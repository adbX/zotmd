"""Immutable records exposed by ZotMD's local paper source API."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal


class AttachmentAvailability(StrEnum):
    """Point-in-time availability of a PDF attachment."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    LINKED = "linked"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class Creator:
    """A Zotero creator with every supplied name component retained."""

    creator_type: str
    first_name: str | None = None
    last_name: str | None = None
    name: str | None = None

    @property
    def display_name(self) -> str:
        """Return the creator's natural display name without changing stored data."""
        if self.name:
            return self.name
        return " ".join(
            component for component in (self.first_name, self.last_name) if component
        )


@dataclass(frozen=True, slots=True)
class Tag:
    """A Zotero tag and its numeric type."""

    name: str
    type: int = 0


@dataclass(frozen=True, slots=True)
class Identifier:
    """A DOI or arXiv identifier in source and matching forms."""

    kind: Literal["doi", "arxiv"]
    raw: str
    normalized: str | None
    aliases: tuple[str, ...] = ()
    source: Literal["field", "extra"] = "field"

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", tuple(self.aliases))


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A stable machine code and privacy-safe explanation."""

    code: str
    message: str
    blocking: bool


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    """Digests and identity of one successfully read stable file."""

    sha256: str
    md5: str
    size: int
    mtime_ns: int
    device: int
    inode: int


class _UnsafePathError(OSError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(errno.EINVAL, message)
        self.code = code


def _open_no_follow(path: Path) -> int:
    """Open an absolute regular file without following any component symlink."""
    if not path.is_absolute() or ".." in path.parts:
        raise _UnsafePathError(
            "unsafe-local-path", "Local path is not absolute and safe"
        )

    components = path.parts[1:]
    if not components:
        raise _UnsafePathError("not-regular-file", "Local path is not a file")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(path.anchor, directory_flags)
    try:
        for component in components[:-1]:
            component_stat = os.stat(
                component, dir_fd=current_fd, follow_symlinks=False
            )
            if stat.S_ISLNK(component_stat.st_mode):
                raise _UnsafePathError(
                    "symlink-local-path", "Local path contains a symbolic link"
                )
            next_fd = os.open(
                component,
                directory_flags | no_follow,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd

        filename = components[-1]
        file_stat = os.stat(filename, dir_fd=current_fd, follow_symlinks=False)
        if stat.S_ISLNK(file_stat.st_mode):
            raise _UnsafePathError(
                "symlink-local-path", "Local path ends in a symbolic link"
            )
        if not stat.S_ISREG(file_stat.st_mode):
            raise _UnsafePathError(
                "not-regular-file", "Local path is not a regular file"
            )

        file_fd = os.open(
            filename,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | no_follow,
            dir_fd=current_fd,
        )
        opened_stat = os.fstat(file_fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            os.close(file_fd)
            raise _UnsafePathError(
                "not-regular-file", "Local path is not a regular file"
            )
        if (opened_stat.st_dev, opened_stat.st_ino) != (
            file_stat.st_dev,
            file_stat.st_ino,
        ):
            os.close(file_fd)
            raise _UnsafePathError(
                "changed-local-file", "Local file changed while it was inspected"
            )
        return file_fd
    finally:
        os.close(current_fd)


def _inspect_local_file(path: Path) -> tuple[os.stat_result | None, str | None]:
    """Inspect a file without reading it and return a stable diagnostic code."""
    try:
        file_fd = _open_no_follow(path)
    except FileNotFoundError:
        return None, "local-file-unavailable"
    except PermissionError:
        return None, "unreadable-local-file"
    except _UnsafePathError as error:
        return None, error.code
    except OSError:
        return None, "invalid-local-file"

    try:
        file_stat = os.fstat(file_fd)
        if file_stat.st_size <= 0:
            return None, "empty-local-file"
        return file_stat, None
    finally:
        os.close(file_fd)


@dataclass(frozen=True, slots=True)
class PdfAttachment:
    """An immutable PDF candidate discovered through Zotero's local API."""

    key: str
    version: int
    parent_key: str
    title: str | None
    filename: str | None
    content_type: str | None
    link_mode: str | None
    enclosure_uri: str | None = field(default=None, repr=False)
    zotero_md5: str | None = None
    zotero_mtime: int | None = None
    path: Path | None = field(default=None, repr=False)
    local_size: int | None = None
    local_mtime_ns: int | None = None
    local_device: int | None = None
    local_inode: int | None = None
    availability: AttachmentAvailability = AttachmentAvailability.UNAVAILABLE
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def conversion_eligible(self) -> bool:
        """Whether this candidate is individually safe for conversion."""
        return self.availability is AttachmentAvailability.AVAILABLE and not any(
            diagnostic.blocking for diagnostic in self.diagnostics
        )

    def fingerprint(self) -> FileFingerprint:
        """Hash one stable read after revalidating the discovered file identity."""
        expected = (
            self.local_device,
            self.local_inode,
            self.local_size,
            self.local_mtime_ns,
        )
        if (
            not self.conversion_eligible
            or self.path is None
            or any(value is None for value in expected)
        ):
            raise OSError(f"Attachment {self.key} is not an available local file")

        try:
            file_fd = _open_no_follow(self.path)
        except OSError:
            raise OSError(
                f"Attachment {self.key} no longer has a safe local path"
            ) from None

        try:
            opened_stat = os.fstat(file_fd)
            opened_identity = (
                opened_stat.st_dev,
                opened_stat.st_ino,
                opened_stat.st_size,
                opened_stat.st_mtime_ns,
            )
            if opened_identity != expected:
                raise OSError(f"Attachment {self.key} changed after it was discovered")

            sha256 = hashlib.sha256()
            md5 = hashlib.md5(usedforsecurity=False)
            while chunk := os.read(file_fd, 1024 * 1024):
                sha256.update(chunk)
                md5.update(chunk)

            final_stat = os.fstat(file_fd)
            final_identity = (
                final_stat.st_dev,
                final_stat.st_ino,
                final_stat.st_size,
                final_stat.st_mtime_ns,
            )
            if final_identity != opened_identity:
                raise OSError(f"Attachment {self.key} changed while it was read")
        except OSError:
            raise OSError(f"Attachment {self.key} could not be read stably") from None
        finally:
            os.close(file_fd)

        md5_hex = md5.hexdigest()
        if self.zotero_md5 is not None and md5_hex != self.zotero_md5.casefold():
            raise ValueError(f"Attachment {self.key} does not match Zotero's MD5")

        return FileFingerprint(
            sha256=sha256.hexdigest(),
            md5=md5_hex,
            size=opened_stat.st_size,
            mtime_ns=opened_stat.st_mtime_ns,
            device=opened_stat.st_dev,
            inode=opened_stat.st_ino,
        )


@dataclass(frozen=True, slots=True)
class Paper:
    """A top-level local Zotero item and its PDF candidates."""

    server_id: str
    library_type: str
    library_id: int
    key: str
    version: int
    item_type: str
    citation_key: str | None
    title: str | None
    creators: tuple[Creator, ...] = ()
    publication_date: str | None = None
    venues: tuple[tuple[str, str], ...] = ()
    venue: str | None = None
    url: str | None = None
    tags: tuple[Tag, ...] = ()
    collection_keys: tuple[str, ...] = ()
    identifiers: tuple[Identifier, ...] = ()
    pdf_attachments: tuple[PdfAttachment, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "creators", tuple(self.creators))
        object.__setattr__(self, "venues", tuple(tuple(venue) for venue in self.venues))
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "collection_keys", tuple(self.collection_keys))
        object.__setattr__(self, "identifiers", tuple(self.identifiers))
        object.__setattr__(self, "pdf_attachments", tuple(self.pdf_attachments))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    @property
    def zotero_uri(self) -> str:
        """Return the personal-library Zotero selection URI."""
        return f"zotero://select/library/items/{self.key}"

    @property
    def primary_pdf(self) -> PdfAttachment | None:
        """Return the sole conversion-eligible PDF when the paper is unblocked."""
        if len(self.pdf_attachments) != 1 or any(
            diagnostic.blocking for diagnostic in self.diagnostics
        ):
            return None
        attachment = self.pdf_attachments[0]
        return attachment if attachment.conversion_eligible else None


__all__ = [
    "AttachmentAvailability",
    "Creator",
    "Diagnostic",
    "FileFingerprint",
    "Identifier",
    "Paper",
    "PdfAttachment",
    "Tag",
]
