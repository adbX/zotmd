"""File manager for markdown file operations."""

import ctypes
import errno
import hashlib
import logging
import os
import secrets
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..utils.filename_sanitizer import FilenameSanitizer

logger = logging.getLogger(__name__)

FileIdentity = tuple[int, int]
MutationGuard = Callable[[], None]

_RENAME_SWAP = 0x00000002
_RENAME_EXCL = 0x00000004
_ATTR_BIT_MAP_COUNT = 5
_ATTR_VOL_CAPABILITIES = 0x00020000
_ATTR_VOL_INFO = 0x80000000
_VOL_CAPABILITIES_INTERFACES = 1
_VOL_CAP_INT_RENAME_SWAP = 0x00040000
_VOL_CAP_INT_RENAME_EXCL = 0x00080000


class _AttrList(ctypes.Structure):
    _fields_ = [
        ("bitmapcount", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16),
        ("commonattr", ctypes.c_uint32),
        ("volattr", ctypes.c_uint32),
        ("dirattr", ctypes.c_uint32),
        ("fileattr", ctypes.c_uint32),
        ("forkattr", ctypes.c_uint32),
    ]


class _VolumeCapabilities(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32 * 4),
        ("valid", ctypes.c_uint32 * 4),
    ]


if sys.platform == "darwin":
    _libc = ctypes.CDLL(None, use_errno=True)
    _renameatx_np = _libc.renameatx_np
    _renameatx_np.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    _renameatx_np.restype = ctypes.c_int
    _fgetattrlist = _libc.fgetattrlist
    _fgetattrlist.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(_AttrList),
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint,
    ]
    _fgetattrlist.restype = ctypes.c_int
else:
    _renameatx_np = None
    _fgetattrlist = None


class ReadOnlyFileManagerError(RuntimeError):
    """Raised when filesystem mutation is attempted in read-only mode."""


class AtomicRenameUnavailable(RuntimeError):
    """Raised when a filesystem cannot provide safe atomic rename operations."""


@dataclass
class PathOperation:
    """Filesystem identities owned by one attempted mutation."""

    source_identity: FileIdentity | None = None
    target_identity: FileIdentity | None = None
    target_claimed: bool = False
    source_removed: bool = False
    source_mode: int | None = None

    def reset(self) -> None:
        """Clear outcomes before reusing an operation receipt."""
        self.source_identity = None
        self.target_identity = None
        self.target_claimed = False
        self.source_removed = False
        self.source_mode = None


@dataclass
class _TemporaryFile:
    path: Path
    descriptor: int
    identity: FileIdentity


class FileManager:
    """Manage markdown file operations."""

    def __init__(
        self,
        base_dir: Path,
        deletion_behavior: str = "move",
        *,
        create: bool = True,
        read_only: bool = False,
    ) -> None:
        """Initialize the manager, optionally creating its directories."""
        if deletion_behavior not in {"move", "delete"}:
            raise ValueError("deletion_behavior must be 'move' or 'delete'")

        self.base_dir = Path(base_dir)
        self.deletion_behavior = deletion_behavior
        self.read_only = read_only
        self.removed_dir = (
            self.base_dir / "removed" if deletion_behavior == "move" else None
        )
        self._directories_ready = False

        if create:
            self.ensure_directories()

        logger.info(
            "FileManager initialized: base=%s, deletion=%s, create=%s",
            self.base_dir,
            deletion_behavior,
            create,
        )

    def ensure_directories(self) -> tuple[FileIdentity, FileIdentity | None]:
        """Create configured directories without following symbolic links."""
        self._require_writable()
        self._require_atomic_rename_path(self.base_dir)
        base_fd = self._open_or_create_directory(
            self.base_dir,
            "Output directory",
        )
        removed_fd: int | None = None
        try:
            self._require_atomic_rename_support(
                base_fd,
                _VOL_CAP_INT_RENAME_SWAP | _VOL_CAP_INT_RENAME_EXCL,
            )
            base_stat = os.fstat(base_fd)
            base_identity = (base_stat.st_dev, base_stat.st_ino)
            removed_identity = None
            if self.removed_dir is not None:
                removed_fd = self._open_or_create_child_directory(
                    base_fd,
                    self.removed_dir,
                    "Removed directory",
                )
                self._require_atomic_rename_support(
                    removed_fd,
                    _VOL_CAP_INT_RENAME_SWAP | _VOL_CAP_INT_RENAME_EXCL,
                )
                removed_stat = os.fstat(removed_fd)
                removed_identity = (removed_stat.st_dev, removed_stat.st_ino)
        finally:
            if removed_fd is not None:
                os.close(removed_fd)
            os.close(base_fd)
        self._directories_ready = True
        return base_identity, removed_identity

    @staticmethod
    def _directory_flags() -> int:
        return (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )

    @classmethod
    def _require_atomic_rename_path(cls, path: Path) -> None:
        candidate = path.expanduser()
        while True:
            try:
                descriptor = os.open(candidate, cls._directory_flags())
            except (FileNotFoundError, NotADirectoryError):
                parent = candidate.parent
                if parent == candidate:
                    raise AtomicRenameUnavailable(
                        f"Cannot inspect filesystem capabilities for {path}"
                    ) from None
                candidate = parent
                continue
            try:
                cls._require_atomic_rename_support(
                    descriptor,
                    _VOL_CAP_INT_RENAME_SWAP | _VOL_CAP_INT_RENAME_EXCL,
                )
            finally:
                os.close(descriptor)
            return

    @staticmethod
    def _require_atomic_rename_support(descriptor: int, capabilities: int) -> None:
        if _fgetattrlist is None:
            raise AtomicRenameUnavailable(
                "Safe filesystem mutations require macOS atomic rename support"
            )

        attributes = _AttrList(
            bitmapcount=_ATTR_BIT_MAP_COUNT,
            reserved=0,
            commonattr=0,
            volattr=_ATTR_VOL_INFO | _ATTR_VOL_CAPABILITIES,
            dirattr=0,
            fileattr=0,
            forkattr=0,
        )
        volume = _VolumeCapabilities()
        ctypes.set_errno(0)
        result = _fgetattrlist(
            descriptor,
            ctypes.byref(attributes),
            ctypes.byref(volume),
            ctypes.sizeof(volume),
            0,
        )
        if result != 0:
            code = ctypes.get_errno()
            error = OSError(code, os.strerror(code))
            raise AtomicRenameUnavailable(
                "Could not confirm atomic rename support for the output filesystem"
            ) from error

        supported = volume.capabilities[_VOL_CAPABILITIES_INTERFACES]
        valid = volume.valid[_VOL_CAPABILITIES_INTERFACES]
        if volume.length != ctypes.sizeof(volume) or (
            valid & capabilities != capabilities
            or supported & capabilities != capabilities
        ):
            raise AtomicRenameUnavailable(
                "The output filesystem does not support safe atomic rename operations"
            )

    @classmethod
    def _native_rename(
        cls,
        source: Path,
        target: Path,
        source_fd: int | None,
        target_fd: int | None,
        flag: int,
    ) -> None:
        if _renameatx_np is None or source_fd is None or target_fd is None:
            raise AtomicRenameUnavailable(
                "Safe filesystem mutations require macOS atomic rename support"
            )
        if "/" in source.name or "/" in target.name:
            raise ValueError("Atomic rename paths must be single path components")

        capability = (
            _VOL_CAP_INT_RENAME_SWAP
            if flag == _RENAME_SWAP
            else _VOL_CAP_INT_RENAME_EXCL
        )
        cls._require_atomic_rename_support(source_fd, capability)
        cls._require_atomic_rename_support(target_fd, capability)
        if os.fstat(source_fd).st_dev != os.fstat(target_fd).st_dev:
            raise OSError(
                errno.EXDEV,
                os.strerror(errno.EXDEV),
                source,
                None,
                target,
            )

        ctypes.set_errno(0)
        result = _renameatx_np(
            source_fd,
            os.fsencode(source.name),
            target_fd,
            os.fsencode(target.name),
            flag,
        )
        if result == 0:
            return
        code = ctypes.get_errno()
        if code == errno.ENOTSUP:
            raise AtomicRenameUnavailable(
                "The output filesystem rejected a required atomic rename operation"
            )
        raise OSError(code, os.strerror(code), source, None, target)

    @classmethod
    def _exchange_entries(
        cls,
        source: Path,
        target: Path,
        source_fd: int | None,
        target_fd: int | None,
    ) -> None:
        cls._native_rename(source, target, source_fd, target_fd, _RENAME_SWAP)

    @classmethod
    def _rename_exclusive(
        cls,
        source: Path,
        target: Path,
        source_fd: int | None,
        target_fd: int | None,
    ) -> None:
        cls._native_rename(source, target, source_fd, target_fd, _RENAME_EXCL)

    @classmethod
    def _open_or_create_child_directory(
        cls,
        parent_fd: int,
        path: Path,
        label: str,
    ) -> int:
        flags = cls._directory_flags()
        created = False
        try:
            return os.open(path.name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            try:
                os.mkdir(path.name, dir_fd=parent_fd)
                created = True
            except FileExistsError:
                pass
        except OSError as error:
            cls._raise_if_symlink(parent_fd, path, label, error)
            raise
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        except OSError as error:
            cls._raise_if_symlink(parent_fd, path, label, error)
            raise
        if created:
            try:
                os.fsync(descriptor)
                os.fsync(parent_fd)
            except BaseException:
                os.close(descriptor)
                raise
        return descriptor

    @staticmethod
    def _raise_if_symlink(
        parent_fd: int,
        path: Path,
        label: str,
        error: OSError,
    ) -> None:
        try:
            entry = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            return
        if stat.S_ISLNK(entry.st_mode):
            raise ValueError(f"{label} must not be a symbolic link: {path}") from error

    @classmethod
    def _open_or_create_directory(cls, path: Path, label: str) -> int:
        expanded = path.expanduser()
        flags = cls._directory_flags()
        if expanded.is_absolute():
            descriptor = os.open(expanded.anchor, flags)
            parts = expanded.parts[1:]
        else:
            descriptor = os.open(".", flags)
            parts = expanded.parts

        try:
            for index, _part in enumerate(parts):
                current_path = (
                    Path(*expanded.parts[: index + 2])
                    if expanded.is_absolute()
                    else Path(*parts[: index + 1])
                )
                next_descriptor = cls._open_or_create_child_directory(
                    descriptor,
                    current_path,
                    label,
                )
                os.close(descriptor)
                descriptor = next_descriptor
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def ensure_parent_directory(self, file_path: Path | str) -> None:
        """Create a target parent within the configured output root."""
        self._require_writable()
        self._require_directories()
        parent = Path(file_path).parent.resolve()
        base = self.base_dir.resolve()
        if not parent.is_relative_to(base):
            raise ValueError(f"Target parent is outside the output root: {parent}")
        descriptor = self._open_or_create_directory(parent, "Target parent")
        os.close(descriptor)

    def require_atomic_mutations(self, directory: Path | str) -> None:
        """Require a directory's filesystem to support safe note mutations."""
        self._require_atomic_rename_path(Path(directory))

    def _require_directories(self) -> None:
        if not self._directories_ready:
            raise RuntimeError(
                "Directories must be created before performing file mutations"
            )

    def _require_writable(self) -> None:
        if self.read_only:
            raise ReadOnlyFileManagerError("FileManager is read-only")

    def get_file_path(self, citation_key: str) -> Path:
        """Return the sanitized markdown path for a citation key."""
        filename = FilenameSanitizer.add_extension(citation_key, "md")
        return self.base_dir / filename

    def file_exists(self, citation_key: str) -> bool:
        """Return whether the markdown file for a citation key exists."""
        return self.get_file_path(citation_key).exists()

    def read_existing(self, citation_key: str) -> str | None:
        """Read a citation key's markdown file, or return None if it is missing."""
        return self.read_path(self.get_file_path(citation_key))

    def read_path(self, file_path: Path | str) -> str | None:
        """Read an actual stored path, or return None if it is missing."""
        path = Path(file_path)
        try:
            with path.open(encoding="utf-8", newline="") as source_file:
                content = source_file.read()
        except FileNotFoundError:
            return None

        logger.debug("Read existing file: %s", path)
        return content

    def read_path_with_identity(
        self, file_path: Path | str
    ) -> tuple[str | None, FileIdentity | None]:
        """Read a regular file and return the inode that supplied its content."""
        path = Path(file_path)
        try:
            descriptor = self._open_entry(path, None, os.O_RDONLY)
        except (FileNotFoundError, NotADirectoryError):
            return None, None
        try:
            file_stat = os.fstat(descriptor)
            identity = (file_stat.st_dev, file_stat.st_ino)
            source_file = os.fdopen(descriptor, "r", encoding="utf-8", newline="")
            descriptor = -1
            with source_file:
                content = source_file.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        logger.debug("Read existing file: %s", path)
        return content, identity

    @classmethod
    def _create_temporary(
        cls,
        target: Path,
        purpose: str,
        parent_fd: int | None,
    ) -> _TemporaryFile:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        for _ in range(100):
            name = f".{target.name}.{secrets.token_hex(8)}.{purpose}"
            path = target.parent / name
            try:
                descriptor = (
                    os.open(path, flags, 0o600)
                    if parent_fd is None
                    else os.open(name, flags, 0o600, dir_fd=parent_fd)
                )
            except FileExistsError:
                continue
            try:
                file_stat = os.fstat(descriptor)
            except BaseException:
                os.close(descriptor)
                try:
                    cls._unlink_entry(path, parent_fd)
                except BaseException:
                    pass
                raise
            return _TemporaryFile(
                path,
                descriptor,
                (file_stat.st_dev, file_stat.st_ino),
            )
        raise FileExistsError(f"Could not allocate a temporary file beside {target}")

    @classmethod
    def _create_recovery_copy(
        cls,
        target: Path,
        purpose: str,
        parent_fd: int | None,
        content: bytes,
        mode: int | None,
    ) -> _TemporaryFile:
        recovery = cls._create_temporary(target, purpose, parent_fd)
        try:
            if mode is not None:
                os.fchmod(recovery.descriptor, mode)
            cls._write_descriptor(recovery.descriptor, content)
        except BaseException:
            cls._close_temporary(recovery)
            try:
                cls._remove_owned_entry(
                    recovery.path,
                    recovery.identity,
                    parent_fd,
                )
            except BaseException:
                pass
            raise
        try:
            cls._sync_parent(recovery.path, parent_fd)
        except BaseException as error:
            cls._close_temporary(recovery)
            raise RuntimeError(
                f"Recovery file retained at {recovery.path}; "
                "directory durability could not be confirmed"
            ) from error
        return recovery

    @staticmethod
    def _write_descriptor(descriptor: int, content: bytes) -> None:
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)

    @staticmethod
    def _read_descriptor(descriptor: int) -> bytes:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)

    @classmethod
    def _copy_descriptors(cls, source: int, target: int) -> None:
        source_stat = os.fstat(source)
        os.fchmod(target, stat.S_IMODE(source_stat.st_mode))
        cls._write_descriptor(target, cls._read_descriptor(source))

    @staticmethod
    def _close_temporary(temporary: _TemporaryFile | None) -> None:
        if temporary is not None and temporary.descriptor >= 0:
            os.close(temporary.descriptor)
            temporary.descriptor = -1

    @classmethod
    def _capture_temporary(
        cls,
        path: Path,
        parent_fd: int | None,
    ) -> _TemporaryFile | None:
        identity = cls._entry_identity(path, parent_fd)
        if identity is None:
            return None
        descriptor = cls._open_entry(path, parent_fd, os.O_RDONLY)
        try:
            file_stat = os.fstat(descriptor)
            opened_identity = (file_stat.st_dev, file_stat.st_ino)
            if not stat.S_ISREG(file_stat.st_mode) or opened_identity != identity:
                raise RuntimeError(f"Recovery file changed: {path}")
        except BaseException:
            os.close(descriptor)
            raise
        return _TemporaryFile(path, descriptor, identity)

    def write_path(
        self,
        file_path: Path | str,
        content: str,
        *,
        overwrite: bool = True,
        operation: PathOperation | None = None,
        guard: MutationGuard | None = None,
        expected_target_identity: FileIdentity | None = None,
        expected_target_bytes: bytes | None = None,
        mode: int | None = None,
    ) -> Path:
        """Atomically write content to an explicit target path."""
        self._require_writable()
        self._require_directories()
        self._run_guard(guard)
        target = Path(file_path)
        receipt = operation if operation is not None else PathOperation()
        receipt.reset()
        parent_fd = self._open_guarded_parent(target, guard)
        temporary: _TemporaryFile | None = None
        recovery: _TemporaryFile | None = None
        original_bytes: bytes | None = None
        original_mode: int | None = None
        content_bytes = content.encode("utf-8")

        try:
            assert parent_fd is not None
            self._require_atomic_rename_support(
                parent_fd,
                _VOL_CAP_INT_RENAME_SWAP | _VOL_CAP_INT_RENAME_EXCL,
            )
            original_identity = self._entry_identity(target, parent_fd)
            receipt.source_identity = original_identity
            self._require_expected_file(
                target,
                expected_target_identity,
                expected_target_bytes,
                parent_fd,
            )
            if not overwrite and original_identity is not None:
                raise FileExistsError(target)

            if original_identity is not None:
                source_fd = self._open_entry(target, parent_fd, os.O_RDONLY)
                try:
                    source_stat = os.fstat(source_fd)
                    opened_identity = (source_stat.st_dev, source_stat.st_ino)
                    if opened_identity != original_identity:
                        raise RuntimeError(
                            f"Managed file changed during synchronization: {target}"
                        )
                    original_bytes = self._read_descriptor(source_fd)
                    original_mode = stat.S_IMODE(source_stat.st_mode)
                    if (
                        expected_target_bytes is not None
                        and original_bytes != expected_target_bytes
                    ):
                        raise RuntimeError(
                            f"Managed file changed during synchronization: {target}"
                        )
                finally:
                    os.close(source_fd)

            purpose = "recovery" if original_identity is not None else "tmp"
            temporary = self._create_temporary(target, purpose, parent_fd)
            if original_mode is not None:
                os.fchmod(temporary.descriptor, original_mode)
            elif mode is not None:
                os.fchmod(temporary.descriptor, mode)
            self._write_descriptor(temporary.descriptor, content_bytes)
            self._close_temporary(temporary)

            self._run_guard(guard)
            if not self._matches_owned(temporary.path, temporary.identity, parent_fd):
                raise RuntimeError(f"Temporary file changed: {temporary.path}")
            if self._entry_identity(target, parent_fd) != original_identity:
                raise RuntimeError(
                    f"Managed file changed during synchronization: {target}"
                )

            if overwrite and original_identity is not None:
                try:
                    self._exchange_entries(
                        temporary.path,
                        target,
                        parent_fd,
                        parent_fd,
                    )
                except BaseException:
                    if self._matches_owned(
                        target,
                        temporary.identity,
                        parent_fd,
                    ):
                        receipt.target_identity = temporary.identity
                        receipt.target_claimed = True
                        recovery = self._capture_temporary(temporary.path, parent_fd)
                        temporary = None
                    raise
                receipt.target_identity = temporary.identity
                receipt.target_claimed = True
                recovery = self._capture_temporary(temporary.path, parent_fd)
                temporary = None
                if recovery is None:
                    raise RuntimeError(
                        f"Previous file disappeared during synchronization: {target}"
                    )
            else:
                try:
                    self._rename_exclusive(
                        temporary.path,
                        target,
                        parent_fd,
                        parent_fd,
                    )
                except BaseException as error:
                    if not self._is_exists_error(error) and self._matches_owned(
                        target,
                        temporary.identity,
                        parent_fd,
                    ):
                        receipt.target_identity = temporary.identity
                        receipt.target_claimed = True
                    raise
                receipt.target_identity = temporary.identity
                receipt.target_claimed = True
                temporary = None

            self._sync_parent(target, parent_fd)
            self._run_guard(guard)
            assert receipt.target_identity is not None
            self._require_expected_file(
                target,
                receipt.target_identity,
                content_bytes,
                parent_fd,
            )

            if recovery is not None:
                self._run_guard(guard)
                assert original_bytes is not None
                self._require_expected_file(
                    recovery.path,
                    receipt.source_identity,
                    original_bytes,
                    parent_fd,
                )
                if not self._remove_owned_entry(
                    recovery.path,
                    recovery.identity,
                    parent_fd,
                ):
                    raise RuntimeError(f"Recovery file changed: {recovery.path}")
                self._close_temporary(recovery)
                recovery = None
        except BaseException as error:
            retained_recovery: Path | None = None
            retained_target: Path | None = None
            rollback_error: BaseException | None = None
            try:
                if temporary is not None and self._matches_owned(
                    target,
                    temporary.identity,
                    parent_fd,
                ):
                    receipt.target_identity = temporary.identity
                    receipt.target_claimed = True
                    recovery = self._capture_temporary(temporary.path, parent_fd)
                    temporary = None
                elif (
                    temporary is not None
                    and original_bytes is not None
                    and self._entry_identity(temporary.path, parent_fd)
                    != temporary.identity
                ):
                    recovery = self._capture_temporary(temporary.path, parent_fd)
                    temporary = None
                target_is_replacement = self._matches_owned(
                    target,
                    receipt.target_identity,
                    parent_fd,
                )
                original_still_present = self._matches_owned(
                    target,
                    receipt.source_identity,
                    parent_fd,
                )
                recovery_changed = (
                    recovery is not None
                    and original_bytes is not None
                    and self._matches_owned(
                        recovery.path,
                        recovery.identity,
                        parent_fd,
                    )
                    and self._read_descriptor(recovery.descriptor) != original_bytes
                )
                if recovery_changed:
                    assert recovery is not None
                    retained_recovery = recovery.path
                elif original_bytes is not None and target_is_replacement:
                    if recovery is None or not self._matches_owned(
                        recovery.path,
                        recovery.identity,
                        parent_fd,
                    ):
                        replacement_recovery = self._create_recovery_copy(
                            target,
                            "recovery",
                            parent_fd,
                            original_bytes,
                            original_mode,
                        )
                        self._close_temporary(recovery)
                        recovery = replacement_recovery
                    retained_recovery = recovery.path
                elif recovery is not None and not original_still_present:
                    retained_recovery = recovery.path
                elif recovery is not None:
                    if recovery_changed:
                        retained_recovery = recovery.path
                    else:
                        self._remove_owned_entry(
                            recovery.path,
                            recovery.identity,
                            parent_fd,
                        )
                elif receipt.target_claimed and target_is_replacement:
                    retained_target = target
            except BaseException as caught:
                rollback_error = caught
                try:
                    recovery_is_valid = (
                        recovery is not None
                        and original_bytes is not None
                        and self._matches_owned(
                            recovery.path,
                            recovery.identity,
                            parent_fd,
                        )
                        and self._read_descriptor(recovery.descriptor) == original_bytes
                    )
                except BaseException:
                    recovery_is_valid = False
                if recovery_is_valid:
                    assert recovery is not None
                    retained_recovery = recovery.path
            finally:
                if temporary is not None:
                    self._close_temporary(temporary)
                    try:
                        self._remove_owned_entry(
                            temporary.path,
                            temporary.identity,
                            parent_fd,
                        )
                    except BaseException as caught:
                        if rollback_error is None:
                            rollback_error = caught
                if retained_recovery is not None and recovery is not None:
                    try:
                        self._sync_entry(
                            recovery.path,
                            recovery.identity,
                            parent_fd,
                        )
                        self._sync_parent(recovery.path, parent_fd)
                    except BaseException as caught:
                        if rollback_error is None:
                            rollback_error = caught
                self._close_temporary(recovery)
                self._close_parent(parent_fd)
            if retained_recovery is not None:
                message = (
                    f"{error}; previous file retained at recovery path: "
                    f"{retained_recovery}"
                )
                if rollback_error is not None:
                    message += f"; write rollback failed: {rollback_error}"
                raise RuntimeError(message) from error
            if retained_target is not None:
                raise RuntimeError(
                    f"{error}; created file retained for recovery at {retained_target}"
                ) from error
            if rollback_error is not None:
                raise RuntimeError(
                    f"{error}; write rollback failed: {rollback_error}"
                ) from error
            raise

        self._close_parent(parent_fd)
        logger.info("Wrote markdown file: %s", target)
        return target

    @staticmethod
    def _same_file(first: Path | None, second: Path) -> bool:
        if first is None or not os.path.lexists(first) or not os.path.lexists(second):
            return False
        try:
            return os.path.samefile(first, second)
        except OSError:
            return False

    @staticmethod
    def path_identity(path: Path | str) -> FileIdentity | None:
        """Return a path entry's device and inode without following symlinks."""
        try:
            stat = os.lstat(path)
        except (FileNotFoundError, NotADirectoryError):
            return None
        return stat.st_dev, stat.st_ino

    @classmethod
    def path_matches(
        cls,
        path: Path | str,
        identity: FileIdentity | None,
    ) -> bool:
        """Return whether a pathname still names the expected entry."""
        return identity is not None and cls.path_identity(path) == identity

    @classmethod
    def paths_alias(cls, first: Path | str, second: Path | str) -> bool:
        """Return whether two pathnames currently identify the same entry."""
        return cls._same_file(Path(first), Path(second))

    def verify_path(
        self,
        file_path: Path | str,
        expected_identity: FileIdentity,
        expected_sha256: str,
        *,
        guard: MutationGuard | None = None,
    ) -> None:
        """Require a regular file to retain its identity and exact content hash."""
        path = Path(file_path)
        parent_fd = self._open_guarded_parent(path, guard)
        descriptor = -1
        try:
            descriptor = self._open_entry(path, parent_fd, os.O_RDONLY)
            file_stat = os.fstat(descriptor)
            identity = (file_stat.st_dev, file_stat.st_ino)
            content_hash = hashlib.sha256(self._read_descriptor(descriptor)).hexdigest()
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or identity != expected_identity
                or content_hash != expected_sha256
            ):
                raise RuntimeError(
                    f"Managed file changed during synchronization: {path}"
                )
            self._run_guard(guard)
            if self._entry_identity(path, parent_fd) != expected_identity:
                raise RuntimeError(
                    f"Managed file changed during synchronization: {path}"
                )
        except OSError as error:
            raise RuntimeError(
                f"Managed file changed during synchronization: {path}"
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            self._close_parent(parent_fd)

    def require_path_absent(
        self,
        file_path: Path | str,
        *,
        guard: MutationGuard | None = None,
    ) -> None:
        """Require a pathname vacated by a managed rename to remain absent."""
        path = Path(file_path)
        parent_fd = self._open_guarded_parent(path, guard)
        try:
            if self._entry_identity(path, parent_fd) is not None:
                raise RuntimeError(
                    f"Vacated managed path was recreated during synchronization: {path}"
                )
            self._run_guard(guard)
        finally:
            self._close_parent(parent_fd)

    @staticmethod
    def _open_entry(path: Path, parent_fd: int | None, flags: int) -> int:
        flags |= getattr(os, "O_NOFOLLOW", 0)
        if parent_fd is None:
            return os.open(path, flags)
        return os.open(path.name, flags, dir_fd=parent_fd)

    @classmethod
    def _require_expected_file(
        cls,
        path: Path,
        expected_identity: FileIdentity | None,
        expected_bytes: bytes | None,
        parent_fd: int | None = None,
    ) -> None:
        if expected_identity is None and expected_bytes is None:
            return

        try:
            descriptor = cls._open_entry(path, parent_fd, os.O_RDONLY)
        except OSError as error:
            raise RuntimeError(
                f"Managed file changed during synchronization: {path}"
            ) from error

        try:
            stat = os.fstat(descriptor)
            identity = (stat.st_dev, stat.st_ino)
            with os.fdopen(descriptor, "rb") as source_file:
                descriptor = -1
                content = source_file.read() if expected_bytes is not None else None
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        if expected_identity is not None and identity != expected_identity:
            raise RuntimeError(f"Managed file changed during synchronization: {path}")
        if expected_bytes is not None and content != expected_bytes:
            raise RuntimeError(f"Managed file changed during synchronization: {path}")

    @staticmethod
    def _open_guarded_parent(
        path: Path,
        guard: MutationGuard | None,
    ) -> int | None:
        FileManager._run_guard(guard)
        descriptor = os.open(path.parent, FileManager._directory_flags())
        try:
            FileManager._run_guard(guard)
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    @staticmethod
    def _close_parent(descriptor: int | None) -> None:
        if descriptor is not None:
            os.close(descriptor)

    @classmethod
    def _sync_parent(cls, path: Path, parent_fd: int | None) -> None:
        if parent_fd is not None:
            os.fsync(parent_fd)
            return
        descriptor = os.open(path.parent, cls._directory_flags())
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _sync_entry(
        cls,
        path: Path,
        expected_identity: FileIdentity,
        parent_fd: int | None,
    ) -> None:
        descriptor = cls._open_entry(path, parent_fd, os.O_RDONLY)
        try:
            file_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or (file_stat.st_dev, file_stat.st_ino) != expected_identity
            ):
                raise RuntimeError(
                    f"Managed file changed during synchronization: {path}"
                )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _identity_at(descriptor: int, name: str) -> FileIdentity | None:
        try:
            stat = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return None
        return stat.st_dev, stat.st_ino

    @classmethod
    def _entry_identity(
        cls,
        path: Path,
        parent_fd: int | None,
    ) -> FileIdentity | None:
        if parent_fd is None:
            return cls.path_identity(path)
        return cls._identity_at(parent_fd, path.name)

    @classmethod
    def _link_entries(
        cls,
        source: Path,
        target: Path,
        source_fd: int | None,
        target_fd: int | None,
    ) -> None:
        if source_fd is None or target_fd is None:
            os.link(source, target)
        else:
            os.link(
                source.name,
                target.name,
                src_dir_fd=source_fd,
                dst_dir_fd=target_fd,
            )

    @classmethod
    def _unlink_entry(cls, path: Path, parent_fd: int | None) -> None:
        if parent_fd is None:
            path.unlink()
        else:
            os.unlink(path.name, dir_fd=parent_fd)
        cls._sync_parent(path, parent_fd)

    @classmethod
    def _copy_entry_at(
        cls,
        source: Path,
        target: Path,
        source_fd: int | None,
        target_fd: int | None,
        source_identity: FileIdentity,
    ) -> None:
        read_fd = cls._open_entry(source, source_fd, os.O_RDONLY)
        temporary: _TemporaryFile | None = None
        try:
            source_stat = os.fstat(read_fd)
            if (source_stat.st_dev, source_stat.st_ino) != source_identity:
                raise RuntimeError(
                    f"Managed file changed during synchronization: {source}"
                )
            source_content = cls._read_descriptor(read_fd)
            temporary = cls._create_temporary(target, "restore", target_fd)
            os.fchmod(temporary.descriptor, stat.S_IMODE(source_stat.st_mode))
            cls._write_descriptor(temporary.descriptor, source_content)
            cls._close_temporary(temporary)
            cls._rename_exclusive(
                temporary.path,
                target,
                target_fd,
                target_fd,
            )
            temporary = None
            cls._sync_parent(target, target_fd)
        finally:
            os.close(read_fd)
            cls._close_temporary(temporary)
            if temporary is not None:
                cls._remove_owned_entry(
                    temporary.path,
                    temporary.identity,
                    target_fd,
                )

    @classmethod
    def _matches_owned(
        cls,
        path: Path | None,
        identity: FileIdentity | None,
        parent_fd: int | None,
    ) -> bool:
        if path is None or identity is None:
            return False
        if parent_fd is None:
            return cls.path_matches(path, identity)
        return cls._identity_at(parent_fd, path.name) == identity

    @classmethod
    def _remove_owned_entry(
        cls,
        path: Path | None,
        identity: FileIdentity | None,
        parent_fd: int | None,
    ) -> bool:
        if path is None or identity is None:
            return False
        if parent_fd is None:
            return cls._remove_owned(path, identity)
        if cls._identity_at(parent_fd, path.name) != identity:
            return False
        os.unlink(path.name, dir_fd=parent_fd)
        cls._sync_parent(path, parent_fd)
        return True

    @staticmethod
    def _run_guard(guard: MutationGuard | None) -> None:
        if guard is not None:
            guard()

    @classmethod
    def guard_passes(cls, guard: MutationGuard | None) -> bool:
        """Return whether a mutation guard still accepts the current layout."""
        try:
            cls._run_guard(guard)
        except BaseException:
            return False
        return True

    @staticmethod
    def _is_exists_error(error: BaseException) -> bool:
        return isinstance(error, OSError) and error.errno == errno.EEXIST

    @staticmethod
    def _is_link_unsupported(error: BaseException) -> bool:
        return isinstance(error, OSError) and error.errno in {
            errno.EXDEV,
            errno.EPERM,
            errno.ENOSYS,
            errno.ENOTSUP,
        }

    @classmethod
    def _remove_owned(
        cls,
        path: Path | None,
        identity: FileIdentity | None,
    ) -> bool:
        if path is None or not cls.path_matches(path, identity):
            return False
        os.unlink(path)
        cls._sync_parent(path, None)
        return True

    @classmethod
    def _restore_bytes_at(
        cls,
        content: bytes,
        mode: int | None,
        target: Path,
        parent_fd: int,
    ) -> None:
        temporary: _TemporaryFile | None = cls._create_temporary(
            target,
            "restore",
            parent_fd,
        )
        try:
            assert temporary is not None
            if mode is not None:
                os.fchmod(temporary.descriptor, mode)
            cls._write_descriptor(temporary.descriptor, content)
            cls._close_temporary(temporary)
            cls._rename_exclusive(
                temporary.path,
                target,
                parent_fd,
                parent_fd,
            )
            temporary = None
            cls._sync_parent(target, parent_fd)
        finally:
            cls._close_temporary(temporary)
            if temporary is not None:
                cls._remove_owned_entry(
                    temporary.path,
                    temporary.identity,
                    parent_fd,
                )

    def write_markdown(self, citation_key: str, content: str) -> Path:
        """Atomically write the markdown file for a citation key."""
        self._require_writable()
        return self.write_path(self.get_file_path(citation_key), content)

    def move_path(
        self,
        source_path: Path | str,
        target_path: Path | str,
        *,
        operation: PathOperation | None = None,
        guard: MutationGuard | None = None,
        expected_source_identity: FileIdentity | None = None,
        expected_source_bytes: bytes | None = None,
    ) -> Path:
        """Move an actual stored path to an explicit target without overwriting."""
        self._require_writable()
        self._require_directories()
        self._run_guard(guard)
        source = Path(source_path)
        target = Path(target_path)
        receipt = operation if operation is not None else PathOperation()
        receipt.reset()
        receipt.source_identity = self.path_identity(source)

        if receipt.source_identity is None or not source.exists():
            raise FileNotFoundError(source)
        self._require_expected_file(
            source,
            expected_source_identity,
            expected_source_bytes,
        )

        source_fd = self._open_guarded_parent(source, guard)
        try:
            target_fd = self._open_guarded_parent(target, guard)
        except BaseException:
            self._close_parent(source_fd)
            raise
        try:
            return self._move_path_open(
                source,
                target,
                receipt,
                guard,
                source_fd,
                target_fd,
                expected_source_bytes,
            )
        finally:
            self._close_parent(target_fd)
            self._close_parent(source_fd)

    def _move_path_open(
        self,
        source: Path,
        target: Path,
        receipt: PathOperation,
        guard: MutationGuard | None,
        source_fd: int | None,
        target_fd: int | None,
        expected_source_bytes: bytes | None,
    ) -> Path:
        """Move a path while guarded parent directory descriptors remain open."""
        source_recovery: _TemporaryFile | None = None
        attempted_recovery: Path | None = None
        source_quarantined = False
        try:
            assert source_fd is not None
            assert target_fd is not None
            self._require_atomic_rename_support(
                source_fd,
                _VOL_CAP_INT_RENAME_EXCL,
            )
            self._require_atomic_rename_support(target_fd, _VOL_CAP_INT_RENAME_EXCL)
            current_source = self._entry_identity(source, source_fd)
            if current_source != receipt.source_identity:
                raise RuntimeError(
                    f"Managed file changed during synchronization: {source}"
                )
            source_descriptor = self._open_entry(source, source_fd, os.O_RDONLY)
            try:
                source_stat = os.fstat(source_descriptor)
                if (source_stat.st_dev, source_stat.st_ino) != receipt.source_identity:
                    raise RuntimeError(
                        f"Managed file changed during synchronization: {source}"
                    )
                operation_source_bytes = self._read_descriptor(source_descriptor)
                receipt.source_mode = stat.S_IMODE(source_stat.st_mode)
            finally:
                os.close(source_descriptor)
            if (
                expected_source_bytes is not None
                and operation_source_bytes != expected_source_bytes
            ):
                raise RuntimeError(
                    f"Managed file changed during synchronization: {source}"
                )
            self._require_expected_file(
                source,
                receipt.source_identity,
                operation_source_bytes,
                source_fd,
            )
            if self._entry_identity(target, target_fd) is not None:
                raise FileExistsError(target)

            try:
                self._run_guard(guard)
                self._require_expected_file(
                    source,
                    receipt.source_identity,
                    operation_source_bytes,
                    source_fd,
                )
                self._link_entries(source, target, source_fd, target_fd)
            except BaseException as error:
                target_existed = self._entry_identity(target, target_fd) is not None
                if target_existed or not self._is_link_unsupported(error):
                    raise
                self._copy_across_filesystems(
                    source,
                    target,
                    receipt,
                    guard,
                    source_fd,
                    target_fd,
                    operation_source_bytes,
                )
            else:
                receipt.target_identity = self._entry_identity(target, target_fd)
                receipt.target_claimed = True
                if receipt.target_identity != receipt.source_identity:
                    raise RuntimeError(
                        f"Managed file changed during synchronization: {source}"
                    )
                self._sync_parent(target, target_fd)

            self._run_guard(guard)
            self._require_expected_file(
                source,
                receipt.source_identity,
                operation_source_bytes,
                source_fd,
            )

            for _ in range(100):
                attempted_recovery = source.parent / (
                    f".{source.name}.{secrets.token_hex(8)}.move-recovery"
                )
                try:
                    self._rename_exclusive(
                        source,
                        attempted_recovery,
                        source_fd,
                        source_fd,
                    )
                except FileExistsError:
                    continue
                source_quarantined = True
                break
            else:
                raise FileExistsError(
                    f"Could not allocate a recovery path beside {source}"
                )

            receipt.source_removed = True
            source_recovery = self._capture_temporary(attempted_recovery, source_fd)
            if source_recovery is None:
                raise RuntimeError(f"Moved file disappeared: {source}")
            self._sync_parent(source, source_fd)
            self._run_guard(guard)
            if self._entry_identity(source, source_fd) is not None:
                raise RuntimeError(
                    f"Vacated managed path was recreated during synchronization: {source}"
                )
            assert receipt.target_identity is not None
            self._require_expected_file(
                target,
                receipt.target_identity,
                operation_source_bytes,
                target_fd,
            )
            self._require_expected_file(
                source_recovery.path,
                receipt.source_identity,
                operation_source_bytes,
                source_fd,
            )
            self._sync_entry(
                source_recovery.path,
                source_recovery.identity,
                source_fd,
            )
            if not self._remove_owned_entry(
                source_recovery.path,
                source_recovery.identity,
                source_fd,
            ):
                raise RuntimeError(f"Recovery file changed: {source_recovery.path}")
            self._close_temporary(source_recovery)
            source_recovery = None
        except BaseException as error:
            if source_recovery is None and attempted_recovery is not None:
                source_recovery = self._capture_temporary(
                    attempted_recovery,
                    source_fd,
                )
                source_quarantined = source_quarantined or source_recovery is not None
            receipt.source_removed = source_quarantined
            retained_source_recovery: Path | None = None
            rollback_error: BaseException | None = None
            recovery_fsync_error: BaseException | None = None
            try:
                current_source = self._entry_identity(source, source_fd)
                if receipt.source_removed and current_source is None:
                    if source_recovery is not None and self._matches_owned(
                        source_recovery.path,
                        source_recovery.identity,
                        source_fd,
                    ):
                        self._rename_exclusive(
                            source_recovery.path,
                            source,
                            source_fd,
                            source_fd,
                        )
                        self._close_temporary(source_recovery)
                        source_recovery = None
                        receipt.source_removed = False
                        receipt.source_identity = self._entry_identity(
                            source, source_fd
                        )
                        current_source = receipt.source_identity
                        self._sync_parent(source, source_fd)
                    elif self._matches_owned(
                        target,
                        receipt.target_identity,
                        target_fd,
                    ):
                        assert receipt.target_identity is not None
                        try:
                            self._link_entries(target, source, target_fd, source_fd)
                            self._sync_parent(source, source_fd)
                        except BaseException as link_error:
                            if self._entry_identity(source, source_fd) is not None:
                                raise
                            if not self._is_link_unsupported(link_error):
                                raise
                            self._copy_entry_at(
                                target,
                                source,
                                target_fd,
                                source_fd,
                                receipt.target_identity,
                            )
                    else:
                        raise RuntimeError(f"Cannot restore moved file: {source}")
                    if receipt.source_removed:
                        receipt.source_removed = False
                        receipt.source_identity = self._entry_identity(
                            source, source_fd
                        )
                        current_source = receipt.source_identity
                if source_recovery is not None and self._matches_owned(
                    source_recovery.path,
                    source_recovery.identity,
                    source_fd,
                ):
                    recovery_is_expected = (
                        source_recovery.identity == receipt.source_identity
                        and self._read_descriptor(source_recovery.descriptor)
                        == operation_source_bytes
                    )
                    if (
                        current_source == receipt.source_identity
                        and recovery_is_expected
                    ):
                        self._remove_owned_entry(
                            source_recovery.path,
                            source_recovery.identity,
                            source_fd,
                        )
                    else:
                        retained_source_recovery = source_recovery.path
            except BaseException as caught:
                rollback_error = caught
                if source_recovery is not None and self._matches_owned(
                    source_recovery.path,
                    source_recovery.identity,
                    source_fd,
                ):
                    retained_source_recovery = source_recovery.path
            finally:
                if retained_source_recovery is not None and source_recovery is not None:
                    try:
                        self._sync_entry(
                            source_recovery.path,
                            source_recovery.identity,
                            source_fd,
                        )
                    except BaseException as caught:
                        recovery_fsync_error = caught
                self._close_temporary(source_recovery)
            target_retained = receipt.target_claimed and self._matches_owned(
                target,
                receipt.target_identity,
                target_fd,
            )
            if retained_source_recovery is not None:
                message = (
                    f"{error}; source retained for recovery at "
                    f"{retained_source_recovery}"
                )
                if rollback_error is not None:
                    message += f"; move rollback failed: {rollback_error}"
                if recovery_fsync_error is not None:
                    message += f"; recovery fsync failed: {recovery_fsync_error}"
                raise RuntimeError(message) from error
            if rollback_error is not None:
                raise RuntimeError(
                    f"{error}; move rollback failed: {rollback_error}"
                ) from error
            if target_retained:
                raise RuntimeError(
                    f"{error}; target retained for recovery at {target}"
                ) from error
            raise

        logger.info("Moved markdown file: %s -> %s", source, target)
        return target

    def rename_path(
        self,
        source_path: Path | str,
        target_path: Path | str,
        *,
        operation: PathOperation | None = None,
        guard: MutationGuard | None = None,
        expected_source_identity: FileIdentity | None = None,
        expected_source_bytes: bytes | None = None,
    ) -> Path:
        """Move a path, using a temporary hop for case-equivalent aliases."""
        self._require_writable()
        self._require_directories()
        self._run_guard(guard)
        source = Path(source_path)
        target = Path(target_path)
        if source == target:
            return target
        if os.path.lexists(target) and self._same_file(source, target):
            temporary = target.parent / (
                f".{target.name}.{secrets.token_hex(8)}.rename"
            )
            first_operation = PathOperation()
            try:
                self.move_path(
                    source,
                    temporary,
                    operation=first_operation,
                    guard=guard,
                    expected_source_identity=expected_source_identity,
                    expected_source_bytes=expected_source_bytes,
                )
            except BaseException:
                if first_operation.target_claimed and not source.exists():
                    self.move_path(
                        temporary,
                        source,
                        guard=guard,
                        expected_source_identity=first_operation.target_identity,
                        expected_source_bytes=expected_source_bytes,
                    )
                raise
            try:
                return self.move_path(
                    temporary,
                    target,
                    operation=operation,
                    guard=guard,
                    expected_source_identity=expected_source_identity,
                    expected_source_bytes=expected_source_bytes,
                )
            except BaseException:
                if temporary.exists() and not source.exists():
                    self.move_path(
                        temporary,
                        source,
                        guard=guard,
                        expected_source_identity=first_operation.target_identity,
                        expected_source_bytes=expected_source_bytes,
                    )
                raise
        return self.move_path(
            source,
            target,
            operation=operation,
            guard=guard,
            expected_source_identity=expected_source_identity,
            expected_source_bytes=expected_source_bytes,
        )

    def _copy_across_filesystems(
        self,
        source: Path,
        target: Path,
        receipt: PathOperation,
        guard: MutationGuard | None,
        source_fd: int | None,
        target_fd: int | None,
        expected_source_bytes: bytes | None,
    ) -> None:
        """Durably copy to a new target without overwriting it."""
        temporary: _TemporaryFile | None = self._create_temporary(
            target,
            "copy",
            target_fd,
        )
        try:
            assert temporary is not None
            read_fd = self._open_entry(source, source_fd, os.O_RDONLY)
            try:
                source_stat = os.fstat(read_fd)
                source_identity = (source_stat.st_dev, source_stat.st_ino)
                source_content = self._read_descriptor(read_fd)
                if source_identity != receipt.source_identity or (
                    expected_source_bytes is not None
                    and source_content != expected_source_bytes
                ):
                    raise RuntimeError(
                        f"Managed file changed during synchronization: {source}"
                    )
                os.fchmod(temporary.descriptor, stat.S_IMODE(source_stat.st_mode))
                self._write_descriptor(temporary.descriptor, source_content)
            finally:
                os.close(read_fd)
            self._close_temporary(temporary)
            self._run_guard(guard)
            if not self._matches_owned(
                temporary.path,
                temporary.identity,
                target_fd,
            ):
                raise RuntimeError(f"Temporary file changed: {temporary.path}")
            temporary_identity = temporary.identity
            try:
                self._rename_exclusive(
                    temporary.path,
                    target,
                    target_fd,
                    target_fd,
                )
            except BaseException as error:
                if not self._is_exists_error(error) and self._matches_owned(
                    target,
                    temporary_identity,
                    target_fd,
                ):
                    receipt.target_identity = temporary_identity
                    receipt.target_claimed = True
                    temporary = None
                raise
            receipt.target_identity = temporary_identity
            receipt.target_claimed = True
            temporary = None
            self._sync_parent(target, target_fd)
            self._run_guard(guard)
        except BaseException:
            raise
        finally:
            self._close_temporary(temporary)
            if temporary is not None:
                self._remove_owned_entry(
                    temporary.path,
                    temporary.identity,
                    target_fd,
                )
        try:
            self._run_guard(guard)
        except BaseException:
            raise

    def handle_removed_item(self, citation_key: str) -> Path | None:
        """Move or delete a removed item according to the configured behavior."""
        self._require_writable()
        self._require_directories()
        if self.deletion_behavior == "move":
            return self.move_to_removed(citation_key)

        self.delete_file(citation_key)
        return None

    def move_to_removed(self, citation_key: str) -> Path:
        """Move a markdown file to the removed directory without overwriting."""
        self._require_writable()
        self._require_directories()
        if self.removed_dir is None:
            raise RuntimeError("Removed directory is not configured in delete mode")

        source = self.get_file_path(citation_key)
        target = self.removed_dir / source.name
        return self.move_path(source, target)

    def delete_file(self, citation_key: str) -> bool:
        """Delete a markdown file, raising if it is missing or cannot be removed."""
        self._require_writable()
        return self.delete_path(self.get_file_path(citation_key))

    def delete_path(
        self,
        file_path: Path | str,
        *,
        operation: PathOperation | None = None,
        guard: MutationGuard | None = None,
        expected_source_identity: FileIdentity | None = None,
        expected_source_bytes: bytes | None = None,
    ) -> bool:
        """Delete an actual stored path, raising when it cannot be removed."""
        self._require_writable()
        self._require_directories()
        self._run_guard(guard)
        path = Path(file_path)
        receipt = operation if operation is not None else PathOperation()
        receipt.reset()
        parent_fd = self._open_guarded_parent(path, guard)
        recovery: _TemporaryFile | None = None
        attempted_recovery: Path | None = None
        source_quarantined = False
        original_bytes: bytes | None = None
        original_mode: int | None = None
        try:
            assert parent_fd is not None
            self._require_atomic_rename_support(parent_fd, _VOL_CAP_INT_RENAME_EXCL)
            receipt.source_identity = self._entry_identity(path, parent_fd)
            if receipt.source_identity is None:
                raise FileNotFoundError(path)
            self._require_expected_file(
                path,
                expected_source_identity,
                expected_source_bytes,
                parent_fd,
            )
            source_fd = self._open_entry(path, parent_fd, os.O_RDONLY)
            try:
                source_stat = os.fstat(source_fd)
                opened_identity = (source_stat.st_dev, source_stat.st_ino)
                if opened_identity != receipt.source_identity:
                    raise RuntimeError(
                        f"Managed file changed during synchronization: {path}"
                    )
                original_bytes = self._read_descriptor(source_fd)
                original_mode = stat.S_IMODE(source_stat.st_mode)
                receipt.source_mode = original_mode
                if (
                    expected_source_bytes is not None
                    and original_bytes != expected_source_bytes
                ):
                    raise RuntimeError(
                        f"Managed file changed during synchronization: {path}"
                    )
            finally:
                os.close(source_fd)

            self._run_guard(guard)
            self._require_expected_file(
                path,
                receipt.source_identity,
                expected_source_bytes,
                parent_fd,
            )

            for _ in range(100):
                attempted_recovery = path.parent / (
                    f".{path.name}.{secrets.token_hex(8)}.delete-recovery"
                )
                try:
                    self._rename_exclusive(
                        path,
                        attempted_recovery,
                        parent_fd,
                        parent_fd,
                    )
                except FileExistsError:
                    continue
                source_quarantined = True
                break
            else:
                raise FileExistsError(
                    f"Could not allocate a recovery path beside {path}"
                )

            receipt.source_removed = True
            recovery = self._capture_temporary(attempted_recovery, parent_fd)
            if recovery is None:
                raise RuntimeError(f"Deleted file disappeared: {path}")
            self._sync_parent(path, parent_fd)
            self._run_guard(guard)
            if self._entry_identity(path, parent_fd) is not None:
                raise RuntimeError(
                    f"Vacated managed path was recreated during synchronization: {path}"
                )
            self._require_expected_file(
                recovery.path,
                receipt.source_identity,
                original_bytes,
                parent_fd,
            )
            self._sync_entry(
                recovery.path,
                recovery.identity,
                parent_fd,
            )
            if not self._remove_owned_entry(
                recovery.path,
                recovery.identity,
                parent_fd,
            ):
                raise RuntimeError(f"Recovery file changed: {recovery.path}")
            self._close_temporary(recovery)
            recovery = None
        except BaseException as error:
            if recovery is None and attempted_recovery is not None:
                try:
                    recovery = self._capture_temporary(attempted_recovery, parent_fd)
                    source_quarantined = source_quarantined or recovery is not None
                except BaseException as capture_error:
                    self._close_parent(parent_fd)
                    raise RuntimeError(
                        f"{error}; delete recovery inspection failed: {capture_error}"
                    ) from capture_error
            retained_recovery: Path | None = None
            rollback_error: BaseException | None = None
            try:
                current_identity = self._entry_identity(path, parent_fd)
                receipt.source_removed = source_quarantined
                if current_identity is None and receipt.source_removed:
                    assert original_bytes is not None
                    if recovery is not None and self._matches_owned(
                        recovery.path,
                        recovery.identity,
                        parent_fd,
                    ):
                        self._rename_exclusive(
                            recovery.path,
                            path,
                            parent_fd,
                            parent_fd,
                        )
                        self._close_temporary(recovery)
                        recovery = None
                        self._sync_parent(path, parent_fd)
                    else:
                        assert parent_fd is not None
                        self._restore_bytes_at(
                            original_bytes,
                            original_mode,
                            path,
                            parent_fd,
                        )
                        receipt.source_identity = self._entry_identity(path, parent_fd)
                    receipt.source_removed = False
                elif (
                    receipt.source_removed
                    and current_identity != receipt.source_identity
                ):
                    assert original_bytes is not None
                    if recovery is None or not self._matches_owned(
                        recovery.path,
                        recovery.identity,
                        parent_fd,
                    ):
                        replacement_recovery = self._create_recovery_copy(
                            path,
                            "delete-recovery",
                            parent_fd,
                            original_bytes,
                            original_mode,
                        )
                        self._close_temporary(recovery)
                        recovery = replacement_recovery
                    retained_recovery = recovery.path
                if recovery is not None and retained_recovery is None:
                    recovery_is_expected = (
                        recovery.identity == receipt.source_identity
                        and original_bytes is not None
                        and self._read_descriptor(recovery.descriptor) == original_bytes
                    )
                    if (
                        current_identity == receipt.source_identity
                        and recovery_is_expected
                    ):
                        self._remove_owned_entry(
                            recovery.path,
                            recovery.identity,
                            parent_fd,
                        )
                    else:
                        retained_recovery = recovery.path
            except BaseException as caught:
                rollback_error = caught
                try:
                    recovery_is_valid = (
                        recovery is not None
                        and original_bytes is not None
                        and self._matches_owned(
                            recovery.path,
                            recovery.identity,
                            parent_fd,
                        )
                        and self._read_descriptor(recovery.descriptor) == original_bytes
                    )
                except BaseException:
                    recovery_is_valid = False
                if recovery_is_valid:
                    assert recovery is not None
                    retained_recovery = recovery.path
            finally:
                if retained_recovery is not None and recovery is not None:
                    try:
                        self._sync_entry(
                            recovery.path,
                            recovery.identity,
                            parent_fd,
                        )
                    except BaseException as caught:
                        rollback_error = caught
                self._close_temporary(recovery)
                self._close_parent(parent_fd)
            if retained_recovery is not None:
                message = (
                    f"{error}; original retained at recovery path: {retained_recovery}"
                )
                if rollback_error is not None:
                    message += f"; delete rollback failed: {rollback_error}"
                raise RuntimeError(message) from error
            if rollback_error is not None:
                raise RuntimeError(
                    f"{error}; delete rollback failed: {rollback_error}"
                ) from error
            raise
        self._close_parent(parent_fd)
        logger.info("Deleted file: %s", path)
        return True

    def list_all_files(self) -> list[Path]:
        """List markdown files in the base directory."""
        return sorted(self.base_dir.glob("*.md"))

    def list_removed_files(self) -> list[Path]:
        """List markdown files in the removed directory."""
        if self.removed_dir is None:
            return []
        return sorted(self.removed_dir.glob("*.md"))
