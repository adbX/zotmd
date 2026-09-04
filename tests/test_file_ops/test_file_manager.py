"""Tests for strict markdown file management."""

import os
import stat
from errno import ENOTSUP, EXDEV
from pathlib import Path

import pytest

import zotmd.file_ops.file_manager as file_manager_module
from zotmd.file_ops.file_manager import (
    AtomicRenameUnavailable,
    FileManager,
    PathOperation,
    ReadOnlyFileManagerError,
)


def test_rejects_unknown_deletion_behavior_without_creating_directories(tmp_path):
    base_dir = tmp_path / "references"

    with pytest.raises(ValueError, match="must be 'move' or 'delete'"):
        FileManager(base_dir, deletion_behavior="archive")

    assert not base_dir.exists()


def test_move_setup_creates_base_and_removed_directories(tmp_path):
    base_dir = tmp_path / "nested" / "references"

    manager = FileManager(base_dir, deletion_behavior="move")

    assert manager.base_dir == base_dir
    assert manager.removed_dir == base_dir / "removed"
    assert base_dir.is_dir()
    assert manager.removed_dir is not None
    assert manager.removed_dir.is_dir()


def test_move_setup_rejects_symlinked_removed_directory(tmp_path):
    base_dir = tmp_path / "references"
    external = tmp_path / "external"
    base_dir.mkdir()
    external.mkdir()
    (base_dir / "removed").symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="must not be a symbolic link"):
        FileManager(base_dir, deletion_behavior="move")

    assert list(external.iterdir()) == []


def test_ensure_directories_rejects_symlinked_output_without_touching_target(
    tmp_path,
):
    external = tmp_path / "external"
    external.mkdir()
    output = tmp_path / "references"
    output.symlink_to(external, target_is_directory=True)
    manager = FileManager(output, create=False)

    with pytest.raises(ValueError, match="must not be a symbolic link"):
        manager.ensure_directories()

    assert list(external.iterdir()) == []


def test_delete_setup_creates_only_base_directory(tmp_path):
    base_dir = tmp_path / "nested" / "references"

    manager = FileManager(base_dir, deletion_behavior="delete")

    assert manager.base_dir == base_dir
    assert manager.removed_dir is None
    assert base_dir.is_dir()
    assert not (base_dir / "removed").exists()


def test_setup_rejects_unsupported_atomic_filesystem_before_mutation(
    tmp_path, monkeypatch
):
    base_dir = tmp_path / "nested" / "references"

    def reject_filesystem(descriptor, capabilities):
        raise AtomicRenameUnavailable("atomic rename unavailable")

    monkeypatch.setattr(
        FileManager,
        "_require_atomic_rename_support",
        staticmethod(reject_filesystem),
    )

    with pytest.raises(AtomicRenameUnavailable, match="atomic rename unavailable"):
        FileManager(base_dir)

    assert not (tmp_path / "nested").exists()


def test_setup_checks_actual_output_and_removed_filesystems(tmp_path, monkeypatch):
    base_dir = tmp_path / "references"
    removed_dir = base_dir / "removed"
    removed_dir.mkdir(parents=True)
    sentinel = base_dir / "sentinel.md"
    sentinel.write_text("unchanged", encoding="utf-8")
    calls = 0
    original_check = FileManager._require_atomic_rename_support

    def reject_removed(descriptor, capabilities):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise AtomicRenameUnavailable("removed filesystem unsupported")
        original_check(descriptor, capabilities)

    monkeypatch.setattr(
        FileManager,
        "_require_atomic_rename_support",
        staticmethod(reject_removed),
    )

    manager = FileManager(base_dir, create=False)
    with pytest.raises(AtomicRenameUnavailable, match="removed filesystem unsupported"):
        manager.ensure_directories()

    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_create_false_construction_performs_no_filesystem_mutation(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"unchanged")
    base_dir = tmp_path / "nested" / "references"

    manager = FileManager(base_dir, deletion_behavior="move", create=False)

    assert manager.base_dir == base_dir
    assert manager.removed_dir == base_dir / "removed"
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"unchanged"


def test_read_only_construction_refuses_directory_creation(tmp_path):
    base_dir = tmp_path / "nested" / "references"

    with pytest.raises(ReadOnlyFileManagerError, match="read-only"):
        FileManager(base_dir, read_only=True)

    assert not base_dir.exists()


def test_ensure_directories_enables_mutations(tmp_path):
    base_dir = tmp_path / "nested" / "references"
    manager = FileManager(base_dir, create=False)

    manager.ensure_directories()
    written = manager.write_markdown("paper", "content")

    assert base_dir.is_dir()
    assert manager.removed_dir is not None
    assert manager.removed_dir.is_dir()
    assert written.read_text(encoding="utf-8") == "content"


def test_mutations_require_explicit_directory_creation(tmp_path):
    base_dir = tmp_path / "references"
    base_dir.mkdir()
    source = base_dir / "source.md"
    source.write_bytes(b"source")
    manager = FileManager(base_dir, create=False)

    with pytest.raises(RuntimeError, match="Directories must be created"):
        manager.write_markdown("paper", "content")
    with pytest.raises(RuntimeError, match="Directories must be created"):
        manager.write_path(base_dir / "target.md", "content")
    with pytest.raises(RuntimeError, match="Directories must be created"):
        manager.move_path(source, base_dir / "target.md")
    with pytest.raises(RuntimeError, match="Directories must be created"):
        manager.move_to_removed("source")
    with pytest.raises(RuntimeError, match="Directories must be created"):
        manager.delete_file("source")
    with pytest.raises(RuntimeError, match="Directories must be created"):
        manager.delete_path(source)
    with pytest.raises(RuntimeError, match="Directories must be created"):
        manager.handle_removed_item("source")

    assert list(base_dir.iterdir()) == [source]
    assert source.read_bytes() == b"source"


def test_dry_run_can_calculate_and_read_paths_without_mutation(tmp_path):
    base_dir = tmp_path / "references"
    base_dir.mkdir()
    stored_path = tmp_path / "stored-name.md"
    stored_path.write_text("stored", encoding="utf-8")
    generated_path = base_dir / "paper.md"
    generated_path.write_text("generated", encoding="utf-8")
    manager = FileManager(base_dir, create=False, read_only=True)

    assert manager.get_file_path("paper") == generated_path
    assert manager.file_exists("paper") is True
    assert manager.read_existing("paper") == "generated"
    assert manager.read_path(stored_path) == "stored"
    assert manager.list_all_files() == [generated_path]
    assert manager.list_removed_files() == []
    assert stored_path.read_text(encoding="utf-8") == "stored"
    assert generated_path.read_text(encoding="utf-8") == "generated"


def test_read_only_manager_rejects_every_mutator_before_mutation(tmp_path):
    base_dir = tmp_path / "references"
    removed_dir = base_dir / "removed"
    removed_dir.mkdir(parents=True)
    source = base_dir / "source.md"
    source.write_bytes(b"source")
    manager = FileManager(base_dir, create=False, read_only=True)

    def snapshot():
        return [
            (
                path.relative_to(tmp_path),
                path.is_dir(),
                path.read_bytes() if path.is_file() else None,
            )
            for path in sorted(tmp_path.rglob("*"))
        ]

    before = snapshot()
    mutations = [
        manager.ensure_directories,
        lambda: manager.ensure_parent_directory(base_dir / "nested" / "paper.md"),
        lambda: manager.write_path(base_dir / "target.md", "content"),
        lambda: manager.write_markdown("target", "content"),
        lambda: manager.move_path(source, base_dir / "target.md"),
        lambda: manager.rename_path(source, source),
        lambda: manager.handle_removed_item("source"),
        lambda: manager.move_to_removed("source"),
        lambda: manager.delete_file("source"),
        lambda: manager.delete_path(source),
    ]

    for mutation in mutations:
        with pytest.raises(ReadOnlyFileManagerError, match="read-only"):
            mutation()
        assert snapshot() == before


def test_get_file_path_sanitizes_citation_key(tmp_path):
    manager = FileManager(tmp_path / "references", create=False)

    assert manager.get_file_path("Smith: 2024/report?") == (
        manager.base_dir / "Smith_2024report.md"
    )


def test_missing_reads_return_none(tmp_path):
    manager = FileManager(tmp_path / "references", create=False)

    assert manager.file_exists("missing") is False
    assert manager.read_existing("missing") is None
    assert manager.read_path(tmp_path / "stored-missing.md") is None


def test_reads_preserve_crlf_bytes(tmp_path):
    manager = FileManager(tmp_path / "references", create=False)
    stored = tmp_path / "stored.md"
    stored.write_bytes(b"first\r\nsecond\r\n")

    content, identity = manager.read_path_with_identity(stored)

    assert manager.read_path(stored) == "first\r\nsecond\r\n"
    assert content is not None
    assert content.encode("utf-8") == stored.read_bytes()
    assert identity == manager.path_identity(stored)


def test_read_failure_other_than_missing_raises(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references", create=False)
    error = PermissionError("read denied")

    def failing_open(self, *args, **kwargs):
        raise error

    monkeypatch.setattr(Path, "open", failing_open)

    with pytest.raises(PermissionError) as raised:
        manager.read_existing("paper")

    assert raised.value is error


def test_atomic_write_flushes_fsyncs_replaces_and_returns_target(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    target = manager.get_file_path("paper")
    target.write_bytes(b"old bytes")
    fsynced = []
    exchanges = []
    real_fsync = os.fsync
    real_exchange = manager._exchange_entries

    def tracking_fsync(file_descriptor):
        fsynced.append(stat.S_ISDIR(os.fstat(file_descriptor).st_mode))
        real_fsync(file_descriptor)

    def tracking_exchange(source, destination, source_fd, target_fd):
        exchanges.append((source, destination))
        real_exchange(source, destination, source_fd, target_fd)

    monkeypatch.setattr(file_manager_module.os, "fsync", tracking_fsync)
    monkeypatch.setattr(manager, "_exchange_entries", tracking_exchange)

    result = manager.write_path(target, "new Café\n")

    assert result == target
    assert target.read_bytes() == "new Café\n".encode()
    assert False in fsynced
    assert True in fsynced
    assert len(exchanges) == 1
    temporary, destination = exchanges[0]
    assert temporary.parent == target.parent
    assert destination == target
    assert not temporary.exists()


def test_atomic_replace_preserves_existing_mode(tmp_path):
    manager = FileManager(tmp_path / "references")
    target = manager.get_file_path("paper")
    target.write_bytes(b"old bytes")
    target.chmod(0o640)

    manager.write_path(target, "new bytes")

    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_move_fsyncs_source_and_target_directories(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_bytes(b"content")
    target = manager.get_file_path("paper")
    synced_directories = []
    real_fsync = os.fsync

    def tracking_fsync(file_descriptor):
        file_stat = os.fstat(file_descriptor)
        if stat.S_ISDIR(file_stat.st_mode):
            synced_directories.append((file_stat.st_dev, file_stat.st_ino))
        real_fsync(file_descriptor)

    monkeypatch.setattr(file_manager_module.os, "fsync", tracking_fsync)

    manager.move_path(source, target)

    assert manager.path_identity(source.parent) in synced_directories
    assert manager.path_identity(target.parent) in synced_directories


def test_atomic_replace_failure_preserves_old_bytes_and_cleans_temporary(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    target = manager.get_file_path("paper")
    target.write_bytes(b"old bytes")
    error = PermissionError("replace denied")

    def failing_exchange(source, destination, source_fd, target_fd):
        raise error

    monkeypatch.setattr(manager, "_exchange_entries", failing_exchange)

    with pytest.raises(PermissionError) as raised:
        manager.write_markdown("paper", "new content")

    assert raised.value is error
    assert target.read_bytes() == b"old bytes"
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_interrupt_after_atomic_replace_retains_recovery(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    target = manager.write_markdown("paper", "old bytes")
    real_exchange = manager._exchange_entries

    def exchange_then_interrupt(source, destination, source_fd, target_fd):
        real_exchange(source, destination, source_fd, target_fd)
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_exchange_entries", exchange_then_interrupt)

    with pytest.raises(RuntimeError, match="previous file retained at recovery path"):
        manager.write_markdown("paper", "new bytes")

    recovery_files = list(target.parent.glob(f".{target.name}.*.recovery"))
    assert target.read_text(encoding="utf-8") == "new bytes"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "old bytes"


def test_in_place_edit_during_atomic_replace_is_retained_for_recovery(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    target = manager.write_markdown("paper", "original")
    real_exchange = manager._exchange_entries

    def edit_then_exchange(source, destination, source_fd, target_fd):
        target.write_text("concurrent edit", encoding="utf-8")
        return real_exchange(source, destination, source_fd, target_fd)

    monkeypatch.setattr(manager, "_exchange_entries", edit_then_exchange)

    with pytest.raises(RuntimeError, match="previous file retained at recovery path"):
        manager.write_path(target, "replacement")

    recovery_files = list(target.parent.glob(f".{target.name}.*.recovery"))
    assert target.read_text(encoding="utf-8") == "replacement"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "concurrent edit"


def test_atomic_save_immediately_before_exchange_is_retained_for_recovery(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    target = manager.write_markdown("paper", "original")
    real_exchange = manager._exchange_entries

    def save_then_exchange(source, destination, source_fd, target_fd):
        editor_file = target.with_suffix(".editor")
        editor_file.write_text("concurrent save", encoding="utf-8")
        os.replace(editor_file, target)
        real_exchange(source, destination, source_fd, target_fd)

    monkeypatch.setattr(manager, "_exchange_entries", save_then_exchange)

    with pytest.raises(RuntimeError, match="previous file retained at recovery path"):
        manager.write_path(target, "replacement")

    recovery_files = list(target.parent.glob(f".{target.name}.*.recovery"))
    assert target.read_text(encoding="utf-8") == "replacement"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "concurrent save"


def test_output_replacement_during_atomic_replace_preserves_both_roots(
    tmp_path, monkeypatch
):
    output = tmp_path / "references"
    hidden_output = tmp_path / "hidden-references"
    manager = FileManager(output)
    target = manager.write_markdown("paper", "original")
    output_identity = manager.path_identity(output)
    real_exchange = manager._exchange_entries
    replaced = False

    def guard():
        if manager.path_identity(output) != output_identity:
            raise RuntimeError("output directory changed")

    def replace_root_during_exchange(source, destination, source_fd, target_fd):
        nonlocal replaced
        if not replaced and destination == target:
            replaced = True
            output.rename(hidden_output)
            output.mkdir()
            (output / target.name).write_text("competing", encoding="utf-8")
        return real_exchange(source, destination, source_fd, target_fd)

    monkeypatch.setattr(manager, "_exchange_entries", replace_root_during_exchange)

    with pytest.raises(RuntimeError, match="output directory changed"):
        manager.write_path(target, "replacement", guard=guard)

    recovery_files = list(hidden_output.glob(f".{target.name}.*.recovery"))
    assert (hidden_output / target.name).read_text(encoding="utf-8") == "replacement"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "original"
    assert (output / target.name).read_text(encoding="utf-8") == "competing"


def test_atomic_no_clobber_write_refuses_existing_target(tmp_path):
    manager = FileManager(tmp_path / "references")
    target = manager.write_markdown("paper", "original")

    with pytest.raises(FileExistsError):
        manager.write_path(target, "replacement", overwrite=False)

    assert target.read_text(encoding="utf-8") == "original"
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_atomic_fsync_failure_preserves_old_bytes_and_cleans_temporary(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    target = manager.get_file_path("paper")
    target.write_bytes(b"old bytes")
    error = OSError("fsync failed")
    real_fsync = os.fsync

    def failing_fsync(file_descriptor):
        if stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise error
        real_fsync(file_descriptor)

    monkeypatch.setattr(file_manager_module.os, "fsync", failing_fsync)

    with pytest.raises(OSError) as raised:
        manager.write_markdown("paper", "new content")

    assert raised.value is error
    assert target.read_bytes() == b"old bytes"
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_directory_fsync_failure_does_not_overwrite_concurrent_edit(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    target = manager.write_markdown("paper", "original")
    error = OSError("directory fsync failed")
    real_fsync = os.fsync
    failed = False

    def edit_then_fail_directory_fsync(file_descriptor):
        nonlocal failed
        if (
            not failed
            and stat.S_ISDIR(os.fstat(file_descriptor).st_mode)
            and target.read_text(encoding="utf-8") == "replacement"
        ):
            failed = True
            target.write_text("concurrent edit", encoding="utf-8")
            raise error
        real_fsync(file_descriptor)

    monkeypatch.setattr(file_manager_module.os, "fsync", edit_then_fail_directory_fsync)

    with pytest.raises(RuntimeError, match="previous file retained at recovery path"):
        manager.write_path(target, "replacement")

    recovery_files = list(target.parent.glob(f".{target.name}.*.recovery"))
    assert target.read_text(encoding="utf-8") == "concurrent edit"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "original"


def test_new_file_directory_fsync_failure_does_not_remove_concurrent_edit(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    target = manager.get_file_path("paper")
    error = OSError("directory fsync failed")
    real_fsync = os.fsync

    def edit_then_fail_directory_fsync(file_descriptor):
        if stat.S_ISDIR(os.fstat(file_descriptor).st_mode) and target.exists():
            target.write_text("concurrent edit", encoding="utf-8")
            raise error
        real_fsync(file_descriptor)

    monkeypatch.setattr(file_manager_module.os, "fsync", edit_then_fail_directory_fsync)

    with pytest.raises(RuntimeError, match="created file retained for recovery"):
        manager.write_path(target, "new content", overwrite=False)

    assert target.read_text(encoding="utf-8") == "concurrent edit"


def test_repeated_directory_fsync_failures_close_guarded_parent(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    target = manager.write_markdown("paper", "original")
    closed = []
    real_close_parent = manager._close_parent
    real_fsync = os.fsync

    def fail_directory_fsync(file_descriptor):
        if stat.S_ISDIR(os.fstat(file_descriptor).st_mode):
            raise OSError("directory fsync failed")
        real_fsync(file_descriptor)

    def tracking_close_parent(file_descriptor):
        closed.append(file_descriptor)
        real_close_parent(file_descriptor)

    monkeypatch.setattr(file_manager_module.os, "fsync", fail_directory_fsync)
    monkeypatch.setattr(manager, "_close_parent", tracking_close_parent)

    with pytest.raises(RuntimeError, match="previous file retained at recovery path"):
        manager.write_path(target, "replacement", guard=lambda: None)

    assert len(closed) == 1
    with pytest.raises(OSError):
        os.fstat(closed[0])


def test_atomic_write_retains_recovery_when_competitor_blocks_rollback(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    target = manager.write_markdown("paper", "original")
    real_exchange = manager._exchange_entries

    def exchange_with_competitor(source, destination, source_fd, target_fd):
        real_exchange(source, destination, source_fd, target_fd)
        target.unlink()
        target.write_text("competing", encoding="utf-8")
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_exchange_entries", exchange_with_competitor)

    with pytest.raises(RuntimeError, match="previous file retained at recovery path"):
        manager.write_path(target, "replacement")

    recovery_files = list(target.parent.glob(f".{target.name}.*.recovery"))
    assert target.read_text(encoding="utf-8") == "competing"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "original"


def test_atomic_write_does_not_follow_replaced_temporary_path(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    target = manager.write_markdown("paper", "original")
    original_write = manager._write_descriptor
    replacement_path = None

    def replace_temporary(descriptor, content):
        nonlocal replacement_path
        if content == b"replacement":
            identity = os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino
            replacement_path = next(
                path
                for path in target.parent.iterdir()
                if manager.path_identity(path) == identity
            )
            replacement_path.unlink()
            replacement_path.write_text("competing", encoding="utf-8")
        original_write(descriptor, content)

    monkeypatch.setattr(manager, "_write_descriptor", replace_temporary)

    with pytest.raises(RuntimeError, match="Temporary file changed"):
        manager.write_path(target, "replacement")

    assert target.read_text(encoding="utf-8") == "original"
    assert replacement_path is not None
    assert replacement_path.read_text(encoding="utf-8") == "competing"


def test_no_clobber_cleanup_checks_guard_and_preserves_replacement_root(
    tmp_path, monkeypatch
):
    output = tmp_path / "references"
    hidden_output = tmp_path / "hidden-references"
    manager = FileManager(output)
    target = manager.get_file_path("paper")
    output_identity = manager.path_identity(output)
    original_rename = manager._rename_exclusive
    replaced = False

    def guard():
        if manager.path_identity(output) != output_identity:
            raise RuntimeError("output directory changed")

    def rename_then_replace_root(source, destination, source_fd, target_fd):
        nonlocal replaced
        original_rename(source, destination, source_fd, target_fd)
        if not replaced and destination == target:
            replaced = True
            output.rename(hidden_output)
            output.mkdir()
            target.write_text("competing", encoding="utf-8")

    monkeypatch.setattr(manager, "_rename_exclusive", rename_then_replace_root)

    with pytest.raises(RuntimeError, match="output directory changed"):
        manager.write_path(target, "generated", overwrite=False, guard=guard)

    assert target.read_text(encoding="utf-8") == "competing"
    assert (hidden_output / target.name).read_text(encoding="utf-8") == "generated"


def test_move_path_uses_stored_source_and_explicit_target(tmp_path):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored-actual-name.md"
    source.write_bytes(b"content")
    target = manager.get_file_path("new-key")

    moved = manager.move_path(source, target)

    assert moved == target
    assert target.read_bytes() == b"content"
    assert not source.exists()


def test_move_path_collision_does_not_overwrite_or_remove_source(tmp_path):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored-actual-name.md"
    source.write_bytes(b"source")
    target = manager.get_file_path("new-key")
    target.write_bytes(b"target")

    with pytest.raises(FileExistsError):
        manager.move_path(source, target)

    assert source.read_bytes() == b"source"
    assert target.read_bytes() == b"target"


def test_move_path_collision_does_not_unlink_existing_hardlink(tmp_path):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("content", encoding="utf-8")
    target = manager.get_file_path("target")
    os.link(source, target)

    with pytest.raises(FileExistsError):
        manager.move_path(source, target)

    assert source.read_text(encoding="utf-8") == "content"
    assert target.read_text(encoding="utf-8") == "content"


def test_move_target_hardlink_race_is_not_recorded_as_owned(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("content", encoding="utf-8")
    target = manager.get_file_path("target")
    operation = PathOperation()
    real_link = manager._link_entries

    def competing_link(source_path, target_path, *args):
        os.link(source, target)
        real_link(source_path, target_path, *args)

    monkeypatch.setattr(manager, "_link_entries", competing_link)

    with pytest.raises(FileExistsError):
        manager.move_path(source, target, operation=operation)

    assert operation.target_claimed is False
    assert source.read_text(encoding="utf-8") == "content"
    assert target.read_text(encoding="utf-8") == "content"


def test_move_path_missing_source_raises(tmp_path):
    manager = FileManager(tmp_path / "references")

    with pytest.raises(FileNotFoundError):
        manager.move_path(tmp_path / "missing.md", manager.get_file_path("target"))


def test_move_path_filesystem_failure_raises_and_preserves_source(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_bytes(b"source")
    target = manager.get_file_path("target")
    error = PermissionError("move denied")
    real_link = manager._link_entries

    def failing_link(source_path, target_path, source_fd, target_fd):
        if target_path == target:
            raise error
        return real_link(source_path, target_path, source_fd, target_fd)

    monkeypatch.setattr(manager, "_link_entries", failing_link)

    with pytest.raises(PermissionError) as raised:
        manager.move_path(source, target)

    assert raised.value is error
    assert source.read_bytes() == b"source"
    assert not target.exists()


def test_move_link_race_retains_the_linked_competing_source(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("original", encoding="utf-8")
    target = manager.get_file_path("target")
    real_link = manager._link_entries

    def save_then_link(source_path, target_path, *args):
        editor_file = source.with_suffix(".editor")
        editor_file.write_text("concurrent save", encoding="utf-8")
        os.replace(editor_file, source)
        real_link(source_path, target_path, *args)

    monkeypatch.setattr(manager, "_link_entries", save_then_link)

    with pytest.raises(RuntimeError, match="target retained for recovery"):
        manager.move_path(source, target, expected_source_bytes=b"original")

    assert source.read_text(encoding="utf-8") == "concurrent save"
    assert target.read_text(encoding="utf-8") == "concurrent save"


def test_interrupt_after_move_link_retains_both_paths(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("source", encoding="utf-8")
    target = manager.get_file_path("target")
    operation = PathOperation()
    real_link = manager._link_entries

    def link_then_interrupt(source_path, target_path, source_fd, target_fd):
        real_link(source_path, target_path, source_fd, target_fd)
        if target_path == target:
            raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_link_entries", link_then_interrupt)

    with pytest.raises(KeyboardInterrupt):
        manager.move_path(source, target, operation=operation)

    assert operation.target_claimed is False
    assert source.read_text(encoding="utf-8") == "source"
    assert target.read_text(encoding="utf-8") == "source"


def test_output_replacement_during_move_link_preserves_both_roots(
    tmp_path, monkeypatch
):
    output = tmp_path / "references"
    hidden_output = tmp_path / "hidden-references"
    manager = FileManager(output)
    source = manager.write_markdown("old-key", "original")
    target = manager.get_file_path("new-key")
    output_identity = manager.path_identity(output)
    real_link = manager._link_entries
    replaced = False

    def guard():
        if manager.path_identity(output) != output_identity:
            raise RuntimeError("output directory changed")

    def replace_root_during_link(source_path, target_path, source_fd, target_fd):
        nonlocal replaced
        if not replaced and target_path == target:
            replaced = True
            output.rename(hidden_output)
            output.mkdir()
            (output / target.name).write_text("competing", encoding="utf-8")
        return real_link(source_path, target_path, source_fd, target_fd)

    monkeypatch.setattr(manager, "_link_entries", replace_root_during_link)

    with pytest.raises(RuntimeError, match="output directory changed"):
        manager.move_path(source, target, guard=guard)

    assert (hidden_output / source.name).read_text(encoding="utf-8") == "original"
    assert (hidden_output / target.name).read_text(encoding="utf-8") == "original"
    assert (output / target.name).read_text(encoding="utf-8") == "competing"


def test_move_restores_source_when_target_changes_after_source_unlink(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    source = manager.write_markdown("old-key", "original")
    target = manager.get_file_path("new-key")
    replaced = False

    def replace_target_after_unlink():
        nonlocal replaced
        if not replaced and not source.exists() and target.exists():
            replaced = True
            target.unlink()
            target.write_text("competing", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Managed file changed"):
        manager.move_path(
            source,
            target,
            guard=replace_target_after_unlink,
            expected_source_bytes=b"original",
        )

    assert source.read_text(encoding="utf-8") == "original"
    assert target.read_text(encoding="utf-8") == "competing"
    assert list(source.parent.glob(f".{source.name}.*.move-recovery")) == []


def test_move_preserves_atomic_save_made_immediately_before_source_rename(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    source = manager.write_markdown("old-key", "original")
    target = manager.get_file_path("new-key")
    original_rename = manager._rename_exclusive

    def save_then_rename(source_path, target_path, *args):
        if source_path == source and target_path.name.endswith(".move-recovery"):
            editor_file = source.with_suffix(".editor")
            editor_file.write_text("concurrent save", encoding="utf-8")
            os.replace(editor_file, source)
        original_rename(source_path, target_path, *args)

    monkeypatch.setattr(manager, "_rename_exclusive", save_then_rename)

    with pytest.raises(RuntimeError, match="target retained for recovery"):
        manager.move_path(source, target, expected_source_bytes=b"original")

    assert source.read_text(encoding="utf-8") == "concurrent save"
    assert target.read_text(encoding="utf-8") == "original"
    assert list(source.parent.glob(f".{source.name}.*.move-recovery")) == []


def test_move_does_not_restore_source_deleted_immediately_before_rename(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    source = manager.write_markdown("old-key", "original")
    target = manager.get_file_path("new-key")
    original_rename = manager._rename_exclusive

    def delete_then_rename(source_path, target_path, *args):
        if source_path == source and target_path.name.endswith(".move-recovery"):
            source.unlink()
        original_rename(source_path, target_path, *args)

    monkeypatch.setattr(manager, "_rename_exclusive", delete_then_rename)

    with pytest.raises(RuntimeError, match="target retained for recovery"):
        manager.move_path(source, target, expected_source_bytes=b"original")

    assert not source.exists()
    assert target.read_text(encoding="utf-8") == "original"


def test_move_restores_source_when_completed_quarantine_disappears(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    source = manager.write_markdown("old-key", "original")
    target = manager.get_file_path("new-key")
    original_capture = manager._capture_temporary
    removed = False

    def remove_before_capture(path, parent_fd):
        nonlocal removed
        if not removed and path.name.endswith(".move-recovery"):
            removed = True
            path.unlink()
            return None
        return original_capture(path, parent_fd)

    monkeypatch.setattr(manager, "_capture_temporary", remove_before_capture)

    with pytest.raises(RuntimeError, match="target retained for recovery"):
        manager.move_path(source, target, expected_source_bytes=b"original")

    assert source.read_text(encoding="utf-8") == "original"
    assert target.read_text(encoding="utf-8") == "original"


def test_move_rejects_recreated_source_after_unlink(tmp_path):
    manager = FileManager(tmp_path / "references")
    source = manager.write_markdown("old-key", "original")
    target = manager.get_file_path("new-key")
    recreated = False

    def recreate_source_after_unlink():
        nonlocal recreated
        if not recreated and not source.exists() and target.exists():
            recreated = True
            source.write_text("competing", encoding="utf-8")

    with pytest.raises(RuntimeError, match="source retained for recovery"):
        manager.move_path(
            source,
            target,
            guard=recreate_source_after_unlink,
            expected_source_bytes=b"original",
        )

    recovery_files = list(source.parent.glob(f".{source.name}.*.move-recovery"))
    assert source.read_text(encoding="utf-8") == "competing"
    assert target.read_text(encoding="utf-8") == "original"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "original"


def test_move_path_source_removal_failure_retains_target(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_bytes(b"source")
    target = manager.get_file_path("target")
    error = PermissionError("unlink denied")
    real_rename = manager._rename_exclusive

    def failing_source_rename(source_path, target_path, source_fd, target_fd):
        if source_path == source and target_path.name.endswith(".move-recovery"):
            raise error
        return real_rename(source_path, target_path, source_fd, target_fd)

    monkeypatch.setattr(manager, "_rename_exclusive", failing_source_rename)

    with pytest.raises(RuntimeError, match="target retained for recovery") as raised:
        manager.move_path(source, target)

    assert raised.value.__cause__ is error
    assert source.read_bytes() == b"source"
    assert target.read_bytes() == b"source"


def test_move_path_copies_without_clobbering_across_filesystems(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("source", encoding="utf-8")
    target = manager.get_file_path("target")
    real_link = manager._link_entries

    def cross_device_link(source_path, target_path, source_fd, target_fd):
        if source_path == source and target_path == target:
            raise OSError(EXDEV, "cross-device link")
        return real_link(source_path, target_path, source_fd, target_fd)

    monkeypatch.setattr(manager, "_link_entries", cross_device_link)

    assert manager.move_path(source, target) == target
    assert target.read_text(encoding="utf-8") == "source"
    assert not source.exists()


def test_move_path_uses_fsynced_copy_when_hard_links_are_unsupported(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("source", encoding="utf-8")
    source.chmod(0o640)
    target = manager.get_file_path("target")
    real_link = manager._link_entries

    def unsupported_link(source_path, target_path, *args):
        if source_path == source and target_path == target:
            raise OSError(ENOTSUP, "hard links unsupported")
        return real_link(source_path, target_path, *args)

    monkeypatch.setattr(manager, "_link_entries", unsupported_link)

    assert manager.move_path(source, target) == target
    assert target.read_text(encoding="utf-8") == "source"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert not source.exists()


def test_copy_fallback_detects_source_edit_after_copy(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("before", encoding="utf-8")
    target = manager.get_file_path("target")
    real_link = manager._link_entries
    edited = False

    def unsupported_link(source_path, target_path, *args):
        if source_path == source and target_path == target:
            raise OSError(ENOTSUP, "hard links unsupported")
        return real_link(source_path, target_path, *args)

    def edit_after_copy():
        nonlocal edited
        if target.exists() and not edited:
            edited = True
            source.write_text("concurrent", encoding="utf-8")

    monkeypatch.setattr(manager, "_link_entries", unsupported_link)

    with pytest.raises(RuntimeError, match="target retained for recovery"):
        manager.move_path(source, target, guard=edit_after_copy)

    assert source.read_text(encoding="utf-8") == "concurrent"
    assert target.read_text(encoding="utf-8") == "before"


def test_cross_filesystem_copy_does_not_follow_replaced_source(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    hidden_source = tmp_path / "hidden-stored.md"
    source.write_text("source", encoding="utf-8")
    target = manager.get_file_path("target")
    real_link = manager._link_entries

    def replace_source_then_report_cross_device(source_path, target_path, *args):
        if source_path == source and target_path == target:
            source.rename(hidden_source)
            source.symlink_to(hidden_source)
            raise OSError(EXDEV, "cross-device link")
        real_link(source_path, target_path, *args)

    monkeypatch.setattr(
        manager, "_link_entries", replace_source_then_report_cross_device
    )

    with pytest.raises(OSError, match="Too many levels of symbolic links"):
        manager.move_path(source, target)

    assert source.is_symlink()
    assert hidden_source.read_text(encoding="utf-8") == "source"
    assert not target.exists()
    assert list(source.parent.glob(f".{source.name}.*.move-recovery")) == []


def test_cross_filesystem_copy_race_does_not_delete_competing_target(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("source", encoding="utf-8")
    target = manager.get_file_path("target")
    real_link = manager._link_entries
    real_rename = manager._rename_exclusive

    def cross_device_link(source_path, target_path, *args):
        if source_path == source and target_path == target:
            raise OSError(EXDEV, "cross-device link")
        return real_link(source_path, target_path, *args)

    def compete_with_copy(source_path, target_path, *args):
        if source_path.name.endswith(".copy") and target_path == target:
            target.write_text("competing", encoding="utf-8")
        return real_rename(source_path, target_path, *args)

    monkeypatch.setattr(manager, "_link_entries", cross_device_link)
    monkeypatch.setattr(manager, "_rename_exclusive", compete_with_copy)

    with pytest.raises(FileExistsError):
        manager.move_path(source, target)

    assert source.read_text(encoding="utf-8") == "source"
    assert target.read_text(encoding="utf-8") == "competing"


def test_cross_filesystem_interrupt_after_target_claim_retains_target(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("source", encoding="utf-8")
    target = manager.get_file_path("target")
    real_link = manager._link_entries
    real_rename = manager._rename_exclusive

    def cross_device_link(source_path, target_path, *args):
        if source_path == source and target_path == target:
            raise OSError(EXDEV, "cross-device link")
        return real_link(source_path, target_path, *args)

    def interrupting_copy(source_path, target_path, *args):
        real_rename(source_path, target_path, *args)
        if source_path.name.endswith(".copy") and target_path == target:
            raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_link_entries", cross_device_link)
    monkeypatch.setattr(manager, "_rename_exclusive", interrupting_copy)

    with pytest.raises(RuntimeError, match="target retained for recovery"):
        manager.move_path(source, target)

    assert source.read_text(encoding="utf-8") == "source"
    assert target.read_text(encoding="utf-8") == "source"
    assert list(target.parent.glob(f".{target.name}.*.copy")) == []


def test_cross_filesystem_cleanup_preserves_replacement_target(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("source", encoding="utf-8")
    target = manager.get_file_path("target")
    real_link = manager._link_entries
    real_rename = manager._rename_exclusive

    def cross_device_link(source_path, target_path, *args):
        if source_path == source and target_path == target:
            raise OSError(EXDEV, "cross-device link")
        return real_link(source_path, target_path, *args)

    def replace_then_interrupt(source_path, target_path, *args):
        real_rename(source_path, target_path, *args)
        if source_path.name.endswith(".copy") and target_path == target:
            target.unlink()
            target.write_text("competing", encoding="utf-8")
            raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_link_entries", cross_device_link)
    monkeypatch.setattr(manager, "_rename_exclusive", replace_then_interrupt)

    with pytest.raises(KeyboardInterrupt):
        manager.move_path(source, target)

    assert source.read_text(encoding="utf-8") == "source"
    assert target.read_text(encoding="utf-8") == "competing"
    assert list(target.parent.glob(f".{target.name}.*.copy")) == []


def test_cross_filesystem_move_restores_edit_made_immediately_before_unlink(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references")
    source = tmp_path / "stored.md"
    source.write_text("source", encoding="utf-8")
    target = manager.get_file_path("target")
    real_link = manager._link_entries
    real_rename = manager._rename_exclusive

    def cross_device_link(source_path, target_path, *args):
        if source_path == source and target_path == target:
            raise OSError(EXDEV, "cross-device link")
        return real_link(source_path, target_path, *args)

    def edit_then_rename(source_path, target_path, *args):
        if source_path == source and target_path.name.endswith(".move-recovery"):
            source.write_text("concurrent edit", encoding="utf-8")
        return real_rename(source_path, target_path, *args)

    monkeypatch.setattr(manager, "_link_entries", cross_device_link)
    monkeypatch.setattr(manager, "_rename_exclusive", edit_then_rename)

    with pytest.raises(RuntimeError, match="target retained for recovery"):
        manager.move_path(source, target, expected_source_bytes=b"source")

    assert source.read_text(encoding="utf-8") == "concurrent edit"
    assert target.read_text(encoding="utf-8") == "source"
    assert list(source.parent.glob(f".{source.name}.*.move-recovery")) == []


def test_ensure_parent_directory_is_limited_to_output_root(tmp_path):
    manager = FileManager(tmp_path / "references", create=False)
    manager.ensure_directories()

    nested = manager.base_dir / "removed" / "paper.md"
    manager.ensure_parent_directory(nested)

    assert nested.parent.is_dir()
    with pytest.raises(ValueError, match="outside the output root"):
        manager.ensure_parent_directory(tmp_path / "elsewhere" / "paper.md")


def test_move_to_removed_moves_file(tmp_path):
    manager = FileManager(tmp_path / "references")
    source = manager.write_markdown("paper", "content")

    moved = manager.handle_removed_item("paper")

    assert manager.removed_dir is not None
    assert moved == manager.removed_dir / "paper.md"
    assert moved.read_text(encoding="utf-8") == "content"
    assert not source.exists()


def test_move_to_removed_collision_raises_without_renaming_or_overwriting(tmp_path):
    manager = FileManager(tmp_path / "references")
    source = manager.write_markdown("paper", "current")
    assert manager.removed_dir is not None
    existing = manager.removed_dir / "paper.md"
    existing.write_bytes(b"older")

    with pytest.raises(FileExistsError):
        manager.move_to_removed("paper")

    assert source.read_bytes() == b"current"
    assert existing.read_bytes() == b"older"
    assert list(manager.removed_dir.glob("paper*.md")) == [existing]


def test_move_to_removed_missing_source_raises(tmp_path):
    manager = FileManager(tmp_path / "references")

    with pytest.raises(FileNotFoundError):
        manager.move_to_removed("missing")


def test_move_to_removed_filesystem_failure_raises(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = manager.write_markdown("paper", "content")
    assert manager.removed_dir is not None
    target = manager.removed_dir / source.name
    error = PermissionError("move denied")
    real_link = manager._link_entries

    def failing_link(source_path, target_path, *args):
        if target_path == target:
            raise error
        return real_link(source_path, target_path, *args)

    monkeypatch.setattr(manager, "_link_entries", failing_link)

    with pytest.raises(PermissionError) as raised:
        manager.move_to_removed("paper")

    assert raised.value is error
    assert source.read_text(encoding="utf-8") == "content"


def test_case_only_rollback_does_not_move_competing_temporary(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references")
    source = manager.write_markdown("Paper", "original")
    target = manager.get_file_path("paper")
    original_move = manager.move_path
    calls = 0
    competing_temporary = None

    def replace_before_second_move(source_path, target_path, **kwargs):
        nonlocal calls, competing_temporary
        calls += 1
        if calls == 2:
            competing_temporary = Path(source_path)
            editor_file = competing_temporary.with_suffix(".editor")
            editor_file.write_text("competing", encoding="utf-8")
            os.replace(editor_file, competing_temporary)
            raise PermissionError("rename denied")
        return original_move(source_path, target_path, **kwargs)

    monkeypatch.setattr(manager, "move_path", replace_before_second_move)

    with pytest.raises(RuntimeError, match="Managed file changed"):
        manager.rename_path(source, target, expected_source_bytes=b"original")

    assert competing_temporary is not None
    assert competing_temporary.read_text(encoding="utf-8") == "competing"
    assert not source.exists()


def test_delete_behavior_removes_files(tmp_path):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    direct_path = manager.write_markdown("direct", "direct")
    handled_path = manager.write_markdown("handled", "handled")

    assert manager.delete_file("direct") is True
    assert not direct_path.exists()
    assert manager.handle_removed_item("handled") is None
    assert not handled_path.exists()


def test_delete_receipt_restores_original_mode_after_state_failure(tmp_path):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    target = manager.write_markdown("paper", "content")
    target.chmod(0o640)
    operation = PathOperation()

    manager.delete_path(target, operation=operation)
    manager.write_path(
        target,
        "content",
        overwrite=False,
        mode=operation.source_mode,
    )

    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_delete_fsyncs_recovery_inode_before_unlink(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    target = manager.write_markdown("paper", "content")
    fsynced_regular_file = False
    real_fsync = os.fsync

    def tracking_fsync(file_descriptor):
        nonlocal fsynced_regular_file
        if stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            fsynced_regular_file = True
        real_fsync(file_descriptor)

    monkeypatch.setattr(file_manager_module.os, "fsync", tracking_fsync)

    manager.delete_path(target, expected_source_bytes=b"content")

    assert fsynced_regular_file is True


def test_delete_path_uses_actual_stored_path(tmp_path):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    stored_path = tmp_path / "stored-actual-name.md"
    stored_path.write_text("content", encoding="utf-8")

    assert manager.delete_path(stored_path) is True
    assert not stored_path.exists()


def test_delete_and_handle_removed_raise_for_missing_files(tmp_path):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")

    with pytest.raises(FileNotFoundError):
        manager.delete_file("missing")
    with pytest.raises(FileNotFoundError):
        manager.handle_removed_item("missing")


def test_delete_failure_raises_and_leaves_file(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    file_path = manager.write_markdown("paper", "content")
    error = PermissionError("delete denied")
    real_rename = manager._rename_exclusive

    def failing_rename(source, target, *args):
        if source == file_path and target.name.endswith(".delete-recovery"):
            raise error
        return real_rename(source, target, *args)

    monkeypatch.setattr(manager, "_rename_exclusive", failing_rename)

    with pytest.raises(PermissionError) as raised:
        manager.delete_file("paper")

    assert raised.value is error
    assert file_path.read_text(encoding="utf-8") == "content"


def test_delete_retains_recovery_when_competitor_blocks_rollback(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    target = manager.write_markdown("paper", "original")
    original_rename = manager._rename_exclusive

    def delete_then_compete(source, destination, *args):
        original_rename(source, destination, *args)
        if source == target and destination.name.endswith(".delete-recovery"):
            target.write_text("competing", encoding="utf-8")
            raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_rename_exclusive", delete_then_compete)

    with pytest.raises(RuntimeError, match="original retained at recovery path"):
        manager.delete_path(target)

    recovery_files = list(target.parent.glob(f".{target.name}.*.delete-recovery"))
    assert target.read_text(encoding="utf-8") == "competing"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "original"


def test_delete_restores_in_place_edit_made_immediately_before_unlink(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    target = manager.write_markdown("paper", "original")
    original_rename = manager._rename_exclusive

    def edit_then_rename(source, destination, *args):
        if source == target and destination.name.endswith(".delete-recovery"):
            target.write_text("concurrent edit", encoding="utf-8")
        original_rename(source, destination, *args)

    monkeypatch.setattr(manager, "_rename_exclusive", edit_then_rename)

    with pytest.raises(RuntimeError, match="Managed file changed"):
        manager.delete_path(target, expected_source_bytes=b"original")

    assert target.read_text(encoding="utf-8") == "concurrent edit"
    assert list(target.parent.glob(f".{target.name}.*.delete-recovery")) == []


def test_delete_preserves_atomic_save_made_immediately_before_rename(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    target = manager.write_markdown("paper", "original")
    original_rename = manager._rename_exclusive

    def save_then_rename(source, destination, *args):
        if source == target and destination.name.endswith(".delete-recovery"):
            editor_file = target.with_suffix(".editor")
            editor_file.write_text("concurrent save", encoding="utf-8")
            os.replace(editor_file, target)
        original_rename(source, destination, *args)

    monkeypatch.setattr(manager, "_rename_exclusive", save_then_rename)

    with pytest.raises(RuntimeError, match="Managed file changed"):
        manager.delete_path(target, expected_source_bytes=b"original")

    assert target.read_text(encoding="utf-8") == "concurrent save"
    assert list(target.parent.glob(f".{target.name}.*.delete-recovery")) == []


def test_delete_does_not_restore_file_deleted_immediately_before_rename(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    target = manager.write_markdown("paper", "original")
    original_rename = manager._rename_exclusive

    def delete_then_rename(source, destination, *args):
        if source == target and destination.name.endswith(".delete-recovery"):
            target.unlink()
        original_rename(source, destination, *args)

    monkeypatch.setattr(manager, "_rename_exclusive", delete_then_rename)

    with pytest.raises(FileNotFoundError):
        manager.delete_path(target, expected_source_bytes=b"original")

    assert not target.exists()
    assert list(target.parent.glob(f".{target.name}.*.delete-recovery")) == []


def test_delete_restores_file_when_completed_quarantine_disappears(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    target = manager.write_markdown("paper", "original")
    target.chmod(0o640)
    original_capture = manager._capture_temporary
    removed = False

    def remove_before_capture(path, parent_fd):
        nonlocal removed
        if not removed and path.name.endswith(".delete-recovery"):
            removed = True
            path.unlink()
            return None
        return original_capture(path, parent_fd)

    monkeypatch.setattr(manager, "_capture_temporary", remove_before_capture)

    with pytest.raises(RuntimeError, match="Deleted file disappeared"):
        manager.delete_path(target, expected_source_bytes=b"original")

    assert target.read_text(encoding="utf-8") == "original"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_delete_recreates_durable_recovery_when_original_recovery_disappears(
    tmp_path, monkeypatch
):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    target = manager.write_markdown("paper", "original")
    target.chmod(0o640)
    original_remove = manager._remove_owned_entry

    def remove_recovery_then_compete(path, identity, parent_fd):
        removed = original_remove(path, identity, parent_fd)
        if path is not None and path.name.endswith(".delete-recovery"):
            target.write_text("competing", encoding="utf-8")
            raise KeyboardInterrupt
        return removed

    monkeypatch.setattr(manager, "_remove_owned_entry", remove_recovery_then_compete)

    with pytest.raises(RuntimeError, match="original retained at recovery path"):
        manager.delete_path(target)

    recovery_files = list(target.parent.glob(f".{target.name}.*.delete-recovery"))
    assert target.read_text(encoding="utf-8") == "competing"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "original"
    assert stat.S_IMODE(recovery_files[0].stat().st_mode) == 0o640


def test_delete_keeps_recovery_copy_when_directory_fsync_fails(tmp_path, monkeypatch):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")
    target = manager.write_markdown("paper", "original")
    target.chmod(0o640)
    original_remove = manager._remove_owned_entry
    original_fsync = os.fsync
    recovery_removed = False

    def remove_recovery_then_compete(path, identity, parent_fd):
        nonlocal recovery_removed
        removed = original_remove(path, identity, parent_fd)
        if path is not None and path.name.endswith(".delete-recovery"):
            recovery_removed = True
            target.write_text("competing", encoding="utf-8")
            raise KeyboardInterrupt
        return removed

    def fail_recovery_directory_fsync(descriptor):
        if (
            recovery_removed
            and stat.S_ISDIR(os.fstat(descriptor).st_mode)
            and list(target.parent.glob(f".{target.name}.*.delete-recovery"))
        ):
            raise OSError("directory fsync failed")
        original_fsync(descriptor)

    monkeypatch.setattr(manager, "_remove_owned_entry", remove_recovery_then_compete)
    monkeypatch.setattr(file_manager_module.os, "fsync", fail_recovery_directory_fsync)

    with pytest.raises(
        RuntimeError,
        match="Recovery file retained.*durability could not be confirmed",
    ):
        manager.delete_path(target)

    recovery_files = list(target.parent.glob(f".{target.name}.*.delete-recovery"))
    assert target.read_text(encoding="utf-8") == "competing"
    assert len(recovery_files) == 1
    assert recovery_files[0].read_text(encoding="utf-8") == "original"
    assert stat.S_IMODE(recovery_files[0].stat().st_mode) == 0o640


def test_output_replacement_during_delete_unlink_preserves_both_roots(
    tmp_path, monkeypatch
):
    output = tmp_path / "references"
    hidden_output = tmp_path / "hidden-references"
    manager = FileManager(output, deletion_behavior="delete")
    target = manager.write_markdown("paper", "original")
    output_identity = manager.path_identity(output)
    real_rename = manager._rename_exclusive
    replaced = False

    def guard():
        if manager.path_identity(output) != output_identity:
            raise RuntimeError("output directory changed")

    def replace_root_during_rename(source, destination, source_fd, target_fd):
        nonlocal replaced
        if (
            not replaced
            and source == target
            and destination.name.endswith(".delete-recovery")
        ):
            replaced = True
            output.rename(hidden_output)
            output.mkdir()
            (output / target.name).write_text("competing", encoding="utf-8")
        return real_rename(source, destination, source_fd, target_fd)

    monkeypatch.setattr(manager, "_rename_exclusive", replace_root_during_rename)

    with pytest.raises(RuntimeError, match="output directory changed"):
        manager.delete_path(target, guard=guard)

    assert (hidden_output / target.name).read_text(encoding="utf-8") == "original"
    assert (output / target.name).read_text(encoding="utf-8") == "competing"


def test_lists_only_sorted_markdown_files(tmp_path):
    manager = FileManager(tmp_path / "references")
    zeta_path = manager.write_markdown("zeta", "zeta")
    alpha_path = manager.write_markdown("alpha", "alpha")
    (manager.base_dir / "notes.txt").write_text("not markdown", encoding="utf-8")
    assert manager.removed_dir is not None
    removed_zeta = manager.removed_dir / "z-old.md"
    removed_alpha = manager.removed_dir / "a-old.md"
    removed_zeta.write_text("old", encoding="utf-8")
    removed_alpha.write_text("older", encoding="utf-8")

    assert manager.list_all_files() == [alpha_path, zeta_path]
    assert manager.list_removed_files() == [removed_alpha, removed_zeta]


def test_list_removed_files_is_empty_in_delete_mode(tmp_path):
    manager = FileManager(tmp_path / "references", deletion_behavior="delete")

    assert manager.list_removed_files() == []
