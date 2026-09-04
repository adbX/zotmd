"""Tests for the fresh ZotMD 0.4 SQLite state contract."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from zotmd.core.state_manager import (
    DEFAULT_RENDER_CONTRACT_VERSION,
    IncompatibleStateError,
    ItemState,
    LegacyStateError,
    ReadOnlyStateError,
    StateIdentityError,
    StateManager,
    StateManagerClosedError,
)

LIBRARY_ID = "1234567"
SYNCED_AT = datetime(2026, 1, 2, 3, 4, 5)


def _item(
    zotero_key: str,
    *,
    version: int = 1,
    annotation_count: int = 0,
    item_json: str | None = None,
) -> ItemState:
    return ItemState(
        zotero_key=zotero_key,
        citation_key=f"cite-{zotero_key.lower()}",
        item_type="journalArticle",
        zotero_version=version,
        file_path=f"/actual/notes/{zotero_key}.md",
        last_synced_at=SYNCED_AT,
        sync_status="active",
        item_json=item_json,
        child_signature=f"signature-{zotero_key}",
        annotation_count=annotation_count,
    )


def _manager(tmp_path: Path, **kwargs: object) -> StateManager:
    return StateManager(
        tmp_path / "state" / "sync.sqlite",
        library_id=LIBRARY_ID,
        output_root=tmp_path / "notes",
        **kwargs,
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_fresh_database_creates_parent_and_exact_v4_schema(tmp_path):
    db_path = tmp_path / "nested" / "state" / "sync.sqlite"
    output_root = tmp_path / "notes" / ".." / "references"

    with StateManager(db_path, LIBRARY_ID, output_root) as state:
        assert state.get_identity() == (LIBRARY_ID, output_root.resolve())
        assert state.previous_output_root is None

    assert db_path.is_file()
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (4,)
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_schema
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
        }
        assert tables == {"sync_items", "sync_metadata"}
        assert _table_columns(connection, "sync_items") == {
            "zotero_key",
            "citation_key",
            "item_type",
            "zotero_version",
            "file_path",
            "last_synced_at",
            "sync_status",
            "item_json",
            "child_signature",
            "annotation_count",
            "created_at",
            "updated_at",
        }
        assert _table_columns(connection, "sync_metadata") == {
            "id",
            "library_id",
            "output_root",
            "last_library_version",
            "last_full_sync",
            "last_incremental_sync",
            "template_hash",
            "template_path",
            "template_version_at",
            "render_contract_version",
        }


def test_writable_construction_requires_identity(tmp_path):
    db_path = tmp_path / "missing" / "sync.sqlite"

    with pytest.raises(ValueError, match="library_id and output_root"):
        StateManager(db_path)
    with pytest.raises(ValueError, match="library_id and output_root"):
        StateManager(db_path, library_id=LIBRARY_ID)

    assert not db_path.parent.exists()


def test_existing_empty_database_gets_fresh_schema(tmp_path):
    db_path = tmp_path / "sync.sqlite"
    db_path.touch()

    with StateManager(db_path, LIBRARY_ID, tmp_path / "notes") as state:
        assert state.get_identity() == (LIBRARY_ID, (tmp_path / "notes").resolve())

    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (4,)


def test_empty_public_operations_and_zero_version_checkpoint(tmp_path):
    with _manager(tmp_path) as state:
        assert state.get_last_library_version() is None
        assert state.get_item_state("missing") is None
        assert state.get_active_items() == []
        assert state.get_all_item_keys() == set()
        assert state.get_template_version() is None
        assert state.get_sync_stats() == {
            "active_items": 0,
            "removed_items": 0,
            "total_annotations": 0,
            "last_library_version": None,
            "last_full_sync": None,
            "last_incremental_sync": None,
        }

        state.update_library_version(0)

        assert state.get_last_library_version() == 0
        stats = state.get_sync_stats()
        assert stats["last_library_version"] == 0
        assert datetime.fromisoformat(str(stats["last_incremental_sync"]))


def test_incremental_and_full_sync_checkpoints_use_iso_strings(tmp_path):
    with _manager(tmp_path) as state:
        state.update_library_version(17)

        incremental = state.get_sync_stats()
        assert state.get_last_library_version() == 17
        assert incremental["last_full_sync"] is None
        assert datetime.fromisoformat(str(incremental["last_incremental_sync"]))

        state.record_full_sync(23)

        full = state.get_sync_stats()
        assert state.get_last_library_version() == 23
        assert full["last_library_version"] == 23
        assert full["last_full_sync"] == full["last_incremental_sync"]
        assert datetime.fromisoformat(str(full["last_full_sync"]))


def test_checkpoint_snapshot_restores_every_metadata_field(tmp_path):
    with _manager(tmp_path) as state:
        original = state.get_checkpoint()
        state.record_full_sync(23)
        state.record_template_version("hash", "template", 7)

        assert state.get_checkpoint() != original

        state.restore_checkpoint(original)

        assert state.get_checkpoint() == original
        assert state.get_last_library_version() is None
        assert state.get_template_version() is None


def test_upsert_round_trips_item_state_and_preserves_omitted_json(tmp_path):
    initial_json = '{"key":"ITEM-1","version":0}'
    initial = _item(
        "ITEM-1",
        version=0,
        annotation_count=2,
        item_json=initial_json,
    )

    with _manager(tmp_path) as state:
        state.upsert_item(initial)
        inserted = state.get_item_state("ITEM-1")

        assert inserted is not None
        assert inserted.zotero_key == initial.zotero_key
        assert inserted.citation_key == initial.citation_key
        assert inserted.item_type == initial.item_type
        assert inserted.zotero_version == 0
        assert inserted.file_path == initial.file_path
        assert inserted.last_synced_at == initial.last_synced_at
        assert inserted.sync_status == "active"
        assert inserted.item_json == initial_json
        assert inserted.child_signature == "signature-ITEM-1"
        assert inserted.annotation_count == 2
        assert inserted.created_at is not None
        assert inserted.updated_at is not None

        updated = replace(
            initial,
            citation_key="revised-citation",
            item_type="book",
            zotero_version=2,
            file_path="/actual/renamed/revised.md",
            last_synced_at=datetime(2026, 2, 3, 4, 5, 6),
            item_json=None,
            child_signature="revised-signature",
            annotation_count=4,
        )
        state.upsert_item(updated)
        stored = state.get_item_state("ITEM-1")

        assert stored is not None
        assert stored.citation_key == "revised-citation"
        assert stored.item_type == "book"
        assert stored.zotero_version == 2
        assert stored.file_path == "/actual/renamed/revised.md"
        assert stored.last_synced_at == updated.last_synced_at
        assert stored.item_json == initial_json
        assert stored.child_signature == "revised-signature"
        assert stored.annotation_count == 4
        assert stored.created_at == inserted.created_at
        assert stored.updated_at is not None
        assert inserted.updated_at is not None
        assert stored.updated_at >= inserted.updated_at

        replacement_json = '{"key":"ITEM-1","version":2}'
        state.upsert_item(updated, item_json=replacement_json)
        replaced = state.get_item_state("ITEM-1")
        assert replaced is not None
        assert replaced.item_json == replacement_json


def test_removed_items_are_excluded_from_active_queries_and_stats(tmp_path):
    with _manager(tmp_path) as state:
        state.upsert_item(_item("ITEM-2", annotation_count=7))
        state.upsert_item(_item("ITEM-1", annotation_count=3))
        state.mark_item_removed("ITEM-2")
        state.record_full_sync(41)

        removed = state.get_item_state("ITEM-2")
        assert removed is not None
        assert removed.sync_status == "removed"
        assert [item.zotero_key for item in state.get_active_items()] == ["ITEM-1"]
        assert [item.zotero_key for item in state.get_managed_items()] == [
            "ITEM-1",
            "ITEM-2",
        ]
        assert state.get_all_item_keys() == {"ITEM-1"}

        stats = state.get_sync_stats()

    sync_time = stats["last_full_sync"]
    assert stats == {
        "active_items": 1,
        "removed_items": 1,
        "total_annotations": 3,
        "last_library_version": 41,
        "last_full_sync": sync_time,
        "last_incremental_sync": sync_time,
    }
    assert datetime.fromisoformat(str(sync_time))


def test_template_checkpoint_includes_render_contract_version(tmp_path):
    with _manager(tmp_path) as state:
        state.record_template_version("hash-v1", "built-in")
        first = state.get_template_version()

        assert first is not None
        assert first.template_hash == "hash-v1"
        assert first.template_path == "built-in"
        assert first.render_contract_version == DEFAULT_RENDER_CONTRACT_VERSION
        assert first.recorded_at is not None

        state.record_template_version("hash-v2", "/templates/custom.md.j2", 7)
        second = state.get_template_version()

        assert second is not None
        assert second.template_hash == "hash-v2"
        assert second.template_path == "/templates/custom.md.j2"
        assert second.render_contract_version == 7
        assert second.recorded_at is not None
        assert second.recorded_at >= first.recorded_at


def test_transaction_commits_or_rolls_back_all_mutations(tmp_path):
    with _manager(tmp_path) as state:
        with state.transaction() as transaction_state:
            assert transaction_state is state
            state.upsert_item(_item("COMMITTED"))
            state.update_library_version(9)

        assert state.get_item_state("COMMITTED") is not None
        assert state.get_last_library_version() == 9

        with pytest.raises(RuntimeError, match="stop"):
            with state.transaction():
                state.upsert_item(_item("ROLLED-BACK"))
                state.update_library_version(10)
                raise RuntimeError("stop")

        assert state.get_item_state("ROLLED-BACK") is None
        assert state.get_last_library_version() == 9


def test_outer_transaction_commit_failure_rolls_back_pending_state(tmp_path):
    with _manager(tmp_path) as state:
        assert state.conn is not None
        state.conn.execute("PRAGMA busy_timeout = 0")
        with closing(sqlite3.connect(state.db_path)) as reader:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM sync_metadata").fetchone()

            with pytest.raises(sqlite3.OperationalError, match="locked"):
                with state.transaction():
                    state.upsert_item(_item("UNCOMMITTED"))
                    state.update_library_version(9)

            assert state.conn.in_transaction is False
            assert state.get_item_state("UNCOMMITTED") is None
            assert state.get_last_library_version() is None
            reader.rollback()

        with state.transaction():
            state.upsert_item(_item("COMMITTED"))

        assert state.get_item_state("COMMITTED") is not None


def test_mutator_does_not_commit_an_existing_connection_transaction(tmp_path):
    with _manager(tmp_path) as state:
        assert state.conn is not None
        state.conn.execute("BEGIN")
        state.upsert_item(_item("ROLLED-BACK"))
        state.conn.rollback()

        assert state.get_item_state("ROLLED-BACK") is None


@pytest.mark.parametrize("read_only", [False, True])
def test_legacy_database_is_refused_without_changing_bytes(tmp_path, read_only):
    db_path = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("CREATE TABLE sync_items (zotero_key TEXT PRIMARY KEY)")
    original = db_path.read_bytes()

    kwargs = {"read_only": True} if read_only else {}
    with pytest.raises(LegacyStateError, match=r"Archive .*fresh sync"):
        StateManager(
            db_path,
            library_id=LIBRARY_ID,
            output_root=tmp_path / "notes",
            **kwargs,
        )

    assert db_path.read_bytes() == original


def test_read_only_state_is_byte_stable_and_all_mutators_refuse(tmp_path):
    db_path = tmp_path / "state" / "sync.sqlite"
    output_root = tmp_path / "notes"
    with StateManager(db_path, LIBRARY_ID, output_root) as writable:
        writable.upsert_item(_item("ITEM-1", annotation_count=2))
        writable.update_library_version(0)
    original = db_path.read_bytes()

    with StateManager(db_path, read_only=True) as state:
        assert state.get_identity() == (LIBRARY_ID, output_root.resolve())
        assert state.get_last_library_version() == 0
        assert state.get_sync_stats()["total_annotations"] == 2

        mutators = [
            lambda: state.update_output_root(tmp_path / "other"),
            lambda: state.update_library_version(2),
            lambda: state.record_full_sync(2),
            lambda: state.upsert_item(_item("ITEM-2")),
            lambda: state.mark_item_removed("ITEM-1"),
            lambda: state.record_template_version("hash", "built-in"),
        ]
        for mutate in mutators:
            with pytest.raises(ReadOnlyStateError, match="read-only"):
                mutate()

        with pytest.raises(ReadOnlyStateError, match="read-only"):
            with state.transaction():
                pass

        assert db_path.read_bytes() == original

    assert db_path.read_bytes() == original


def test_same_library_new_output_records_previous_root_until_update(tmp_path):
    db_path = tmp_path / "state.sqlite"
    old_output = (tmp_path / "old-notes").resolve()
    new_output = (tmp_path / "new-notes").resolve()
    with StateManager(db_path, LIBRARY_ID, old_output):
        pass

    with StateManager(db_path, LIBRARY_ID, new_output) as state:
        assert state.previous_output_root == old_output
        assert state.get_identity() == (LIBRARY_ID, old_output)

        state.update_output_root()

        assert state.get_identity() == (LIBRARY_ID, new_output)
        assert state.previous_output_root is None


def test_new_library_is_refused_for_same_output_without_changes(tmp_path):
    db_path = tmp_path / "state.sqlite"
    output_root = tmp_path / "notes"
    with StateManager(db_path, LIBRARY_ID, output_root):
        pass
    original = db_path.read_bytes()

    with pytest.raises(StateIdentityError, match="same output root"):
        StateManager(db_path, "7654321", output_root)

    assert db_path.read_bytes() == original


def test_new_library_and_distinct_empty_output_archives_v4_state(tmp_path):
    db_path = tmp_path / "state.sqlite"
    old_output = tmp_path / "old-notes"
    new_output = tmp_path / "empty-new-notes"
    new_output.mkdir()
    with StateManager(db_path, LIBRARY_ID, old_output) as old_state:
        old_state.upsert_item(_item("OLD-ITEM"))
    old_bytes = db_path.read_bytes()

    first_archive_name = tmp_path / "state.0.4-archive.sqlite"
    first_archive_name.write_bytes(b"existing archive")

    with StateManager(db_path, "7654321", new_output) as fresh_state:
        assert fresh_state.get_identity() == ("7654321", new_output.resolve())
        assert fresh_state.get_active_items() == []
        assert fresh_state.previous_output_root is None

    assert first_archive_name.read_bytes() == b"existing archive"
    archived = tmp_path / "state.0.4-archive-2.sqlite"
    assert archived.read_bytes() == old_bytes
    assert db_path.read_bytes() != old_bytes


def test_new_library_and_nonempty_distinct_output_is_refused(tmp_path):
    db_path = tmp_path / "state.sqlite"
    with StateManager(db_path, LIBRARY_ID, tmp_path / "old-notes"):
        pass
    original = db_path.read_bytes()
    new_output = tmp_path / "new-notes"
    new_output.mkdir()
    (new_output / "unmanaged.md").write_text("keep me", encoding="utf-8")

    with pytest.raises(StateIdentityError, match="not empty"):
        StateManager(db_path, "7654321", new_output)

    assert db_path.read_bytes() == original
    assert (new_output / "unmanaged.md").read_text(encoding="utf-8") == "keep me"


def test_incompatible_v4_shape_is_not_migrated(tmp_path):
    db_path = tmp_path / "invalid-v4.sqlite"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("CREATE TABLE unexpected (value TEXT)")
        connection.execute("PRAGMA user_version = 4")
    original = db_path.read_bytes()

    with pytest.raises(IncompatibleStateError, match="expected tables"):
        StateManager(db_path, LIBRARY_ID, tmp_path / "notes")

    assert db_path.read_bytes() == original


def test_methods_fail_clearly_after_close(tmp_path):
    state = _manager(tmp_path)
    state.close()

    with pytest.raises(StateManagerClosedError, match="closed"):
        state.get_identity()
    with pytest.raises(StateManagerClosedError, match="closed"):
        state.update_library_version(1)
    with pytest.raises(StateManagerClosedError, match="closed"):
        with state.transaction():
            pass

    state.close()
