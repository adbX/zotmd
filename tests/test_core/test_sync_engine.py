"""Contract tests for safe synchronization reconciliation."""

import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from pyzotero import HTTPError, TooManyRetriesError, UserNotAuthorisedError

from zotmd.core.state_manager import StateManager
from zotmd.core.sync_engine import SyncEngine
from zotmd.file_ops.file_manager import FileManager
from zotmd.models.item import VENUE_FIELDS
from zotmd.templates.renderer import RENDER_CONTRACT_VERSION, TemplateRenderer

LIBRARY_ID = "1234567"


class FakeZotero:
    """Serial, mutable Zotero API double used across sync intervals."""

    def __init__(
        self,
        *,
        version: int,
        items: list[dict] | None = None,
        annotations: list[dict] | None = None,
        attachments: list[dict] | None = None,
    ) -> None:
        self.version = version
        self.items = items or []
        self.modified_items = list(self.items)
        self.annotations = annotations or []
        self.attachments = attachments or []
        self.deleted: dict[str, list[str]] = {"items": []}
        self.calls: list[str] = []
        self.version_responses: list[int] = []
        self.item_responses: list[list[dict]] = []
        self.modified_item_responses: list[list[dict]] = []
        self.annotation_responses: list[list[dict]] = []
        self.attachment_responses: list[list[dict]] = []
        self.deleted_responses: list[dict[str, list[str]]] = []

    def get_library_version(self) -> int:
        self.calls.append("version")
        if self.version_responses:
            return self.version_responses.pop(0)
        return self.version

    def get_all_items(self) -> list[dict]:
        self.calls.append("items")
        if self.item_responses:
            return self.item_responses.pop(0)
        return self.items

    def get_items_since_version(self, version: int) -> list[dict]:
        self.calls.append(f"modified:{version}")
        if self.modified_item_responses:
            return self.modified_item_responses.pop(0)
        return self.modified_items

    def get_all_annotations(self) -> list[dict]:
        self.calls.append("annotations")
        if self.annotation_responses:
            return self.annotation_responses.pop(0)
        return self.annotations

    def get_all_attachments(self) -> list[dict]:
        self.calls.append("attachments")
        if self.attachment_responses:
            return self.attachment_responses.pop(0)
        return self.attachments

    def get_deleted_items(self, version: int) -> dict[str, list[str]]:
        self.calls.append(f"deleted:{version}")
        if self.deleted_responses:
            return self.deleted_responses.pop(0)
        return self.deleted


def _item(
    key: str,
    citation_key: str | None,
    *,
    version: int = 1,
    title: str | None = None,
) -> dict:
    extra = f"Citation Key: {citation_key}" if citation_key is not None else ""
    return {
        "key": key,
        "version": version,
        "data": {
            "key": key,
            "itemType": "journalArticle",
            "title": title or f"Title {key}",
            "extra": extra,
            "creators": [],
            "tags": [],
        },
    }


def _attachment(
    key: str,
    parent_key: str,
    *,
    version: int = 1,
    content_type: str = "application/pdf",
) -> dict:
    return {
        "key": key,
        "version": version,
        "data": {
            "key": key,
            "itemType": "attachment",
            "parentItem": parent_key,
            "contentType": content_type,
            "linkMode": "imported_file",
        },
    }


def _trashed(item: dict) -> dict:
    trashed = json.loads(json.dumps(item))
    trashed["data"]["deleted"] = 1
    return trashed


def _annotation(
    key: str,
    attachment_key: str,
    text: str,
    *,
    version: int = 1,
) -> dict:
    return {
        "key": key,
        "version": version,
        "data": {
            "key": key,
            "itemType": "annotation",
            "parentItem": attachment_key,
            "annotationType": "highlight",
            "annotationText": text,
            "annotationPageLabel": "1",
            "annotationPosition": '{"pageIndex":0}',
            "annotationSortIndex": key,
        },
    }


def _engine(
    zotero: FakeZotero,
    state: StateManager | None,
    output: Path,
    *,
    dry_run: bool = False,
    deletion_behavior: str = "move",
) -> SyncEngine:
    return SyncEngine(
        zotero_client=zotero,
        state_manager=state,
        renderer=TemplateRenderer(),
        file_manager=FileManager(
            output,
            deletion_behavior=deletion_behavior,
            create=False,
            read_only=dry_run,
        ),
        library_id=LIBRARY_ID,
        dry_run=dry_run,
    )


def _tree_snapshot(root: Path):
    return [
        (
            path.relative_to(root),
            path.is_dir(),
            path.read_bytes() if path.is_file() else None,
        )
        for path in sorted(root.rglob("*"))
    ]


def test_full_sync_records_child_contract_and_each_attachment_identity(tmp_path):
    item = _item("ITEM-1", "paper")
    attachments = [
        _attachment("PDF-1", "ITEM-1", version=4),
        _attachment("PDF-2", "ITEM-1", version=5),
    ]
    annotations = [
        _annotation("ANN-2", "PDF-2", "Second PDF", version=8),
        _annotation("ANN-1", "PDF-1", "First PDF", version=7),
    ]
    zotero = FakeZotero(
        version=11,
        items=[item],
        annotations=annotations,
        attachments=attachments,
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        result = _engine(zotero, state, output).full_sync(show_progress=False)
        stored = state.get_item_state("ITEM-1")
        template = state.get_template_version()

        assert result.errors == []
        assert result.total_items_processed == 1
        assert result.items_created == 1
        assert result.annotations_synced == 2
        assert zotero.calls == [
            "version",
            "items",
            "annotations",
            "attachments",
            "version",
        ]
        assert stored is not None
        assert json.loads(stored.item_json or "") == item
        assert stored.child_signature.startswith("v1:")
        assert stored.annotation_count == 2
        assert stored.file_path == str(output / "paper.md")
        assert state.get_last_library_version() == 11
        assert template is not None
        assert template.render_contract_version == RENDER_CONTRACT_VERSION

    markdown = (output / "paper.md").read_text(encoding="utf-8")
    assert "library/items/PDF-1?page=0&annotation=ANN-1" in markdown
    assert "library/items/PDF-2?page=0&annotation=ANN-2" in markdown


def test_full_sync_retries_mixed_snapshot_before_removal_or_checkpoint(tmp_path):
    first_item = _item("ITEM-1", "first")
    second_item = _item("ITEM-2", "second")
    attachment = _attachment("PDF-1", "ITEM-1")
    zotero = FakeZotero(
        version=1,
        items=[first_item, second_item],
        annotations=[_annotation("ANN-1", "PDF-1", "Original")],
        attachments=[attachment],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        second_note = output / "second.md"
        original_second = second_note.read_bytes()

        zotero.version = 3
        zotero.version_responses = [2, 3, 3, 3]
        zotero.item_responses = [[first_item], [first_item, second_item]]
        zotero.annotation_responses = [
            [_annotation("ANN-1", "PDF-1", "Rejected", version=2)],
            [_annotation("ANN-1", "PDF-1", "Accepted", version=3)],
        ]
        zotero.attachment_responses = [[attachment], [attachment]]

        result = engine.full_sync(show_progress=False)

        assert result.errors == []
        assert result.items_removed == 0
        assert state.get_last_library_version() == 3
        assert state.get_item_state("ITEM-2").sync_status == "active"  # type: ignore[union-attr]
        assert second_note.read_bytes() == original_second
        assert "Accepted" in (output / "first.md").read_text(encoding="utf-8")
        assert "Rejected" not in (output / "first.md").read_text(encoding="utf-8")


def test_full_sync_aborts_when_no_stable_snapshot_can_be_read(tmp_path):
    zotero = FakeZotero(version=4, items=[_item("ITEM-1", "paper")])
    zotero.version_responses = [1, 2, 2, 3, 3, 4]
    zotero.item_responses = [zotero.items, zotero.items, zotero.items]
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        with pytest.raises(RuntimeError, match="stable Zotero library snapshot"):
            _engine(zotero, state, output).full_sync(show_progress=False)

        assert state.get_active_items() == []
        assert state.get_last_library_version() is None

    assert not output.exists()


def test_recursive_custom_template_change_rerenders_unchanged_library(tmp_path):
    output = tmp_path / "references"
    template = tmp_path / "body.md.j2"
    partial = tmp_path / "partial.md.j2"
    template.write_text('{% include "partial.md.j2" %}\n', encoding="utf-8")
    partial.write_text(
        "# {{ title }}\n\nVersion one\n\n"
        "## Notes\n<!-- zotmd:notes:start -->\n{{ preserved_notes }}\n"
        "<!-- zotmd:notes:end -->\n",
        encoding="utf-8",
    )
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        first = SyncEngine(
            zotero,
            state,
            TemplateRenderer(template),
            FileManager(output, create=False),
            LIBRARY_ID,
        )
        first.full_sync(show_progress=False)
        partial.write_text(
            "# {{ title }}\n\nVersion two\n\n"
            "## Notes\n<!-- zotmd:notes:start -->\n{{ preserved_notes }}\n"
            "<!-- zotmd:notes:end -->\n",
            encoding="utf-8",
        )
        zotero.calls.clear()
        second = SyncEngine(
            zotero,
            state,
            TemplateRenderer(template),
            FileManager(output, create=False),
            LIBRARY_ID,
        )

        result = second.incremental_sync(show_progress=False)

        assert result.errors == []
        assert result.items_updated == 1
        assert zotero.calls == [
            "version",
            "annotations",
            "attachments",
            "version",
        ]

    assert "Version two" in (output / "paper.md").read_text(encoding="utf-8")


def test_template_only_commit_failure_restores_file_and_item_timestamp(
    tmp_path, monkeypatch
):
    output = tmp_path / "references"
    template = tmp_path / "body.md.j2"
    partial = tmp_path / "partial.md.j2"
    template.write_text('{% include "partial.md.j2" %}\n', encoding="utf-8")
    partial.write_text(
        "# {{ title }}\n\nVersion one\n\n"
        "## Notes\n<!-- zotmd:notes:start -->\n{{ preserved_notes }}\n"
        "<!-- zotmd:notes:end -->\n",
        encoding="utf-8",
    )
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        first = SyncEngine(
            zotero,
            state,
            TemplateRenderer(template),
            FileManager(output, create=False),
            LIBRARY_ID,
        )
        first.full_sync(show_progress=False)
        original_file = (output / "paper.md").read_bytes()
        original_state = state.get_item_state("ITEM-1")
        original_template = state.get_template_version()
        partial.write_text(
            "# {{ title }}\n\nVersion two\n\n"
            "## Notes\n<!-- zotmd:notes:start -->\n{{ preserved_notes }}\n"
            "<!-- zotmd:notes:end -->\n",
            encoding="utf-8",
        )
        second = SyncEngine(
            zotero,
            state,
            TemplateRenderer(template),
            FileManager(output, create=False),
            LIBRARY_ID,
        )
        original_upsert = state.upsert_item

        def upsert_then_fail(item_state, item_json=None):
            original_upsert(item_state, item_json=item_json)
            raise RuntimeError("item state commit failed")

        monkeypatch.setattr(state, "upsert_item", upsert_then_fail)

        result = second.incremental_sync(show_progress=False)

        assert result.errors == ["Error syncing item ITEM-1: item state commit failed"]
        assert (output / "paper.md").read_bytes() == original_file
        assert state.get_item_state("ITEM-1") == original_state
        assert state.get_template_version() == original_template


def test_item_rollback_does_not_overwrite_edit_after_ownership_check(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        target = output / "paper.md"
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "paper", version=2, title="Revised")]
        original_write = engine.files.write_path
        write_count = 0

        def edit_before_rollback_write(*args, **kwargs):
            nonlocal write_count
            write_count += 1
            if write_count == 2:
                target.write_bytes(b"concurrent rollback edit")
            return original_write(*args, **kwargs)

        def fail_upsert(*args, **kwargs):
            raise RuntimeError("item state write failed")

        monkeypatch.setattr(engine.files, "write_path", edit_before_rollback_write)
        monkeypatch.setattr(state, "upsert_item", fail_upsert)
        result = engine.incremental_sync(show_progress=False)

        assert len(result.errors) == 1
        assert "file rollback failed" in result.errors[0]
        assert target.read_bytes() == b"concurrent rollback edit"
        assert state.get_last_library_version() == 1


def test_new_item_state_insert_failure_retains_generated_note_for_recovery(
    tmp_path, monkeypatch
):
    output = tmp_path / "references"
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)

        def fail_upsert(*args, **kwargs):
            raise RuntimeError("item state insert failed")

        monkeypatch.setattr(state, "upsert_item", fail_upsert)
        result = engine.full_sync(show_progress=False)

        assert len(result.errors) == 1
        assert "retained for recovery" in result.errors[0]
        assert state.get_item_state("ITEM-1") is None
        assert state.get_last_library_version() is None

    assert (output / "paper.md").is_file()


def test_new_item_state_insert_failure_preserves_concurrent_in_place_edit(
    tmp_path, monkeypatch
):
    output = tmp_path / "references"
    target = output / "paper.md"
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)

        def edit_then_fail(*args, **kwargs):
            identity = engine.files.path_identity(target)
            target.write_bytes(b"concurrent user content")
            assert engine.files.path_identity(target) == identity
            raise RuntimeError("item state insert failed")

        monkeypatch.setattr(state, "upsert_item", edit_then_fail)
        result = engine.full_sync(show_progress=False)

        assert len(result.errors) == 1
        assert "retained for recovery" in result.errors[0]
        assert str(target) in result.errors[0]
        assert state.get_item_state("ITEM-1") is None
        assert state.get_last_library_version() is None

    assert target.read_bytes() == b"concurrent user content"


def test_incremental_detects_same_count_child_only_edit(tmp_path):
    item = _item("ITEM-1", "paper")
    attachment = _attachment("PDF-1", "ITEM-1")
    zotero = FakeZotero(
        version=1,
        items=[item],
        annotations=[_annotation("ANN-1", "PDF-1", "Original")],
        attachments=[attachment],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        original_signature = state.get_item_state("ITEM-1").child_signature  # type: ignore[union-attr]

        zotero.version = 2
        zotero.modified_items = []
        zotero.annotations = [_annotation("ANN-1", "PDF-1", "Revised", version=2)]
        zotero.calls.clear()

        result = engine.incremental_sync(show_progress=False)
        revised = state.get_item_state("ITEM-1")

        assert result.errors == []
        assert result.items_updated == 1
        assert result.annotations_synced == 1
        assert revised is not None
        assert revised.child_signature != original_signature
        assert state.get_last_library_version() == 2
        assert zotero.calls == [
            "version",
            "modified:1",
            "deleted:1",
            "annotations",
            "attachments",
            "version",
        ]

    assert "Revised" in (output / "paper.md").read_text(encoding="utf-8")
    assert "Original" not in (output / "paper.md").read_text(encoding="utf-8")


def test_annotation_api_order_does_not_change_child_signature(tmp_path):
    item = _item("ITEM-1", "paper")
    attachment = _attachment("PDF-1", "ITEM-1")
    first = _annotation("ANN-1", "PDF-1", "First")
    second = _annotation("ANN-2", "PDF-1", "Second")
    zotero = FakeZotero(
        version=1,
        items=[item],
        annotations=[first, second],
        attachments=[attachment],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)

        zotero.version = 2
        zotero.modified_items = []
        zotero.annotations = [second, first]
        result = engine.incremental_sync(show_progress=False)

        assert result.errors == []
        assert result.total_items_processed == 0
        assert result.items_updated == 0
        assert state.get_last_library_version() == 2


def test_citation_key_change_uses_stored_path_and_preserves_notes(tmp_path):
    original = _item("ITEM-1", "old-key", version=1)
    zotero = FakeZotero(version=1, items=[original])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        old_path = output / "old-key.md"
        old_path.write_text(
            old_path.read_text(encoding="utf-8").replace(
                "<!-- zotmd:notes:start -->\n<!-- zotmd:notes:end -->",
                "<!-- zotmd:notes:start -->\nKeep this note.\n<!-- zotmd:notes:end -->",
            ),
            encoding="utf-8",
        )

        revised = _item("ITEM-1", "new-key", version=2)
        zotero.version = 2
        zotero.items = [revised]
        zotero.modified_items = [revised]

        result = engine.incremental_sync(show_progress=False)
        stored = state.get_item_state("ITEM-1")

        assert result.errors == []
        assert result.items_updated == 1
        assert result.items_renamed == 1
        assert not old_path.exists()
        assert stored is not None
        assert stored.citation_key == "new-key"
        assert stored.file_path == str(output / "new-key.md")

    assert "Keep this note." in (output / "new-key.md").read_text(encoding="utf-8")


def test_citation_rename_race_preserves_competing_target(tmp_path, monkeypatch):
    item = _item("ITEM-1", "old-key")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        source = output / "old-key.md"
        target = output / "new-key.md"
        original = source.read_bytes()
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "new-key", version=2)]
        original_rename = engine.files.rename_path

        def create_competing_target(source_path, target_path, **kwargs):
            target.write_text("competing", encoding="utf-8")
            return original_rename(source_path, target_path, **kwargs)

        monkeypatch.setattr(engine.files, "rename_path", create_competing_target)
        result = engine.incremental_sync(show_progress=False)

        assert len(result.errors) == 1
        assert source.read_bytes() == original
        assert target.read_text(encoding="utf-8") == "competing"
        assert state.get_item_state("ITEM-1").citation_key == "old-key"  # type: ignore[union-attr]
        assert state.get_last_library_version() == 1


@pytest.mark.parametrize("replacement", [False, True])
def test_post_commit_note_change_withholds_checkpoint(
    tmp_path, monkeypatch, replacement
):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        target = output / "paper.md"
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "paper", version=2, title="Revised")]
        original_execute = engine._execute_item

        def execute_then_edit(plan, layout_identity):
            receipt = original_execute(plan, layout_identity)
            if replacement:
                competing = output / "competing.md"
                competing.write_bytes(b"concurrent replacement")
                competing.replace(target)
            else:
                target.write_bytes(b"concurrent in-place edit")
            return receipt

        monkeypatch.setattr(engine, "_execute_item", execute_then_edit)
        result = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert stored is not None and stored.zotero_version == 2
        assert state.get_last_library_version() == 1
        assert len(result.errors) == 1
        assert str(target) in result.errors[0]
        assert target.read_bytes().startswith(b"concurrent")

        zotero.calls.clear()
        retry = engine.incremental_sync(show_progress=False)

        assert len(retry.errors) == 1
        assert "pending sync change" in retry.errors[0]
        assert state.get_last_library_version() == 1
        assert zotero.calls == []


def test_old_path_recreated_after_citation_rename_withholds_checkpoint(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "old-key")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        old_path = output / "old-key.md"
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "new-key", version=2)]
        original_execute = engine._execute_item

        def execute_then_recreate(plan, layout_identity):
            receipt = original_execute(plan, layout_identity)
            old_path.write_bytes(b"editor recreated old path")
            return receipt

        monkeypatch.setattr(engine, "_execute_item", execute_then_recreate)
        result = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert stored is not None and stored.citation_key == "new-key"
        assert state.get_last_library_version() == 1
        assert len(result.errors) == 1
        assert str(old_path) in result.errors[0]
        assert old_path.read_bytes() == b"editor recreated old path"
        assert (output / "new-key.md").is_file()

        zotero.calls.clear()
        retry = engine.incremental_sync(show_progress=False)

        assert len(retry.errors) == 1
        assert "pending sync change" in retry.errors[0]
        assert state.get_last_library_version() == 1
        assert zotero.calls == []


def test_pending_receipt_survives_checkpoint_failure_and_clears_on_retry(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        revised = _item("ITEM-1", "paper", version=2, title="Revised")
        zotero.version = 2
        zotero.modified_items = [revised]
        original_record = state.record_template_version

        def fail_checkpoint(*args, **kwargs):
            raise RuntimeError("checkpoint write failed")

        monkeypatch.setattr(state, "record_template_version", fail_checkpoint)
        first = engine.incremental_sync(show_progress=False)

        pending = state.get_item_state("ITEM-1")
        assert first.errors == [
            "Error recording sync checkpoint: checkpoint write failed"
        ]
        assert pending is not None and pending.zotero_version == 2
        assert "_zotmd_pending_change" in (pending.item_json or "")
        assert state.get_last_library_version() == 1

        monkeypatch.setattr(state, "record_template_version", original_record)
        second = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert second.errors == []
        assert second.items_updated == 0
        assert stored is not None
        assert json.loads(stored.item_json or "") == revised
        assert state.get_last_library_version() == 2


def test_post_checkpoint_verification_restores_checkpoint_after_late_edit(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        target = output / "paper.md"
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "paper", version=2, title="Revised")]
        original_verify = engine._require_applied_changes
        verification_count = 0

        def edit_before_post_checkpoint_verification(changes, layout_identity):
            nonlocal verification_count
            verification_count += 1
            if verification_count == 2:
                target.write_bytes(b"late concurrent edit")
            return original_verify(changes, layout_identity)

        monkeypatch.setattr(
            engine,
            "_require_applied_changes",
            edit_before_post_checkpoint_verification,
        )
        result = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert len(result.errors) == 1
        assert "Error confirming sync checkpoint" in result.errors[0]
        assert state.get_last_library_version() == 1
        assert stored is not None
        assert "_zotmd_pending_change" in (stored.item_json or "")
        assert target.read_bytes() == b"late concurrent edit"

        zotero.calls.clear()
        retry = engine.incremental_sync(show_progress=False)

        assert len(retry.errors) == 1
        assert "pending sync change" in retry.errors[0]
        assert state.get_last_library_version() == 1
        assert zotero.calls == []


def test_unchanged_retry_clears_receipt_left_by_cleanup_failure(tmp_path, monkeypatch):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        previous_checkpoint = state.get_checkpoint()
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "paper", version=2, title="Revised")]
        original_upsert = state.upsert_item

        def fail_receipt_cleanup(item_state, item_json=None):
            if (
                item_json is not None
                and "_zotmd_pending_change" not in item_json
                and state.get_last_library_version() == 2
            ):
                raise RuntimeError("receipt cleanup failed")
            return original_upsert(item_state, item_json=item_json)

        monkeypatch.setattr(state, "upsert_item", fail_receipt_cleanup)
        first = engine.incremental_sync(show_progress=False)

        pending = state.get_item_state("ITEM-1")
        assert first.errors == [
            "Error clearing pending file receipts: receipt cleanup failed"
        ]
        assert state.get_checkpoint() == previous_checkpoint
        assert pending is not None
        assert "_zotmd_pending_change" in (pending.item_json or "")
        revised_bytes = (output / "paper.md").read_bytes()

        monkeypatch.setattr(state, "upsert_item", original_upsert)
        second = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert second.errors == []
        assert second.items_updated == 0
        assert stored is not None
        assert "_zotmd_pending_change" not in (stored.item_json or "")
        assert state.get_last_library_version() == 2
        assert state.get_checkpoint() != previous_checkpoint
        assert (output / "paper.md").read_bytes() == revised_bytes


def test_receipt_cleanup_and_checkpoint_restore_failures_are_both_reported(
    tmp_path, monkeypatch
):
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "paper", version=2, title="Revised")]
        original_upsert = state.upsert_item

        def fail_receipt_cleanup(item_state, item_json=None):
            if item_json is not None and "_zotmd_pending_change" not in item_json:
                raise RuntimeError("receipt cleanup failed")
            return original_upsert(item_state, item_json=item_json)

        monkeypatch.setattr(state, "upsert_item", fail_receipt_cleanup)
        monkeypatch.setattr(
            state,
            "restore_checkpoint",
            lambda checkpoint: (_ for _ in ()).throw(
                RuntimeError("checkpoint restore failed")
            ),
        )
        result = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert result.errors == [
            "Error clearing pending file receipts: receipt cleanup failed",
            "Error restoring sync checkpoint after pending file receipt cleanup "
            "failure: checkpoint restore failed",
        ]
        assert stored is not None
        assert "_zotmd_pending_change" in (stored.item_json or "")
        assert state.get_last_library_version() == 2
        assert "Revised" in (output / "paper.md").read_text(encoding="utf-8")


def test_nested_reserved_metadata_is_not_treated_as_pending_receipt(tmp_path):
    item = _item("ITEM-1", "paper")
    item["meta"] = {"_zotmd_pending_change": {"upstream": True}}
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        first = engine.full_sync(show_progress=False)
        zotero.calls.clear()
        second = engine.incremental_sync(show_progress=False)

        assert first.errors == []
        assert second.errors == []
        assert zotero.calls == ["version"]


def test_sanitized_target_collisions_fail_both_items_before_writes(tmp_path):
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "same:key"), _item("ITEM-2", "samekey")],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        result = _engine(zotero, state, output).full_sync(show_progress=False)

        assert len(result.errors) == 2
        assert result.target_collisions == 2
        assert state.get_active_items() == []
        assert state.get_last_library_version() is None

    assert list(output.glob("*.md")) == []


def test_incremental_managed_collision_reports_and_preserves_both_items(tmp_path):
    zotero = FakeZotero(
        version=1,
        items=[_item("CHANGED", "changed"), _item("OWNER", "owner")],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        before_checkpoint = state.get_checkpoint()
        before_states = {key: state.get_item_state(key) for key in ("CHANGED", "OWNER")}
        before_files = {path.name: path.read_bytes() for path in output.glob("*.md")}
        zotero.version = 2
        zotero.modified_items = [_item("CHANGED", "owner", version=2)]

        result = engine.incremental_sync(show_progress=False)

        target = output / "owner.md"
        assert result.errors == [
            f"Target collision for item CHANGED: {target} is managed by OWNER",
            f"Target collision for item OWNER: {target} is targeted by CHANGED",
        ]
        assert result.target_collisions == 2
        assert result.items_updated == 0
        assert state.get_checkpoint() == before_checkpoint
        assert {
            key: state.get_item_state(key) for key in ("CHANGED", "OWNER")
        } == before_states
        assert {
            path.name: path.read_bytes() for path in output.glob("*.md")
        } == before_files


def test_managed_collision_suppresses_incumbent_removal(tmp_path):
    zotero = FakeZotero(
        version=1,
        items=[_item("CHANGED", "changed"), _item("OWNER", "owner")],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        before_checkpoint = state.get_checkpoint()
        before_states = {key: state.get_item_state(key) for key in ("CHANGED", "OWNER")}
        before_files = {path.name: path.read_bytes() for path in output.glob("*.md")}
        zotero.version = 2
        zotero.modified_items = [_item("CHANGED", "owner", version=2)]
        zotero.deleted = {"items": ["OWNER"]}

        result = engine.incremental_sync(show_progress=False)

        assert result.target_collisions == 2
        assert result.items_updated == 0
        assert result.items_removed == 0
        assert state.get_checkpoint() == before_checkpoint
        assert {
            key: state.get_item_state(key) for key in ("CHANGED", "OWNER")
        } == before_states
        assert {
            path.name: path.read_bytes() for path in output.glob("*.md")
        } == before_files


def test_planned_incumbent_collision_has_one_diagnostic_per_item(tmp_path):
    zotero = FakeZotero(
        version=1,
        items=[_item("CHANGED", "changed"), _item("OWNER", "owner")],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        before_checkpoint = state.get_checkpoint()
        zotero.version = 2
        zotero.modified_items = [
            _item("CHANGED", "owner", version=2),
            _item("OWNER", "owner", version=2),
        ]

        result = engine.incremental_sync(show_progress=False)

        assert result.errors == [
            f"Target collision for item CHANGED: {output / 'owner.md'}",
            f"Target collision for item OWNER: {output / 'owner.md'}",
        ]
        assert result.target_collisions == 2
        assert state.get_checkpoint() == before_checkpoint


def test_duplicate_top_level_keys_fail_before_writes_or_checkpoint(tmp_path):
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "first"), _item("ITEM-1", "second")],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        with pytest.raises(ValueError, match="Duplicate top-level item key: ITEM-1"):
            _engine(zotero, state, output).full_sync(show_progress=False)

        assert state.get_active_items() == []
        assert state.get_last_library_version() is None

    assert not output.exists()
    assert zotero.calls == [
        "version",
        "items",
        "annotations",
        "attachments",
        "version",
    ]


def test_duplicate_attachment_keys_fail_before_writes_or_checkpoint(tmp_path):
    attachment = _attachment("PDF-1", "ITEM-1")
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "paper")],
        attachments=[attachment, attachment],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        with pytest.raises(ValueError, match="Duplicate attachment key: PDF-1"):
            _engine(zotero, state, output).full_sync(show_progress=False)

        assert state.get_active_items() == []
        assert state.get_last_library_version() is None

    assert not output.exists()


def test_duplicate_annotation_keys_fail_before_writes_or_checkpoint(tmp_path):
    annotation = _annotation("ANN-1", "PDF-1", "Highlight")
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "paper")],
        attachments=[_attachment("PDF-1", "ITEM-1")],
        annotations=[annotation, annotation],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        with pytest.raises(ValueError, match="Duplicate annotation key: ANN-1"):
            _engine(zotero, state, output).full_sync(show_progress=False)

        assert state.get_active_items() == []
        assert state.get_last_library_version() is None

    assert not output.exists()


def test_case_insensitive_target_aliases_fail_before_writes(tmp_path):
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "Paper"), _item("ITEM-2", "paper")],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        result = _engine(zotero, state, output).full_sync(show_progress=False)

        assert len(result.errors) == 2
        assert result.target_collisions == 2
        assert state.get_active_items() == []
        assert state.get_last_library_version() is None

    assert list(output.glob("*.md")) == []


def test_case_only_citation_change_is_reported_without_unsafe_move(tmp_path):
    item = _item("ITEM-1", "Paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        revised = _item("ITEM-1", "paper", version=2)
        zotero.version = 2
        zotero.modified_items = [revised]

        result = engine.incremental_sync(show_progress=False)
        stored = state.get_item_state("ITEM-1")

        assert result.errors == []
        assert result.items_renamed == 1
        assert stored is not None and stored.citation_key == "paper"
        assert stored.file_path == str(output / "paper.md")


def test_case_only_rename_tracks_vacated_path_on_case_sensitive_volume(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "Paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        source = output / "Paper.md"
        checked_absent: list[Path] = []
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "paper", version=2)]

        monkeypatch.setattr(engine.files, "paths_alias", lambda first, second: False)

        def record_absent(path, **kwargs):
            checked_absent.append(Path(path))

        monkeypatch.setattr(engine.files, "require_path_absent", record_absent)
        result = engine.incremental_sync(show_progress=False)

        assert result.errors == []
        assert source in checked_absent
        assert state.get_last_library_version() == 2


def test_case_only_rename_commit_failure_restores_original_name(tmp_path, monkeypatch):
    item = _item("ITEM-1", "Paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        original = (output / "Paper.md").read_bytes()
        revised = _item("ITEM-1", "paper", version=2)
        zotero.version = 2
        zotero.modified_items = [revised]
        original_upsert = state.upsert_item

        def upsert_then_fail(item_state, item_json=None):
            original_upsert(item_state, item_json=item_json)
            raise RuntimeError("item state commit failed")

        monkeypatch.setattr(state, "upsert_item", upsert_then_fail)

        result = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert result.errors == ["Error syncing item ITEM-1: item state commit failed"]
        assert stored is not None and stored.citation_key == "Paper"
        assert (output / "Paper.md").read_bytes() == original
        assert {path.name for path in output.glob("*.md")} == {"Paper.md"}


def test_unmanaged_dangling_symlink_is_a_target_collision(tmp_path):
    output = tmp_path / "references"
    output.mkdir()
    target = output / "paper.md"
    target.symlink_to(output / "missing-target.md")
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        result = _engine(zotero, state, output).full_sync(show_progress=False)

        assert result.target_collisions == 1
        assert state.get_last_library_version() is None
        assert target.is_symlink()


def test_target_appearing_after_preflight_is_not_deleted(tmp_path, monkeypatch):
    output = tmp_path / "references"
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        original_write = engine.files.write_path
        target = output / "paper.md"

        def create_competing_target(path, content, **kwargs):
            target.write_text("competing", encoding="utf-8")
            return original_write(path, content, **kwargs)

        monkeypatch.setattr(
            engine.files,
            "write_path",
            create_competing_target,
        )
        result = engine.full_sync(show_progress=False)

        assert result.items_created == 0
        assert len(result.errors) == 1
        assert state.get_item_state("ITEM-1") is None
        assert state.get_last_library_version() is None
        assert target.read_text(encoding="utf-8") == "competing"


def test_managed_note_changed_after_render_is_not_overwritten(tmp_path, monkeypatch):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        target = output / "paper.md"
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "paper", version=2, title="Revised")]
        original_write = engine.files.write_path

        def change_source_then_write(path, content, **kwargs):
            target.write_text("concurrent user content", encoding="utf-8")
            return original_write(path, content, **kwargs)

        monkeypatch.setattr(engine.files, "write_path", change_source_then_write)
        result = engine.incremental_sync(show_progress=False)

        assert result.items_updated == 0
        assert len(result.errors) == 1
        assert "Managed file changed during synchronization" in result.errors[0]
        assert target.read_text(encoding="utf-8") == "concurrent user content"
        assert state.get_last_library_version() == 1


@pytest.mark.parametrize("deletion_behavior", ["move", "delete"])
def test_managed_note_changed_before_removal_is_preserved(
    tmp_path, monkeypatch, deletion_behavior
):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(
            zotero,
            state,
            output,
            deletion_behavior=deletion_behavior,
        )
        engine.full_sync(show_progress=False)
        source = output / "paper.md"
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1"]}
        method_name = "move_path" if deletion_behavior == "move" else "delete_path"
        original_mutation = getattr(engine.files, method_name)

        def change_source_then_mutate(*args, **kwargs):
            source.write_text("concurrent user content", encoding="utf-8")
            return original_mutation(*args, **kwargs)

        monkeypatch.setattr(engine.files, method_name, change_source_then_mutate)
        result = engine.incremental_sync(show_progress=False)

        assert result.items_removed == 0
        assert len(result.errors) == 1
        assert "Managed file changed during synchronization" in result.errors[0]
        assert source.read_text(encoding="utf-8") == "concurrent user content"
        assert state.get_item_state("ITEM-1").sync_status == "active"  # type: ignore[union-attr]
        assert state.get_last_library_version() == 1


@pytest.mark.parametrize("deletion_behavior", ["move", "delete"])
def test_post_commit_removal_change_withholds_checkpoint_and_later_sync(
    tmp_path, monkeypatch, deletion_behavior
):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(
            zotero,
            state,
            output,
            deletion_behavior=deletion_behavior,
        )
        engine.full_sync(show_progress=False)
        source = output / "paper.md"
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1"]}
        original_execute = engine._execute_removal

        def execute_then_change(plan, layout_identity):
            receipt = original_execute(plan, layout_identity)
            if deletion_behavior == "move":
                (output / "removed" / "paper.md").write_bytes(
                    b"concurrent removed edit"
                )
            else:
                source.write_bytes(b"editor recreated active path")
            return receipt

        monkeypatch.setattr(engine, "_execute_removal", execute_then_change)
        result = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert stored is not None and stored.sync_status == "removed"
        assert state.get_last_library_version() == 1
        assert len(result.errors) == 1
        assert "ITEM-1" in result.errors[0]

        zotero.calls.clear()
        retry = engine.incremental_sync(show_progress=False)

        assert len(retry.errors) == 1
        assert "pending sync change" in retry.errors[0]
        assert state.get_last_library_version() == 1
        assert zotero.calls == []


def test_partial_render_failure_withholds_all_checkpoints(tmp_path, monkeypatch):
    zotero = FakeZotero(
        version=9,
        items=[_item("GOOD", "good"), _item("BAD", "bad")],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        original_render = engine.renderer.render_item

        def render_with_failure(*args, **kwargs):
            if kwargs["item"].key == "BAD":
                raise RuntimeError("broken template value")
            return original_render(*args, **kwargs)

        monkeypatch.setattr(engine.renderer, "render_item", render_with_failure)
        result = engine.full_sync(show_progress=False)

        assert result.items_created == 1
        assert result.errors == ["Error rendering item BAD: broken template value"]
        assert state.get_item_state("GOOD") is not None
        assert state.get_item_state("BAD") is None
        assert state.get_last_library_version() is None
        assert state.get_template_version() is None


def test_malformed_existing_item_is_not_treated_as_missing_citation_key(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output, deletion_behavior="delete")
        engine.full_sync(show_progress=False)
        malformed = _item("ITEM-1", None, version=2)
        malformed["data"]["extra"] = 123
        zotero.version = 2
        zotero.modified_items = [malformed]

        with pytest.raises(ValueError, match="extra is not a string"):
            engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert stored is not None and stored.sync_status == "active"
        assert state.get_last_library_version() == 1
        assert (output / "paper.md").is_file()


@pytest.mark.parametrize(
    "error_type",
    [UserNotAuthorisedError, HTTPError, TooManyRetriesError],
)
def test_remote_api_failures_cannot_advance_checkpoints(
    tmp_path, monkeypatch, error_type
):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        before_checkpoint = state.get_checkpoint()
        before_state = state.get_item_state("ITEM-1")
        before_file = (output / "paper.md").read_bytes()
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "paper", version=2)]
        error = error_type("remote read failed")

        def fail_read():
            raise error

        monkeypatch.setattr(zotero, "get_all_attachments", fail_read)

        with pytest.raises(error_type) as raised:
            engine.incremental_sync(show_progress=False)

        assert raised.value is error
        assert state.get_checkpoint() == before_checkpoint
        assert state.get_item_state("ITEM-1") == before_state
        assert (output / "paper.md").read_bytes() == before_file


@pytest.mark.parametrize("field_name", VENUE_FIELDS)
@pytest.mark.parametrize("malformed", [[], {}, 42, False])
def test_malformed_venue_candidates_are_rejected(field_name, malformed):
    item = _item("ITEM-1", "paper")
    item["data"][field_name] = malformed

    with pytest.raises(
        ValueError,
        match=rf"Malformed top-level item ITEM-1: {field_name} is not a string",
    ):
        SyncEngine._validate_top_level_item(item)


def test_type_specific_venue_renders_as_scalar_frontmatter(tmp_path):
    item = _item("ITEM-1", "paper")
    item["data"]["proceedingsTitle"] = "Proceedings of Safe Synchronization"
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        result = _engine(zotero, state, output).full_sync(show_progress=False)

        assert result.errors == []
        assert state.get_last_library_version() == 1

    rendered = (output / "paper.md").read_text(encoding="utf-8")
    metadata = yaml.safe_load(rendered.split("---", 2)[1])
    assert metadata["venue"] == "Proceedings of Safe Synchronization"
    assert isinstance(metadata["venue"], str)


def test_missing_managed_file_blocks_rewrite_and_checkpoint(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        (output / "paper.md").unlink()
        revised = _item("ITEM-1", "paper", version=2)
        zotero.version = 2
        zotero.modified_items = [revised]

        result = engine.incremental_sync(show_progress=False)

        assert result.items_updated == 0
        assert result.errors == [
            f"Error syncing item ITEM-1: stored file does not exist: {output / 'paper.md'}"
        ]
        assert state.get_last_library_version() == 1
        assert not (output / "paper.md").exists()


def test_full_sync_rejects_stored_path_that_resolves_outside_output(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"
    external = tmp_path / "external.md"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        original = (output / "paper.md").read_bytes()
        external.write_text("external", encoding="utf-8")
        stored = state.get_item_state("ITEM-1")
        assert stored is not None
        unsafe_path = output / ".." / external.name
        state.upsert_item(replace(stored, file_path=str(unsafe_path)))
        zotero.calls.clear()

        result = engine.full_sync(show_progress=False)

        assert result.errors == [
            f"Managed item ITEM-1 is outside the output root: {unsafe_path}"
        ]
        assert zotero.calls == []
        assert (output / "paper.md").read_bytes() == original
        assert external.read_text(encoding="utf-8") == "external"
        assert state.get_last_library_version() == 1


def test_managed_file_disappearing_during_read_blocks_rewrite(tmp_path, monkeypatch):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        revised = _item("ITEM-1", "paper", version=2)
        zotero.version = 2
        zotero.modified_items = [revised]
        original_read = engine.files.read_path_with_identity

        def remove_before_read(path):
            Path(path).unlink()
            return original_read(path)

        monkeypatch.setattr(engine.files, "read_path_with_identity", remove_before_read)
        result = engine.incremental_sync(show_progress=False)

        assert result.items_updated == 0
        assert result.errors == [
            f"Error rendering item ITEM-1: stored file does not exist: {output / 'paper.md'}"
        ]
        assert state.get_last_library_version() == 1


def test_output_directory_replacement_withholds_checkpoint(tmp_path, monkeypatch):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"
    hidden_output = tmp_path / "hidden-references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        original_note = (output / "paper.md").read_bytes()
        revised = _item("ITEM-1", "paper", version=2, title="Revised")
        zotero.version = 2
        zotero.modified_items = [revised]
        original_write = engine.files.write_path
        replaced = False

        def replace_output_then_write(path, content, **kwargs):
            nonlocal replaced
            if not replaced:
                replaced = True
                output.rename(hidden_output)
                output.mkdir()
                (output / "paper.md").write_text("competing", encoding="utf-8")
            return original_write(path, content, **kwargs)

        monkeypatch.setattr(engine.files, "write_path", replace_output_then_write)
        result = engine.incremental_sync(show_progress=False)

        assert result.items_updated == 0
        assert result.errors == [
            "Error syncing item ITEM-1: output directory changed during synchronization"
        ]
        assert state.get_last_library_version() == 1

    assert (hidden_output / "paper.md").read_bytes() == original_note
    assert (output / "paper.md").read_text(encoding="utf-8") == "competing"


def test_output_replacement_before_rename_preserves_both_roots(tmp_path, monkeypatch):
    item = _item("ITEM-1", "old-key")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"
    hidden_output = tmp_path / "hidden-references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        original = (output / "old-key.md").read_bytes()
        zotero.version = 2
        zotero.modified_items = [_item("ITEM-1", "new-key", version=2)]
        original_rename = engine.files.rename_path

        def replace_root_then_rename(source, target, **kwargs):
            output.rename(hidden_output)
            output.mkdir()
            (output / "new-key.md").write_text("competing", encoding="utf-8")
            return original_rename(source, target, **kwargs)

        monkeypatch.setattr(engine.files, "rename_path", replace_root_then_rename)
        result = engine.incremental_sync(show_progress=False)

        assert len(result.errors) == 1
        assert state.get_last_library_version() == 1

    assert (hidden_output / "old-key.md").read_bytes() == original
    assert (output / "new-key.md").read_text(encoding="utf-8") == "competing"


def test_output_replacement_before_delete_preserves_both_roots(tmp_path, monkeypatch):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"
    hidden_output = tmp_path / "hidden-references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output, deletion_behavior="delete")
        engine.full_sync(show_progress=False)
        original = (output / "paper.md").read_bytes()
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1"]}
        original_delete = engine.files.delete_path

        def replace_root_then_delete(path, **kwargs):
            output.rename(hidden_output)
            output.mkdir()
            (output / "paper.md").write_text("competing", encoding="utf-8")
            return original_delete(path, **kwargs)

        monkeypatch.setattr(engine.files, "delete_path", replace_root_then_delete)
        result = engine.incremental_sync(show_progress=False)

        assert len(result.errors) == 1
        assert state.get_item_state("ITEM-1").sync_status == "active"  # type: ignore[union-attr]
        assert state.get_last_library_version() == 1

    assert (hidden_output / "paper.md").read_bytes() == original
    assert (output / "paper.md").read_text(encoding="utf-8") == "competing"


def test_interrupt_after_rename_rolls_back_file_and_state(tmp_path, monkeypatch):
    item = _item("ITEM-1", "old-key")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        original = (output / "old-key.md").read_bytes()
        revised = _item("ITEM-1", "new-key", version=2)
        zotero.version = 2
        zotero.modified_items = [revised]
        original_upsert = state.upsert_item

        def interrupt_on_update(item_state, item_json=None):
            if item_state.citation_key == "new-key":
                raise KeyboardInterrupt
            return original_upsert(item_state, item_json=item_json)

        monkeypatch.setattr(state, "upsert_item", interrupt_on_update)

        with pytest.raises(KeyboardInterrupt):
            engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert stored is not None and stored.citation_key == "old-key"
        assert (output / "old-key.md").read_bytes() == original
        assert not (output / "new-key.md").exists()
        assert state.get_last_library_version() == 1


def test_interrupt_after_rename_helper_returns_is_inferred_and_rolled_back(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "old-key")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        revised = _item("ITEM-1", "new-key", version=2)
        zotero.version = 2
        zotero.modified_items = [revised]
        original_rename = engine.files.rename_path
        interrupted = False

        def rename_then_interrupt(source, target, **kwargs):
            nonlocal interrupted
            result = original_rename(source, target, **kwargs)
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return result

        monkeypatch.setattr(engine.files, "rename_path", rename_then_interrupt)

        with pytest.raises(KeyboardInterrupt):
            engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert stored is not None and stored.citation_key == "old-key"
        assert (output / "old-key.md").is_file()
        assert not (output / "new-key.md").exists()


def test_interrupt_after_state_commit_keeps_committed_file_and_item_state(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "old-key")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        revised = _item("ITEM-1", "new-key", version=2)
        zotero.version = 2
        zotero.modified_items = [revised]
        original_transaction = state.transaction
        interrupted = False

        @contextmanager
        def commit_then_interrupt():
            nonlocal interrupted
            with original_transaction() as transaction_state:
                yield transaction_state
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt

        monkeypatch.setattr(state, "transaction", commit_then_interrupt)

        with pytest.raises(KeyboardInterrupt):
            engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert stored is not None and stored.citation_key == "new-key"
        assert stored.zotero_version == 2
        assert not (output / "old-key.md").exists()
        assert (output / "new-key.md").is_file()
        assert state.get_last_library_version() == 1


def test_removal_failure_leaves_item_active_and_checkpoint_pending(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        source = output / "paper.md"

        zotero.version = 2
        zotero.items = []
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1", "CHILD-1"]}
        error = PermissionError("move denied")

        def fail_move(*args, **kwargs):
            raise error

        monkeypatch.setattr(engine.files, "move_path", fail_move)
        result = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert result.items_removed == 0
        assert result.errors == ["Error removing item ITEM-1: move denied"]
        assert stored is not None
        assert stored.sync_status == "active"
        assert state.get_last_library_version() == 1
        assert source.is_file()


def test_removal_target_race_preserves_competing_file(tmp_path, monkeypatch):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        source = output / "paper.md"
        assert engine.files.removed_dir is not None
        target = engine.files.removed_dir / "paper.md"
        original_move = engine.files.move_path
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1"]}

        def create_competing_target(source_path, target_path, **kwargs):
            target.write_text("competing", encoding="utf-8")
            return original_move(source_path, target_path, **kwargs)

        monkeypatch.setattr(engine.files, "move_path", create_competing_target)
        result = engine.incremental_sync(show_progress=False)

        assert len(result.errors) == 1
        assert source.is_file()
        assert target.read_text(encoding="utf-8") == "competing"
        assert state.get_item_state("ITEM-1").sync_status == "active"  # type: ignore[union-attr]
        assert state.get_last_library_version() == 1


def test_removal_commit_failure_restores_file_and_active_state(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output, deletion_behavior="delete")
        engine.full_sync(show_progress=False)
        source = output / "paper.md"
        original = source.read_bytes()
        assert state.conn is not None
        state.conn.execute("PRAGMA busy_timeout = 0")
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1"]}

        with closing(sqlite3.connect(state.db_path)) as reader:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM sync_metadata").fetchone()
            result = engine.incremental_sync(show_progress=False)
            reader.rollback()

        assert len(result.errors) == 1
        assert "database is locked" in result.errors[0]
        assert source.read_bytes() == original
        assert state.get_item_state("ITEM-1").sync_status == "active"  # type: ignore[union-attr]
        assert state.get_last_library_version() == 1


def test_delete_rollback_does_not_overwrite_recreated_source(tmp_path, monkeypatch):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output, deletion_behavior="delete")
        engine.full_sync(show_progress=False)
        source = output / "paper.md"
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1"]}
        original_write = engine.files.write_path
        original_upsert = state.upsert_item

        def recreate_before_restore(*args, **kwargs):
            source.write_bytes(b"editor recreated source")
            return original_write(*args, **kwargs)

        def fail_removed_state(item_state, item_json=None):
            if item_state.sync_status == "removed":
                raise RuntimeError("removed state write failed")
            return original_upsert(item_state, item_json=item_json)

        monkeypatch.setattr(engine.files, "write_path", recreate_before_restore)
        monkeypatch.setattr(state, "upsert_item", fail_removed_state)
        result = engine.incremental_sync(show_progress=False)

        assert len(result.errors) == 1
        assert "file rollback failed" in result.errors[0]
        assert source.read_bytes() == b"editor recreated source"
        assert state.get_item_state("ITEM-1").sync_status == "active"  # type: ignore[union-attr]
        assert state.get_last_library_version() == 1


def test_changed_output_root_moves_only_tracked_notes_before_no_op(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    db_path = tmp_path / "sync.sqlite"
    old_output = tmp_path / "old-references"
    new_output = tmp_path / "new-references"

    with StateManager(db_path, LIBRARY_ID, old_output) as state:
        _engine(zotero, state, old_output).full_sync(show_progress=False)
    unmanaged = old_output / "unmanaged.md"
    unmanaged.write_text("leave me", encoding="utf-8")

    with StateManager(db_path, LIBRARY_ID, new_output) as state:
        result = _engine(zotero, state, new_output).incremental_sync(
            show_progress=False
        )
        stored = state.get_item_state("ITEM-1")

        assert result.errors == []
        assert result.output_items_moved == 1
        assert state.get_identity() == (LIBRARY_ID, new_output.resolve())
        assert stored is not None
        assert stored.file_path == str(new_output / "paper.md")

    assert (new_output / "paper.md").is_file()
    assert not (old_output / "paper.md").exists()
    assert unmanaged.read_text(encoding="utf-8") == "leave me"


def test_output_move_race_preserves_competing_target(tmp_path, monkeypatch):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    db_path = tmp_path / "sync.sqlite"
    old_output = tmp_path / "old-references"
    new_output = tmp_path / "new-references"

    with StateManager(db_path, LIBRARY_ID, old_output) as state:
        _engine(zotero, state, old_output).full_sync(show_progress=False)

    with StateManager(db_path, LIBRARY_ID, new_output) as state:
        engine = _engine(zotero, state, new_output)
        original_move = engine.files.move_path
        target = new_output / "paper.md"

        def create_competing_target(source_path, target_path, **kwargs):
            target.write_text("competing", encoding="utf-8")
            return original_move(source_path, target_path, **kwargs)

        monkeypatch.setattr(engine.files, "move_path", create_competing_target)
        result = engine.incremental_sync(show_progress=False)

        assert len(result.errors) == 1
        assert state.get_identity() == (LIBRARY_ID, old_output.resolve())

    assert (old_output / "paper.md").is_file()
    assert target.read_text(encoding="utf-8") == "competing"


def test_changed_output_root_moves_active_and_removed_managed_notes(tmp_path):
    first = _item("ITEM-1", "active")
    second = _item("ITEM-2", "removed")
    zotero = FakeZotero(version=1, items=[first, second])
    db_path = tmp_path / "sync.sqlite"
    old_output = tmp_path / "old-references"
    new_output = tmp_path / "new-references"

    with StateManager(db_path, LIBRARY_ID, old_output) as state:
        engine = _engine(zotero, state, old_output)
        engine.full_sync(show_progress=False)
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-2"]}
        engine.incremental_sync(show_progress=False)

    with StateManager(db_path, LIBRARY_ID, new_output) as state:
        result = _engine(zotero, state, new_output).incremental_sync(
            show_progress=False
        )
        removed = state.get_item_state("ITEM-2")

        assert result.errors == []
        assert result.output_items_moved == 2
        assert removed is not None
        assert removed.file_path == str(new_output / "removed" / "removed.md")

    assert (new_output / "active.md").is_file()
    assert (new_output / "removed" / "removed.md").is_file()


def test_output_migration_guards_old_removed_directory_identity(tmp_path, monkeypatch):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    db_path = tmp_path / "sync.sqlite"
    old_output = tmp_path / "old-references"
    new_output = tmp_path / "new-references"
    old_removed = old_output / "removed"
    hidden_removed = old_output / "hidden-removed"

    with StateManager(db_path, LIBRARY_ID, old_output) as state:
        engine = _engine(zotero, state, old_output)
        engine.full_sync(show_progress=False)
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1"]}
        engine.incremental_sync(show_progress=False)

    with StateManager(db_path, LIBRARY_ID, new_output) as state:
        engine = _engine(zotero, state, new_output)
        original_move = engine.files.move_path
        replaced = False

        def replace_old_removed_then_move(source_path, target_path, **kwargs):
            nonlocal replaced
            if not replaced:
                replaced = True
                old_removed.rename(hidden_removed)
                old_removed.mkdir()
            return original_move(source_path, target_path, **kwargs)

        monkeypatch.setattr(engine.files, "move_path", replace_old_removed_then_move)

        result = engine.incremental_sync(show_progress=False)

        assert len(result.errors) == 1
        assert "source output directory changed" in result.errors[0]
        assert state.get_identity() == (LIBRARY_ID, old_output.resolve())

    assert (hidden_removed / "paper.md").is_file()
    assert list(old_removed.iterdir()) == []
    assert not (new_output / "removed" / "paper.md").exists()


def test_permanently_deleted_item_does_not_block_output_change(tmp_path):
    first = _item("ITEM-1", "active")
    second = _item("ITEM-2", "deleted")
    zotero = FakeZotero(version=1, items=[first, second])
    db_path = tmp_path / "sync.sqlite"
    old_output = tmp_path / "old-references"
    new_output = tmp_path / "new-references"

    with StateManager(db_path, LIBRARY_ID, old_output) as state:
        engine = _engine(zotero, state, old_output, deletion_behavior="delete")
        engine.full_sync(show_progress=False)
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-2"]}
        result = engine.incremental_sync(show_progress=False)
        deleted = state.get_item_state("ITEM-2")
        assert result.errors == []
        assert deleted is not None and deleted.file_path == ""

    with StateManager(db_path, LIBRARY_ID, new_output) as state:
        result = _engine(
            zotero,
            state,
            new_output,
            deletion_behavior="delete",
        ).incremental_sync(show_progress=False)

        assert result.errors == []
        assert result.output_items_moved == 1
        assert state.get_identity() == (LIBRARY_ID, new_output.resolve())


@pytest.mark.parametrize("full", [False, True])
def test_active_item_losing_citation_key_is_skipped_without_removal(tmp_path, full):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output, deletion_behavior="delete")
        engine.full_sync(show_progress=False)
        note = output / "paper.md"
        original = note.read_bytes()
        without_key = _item("ITEM-1", None, version=2)
        zotero.version = 2
        zotero.items = [without_key]
        zotero.modified_items = [without_key]

        result = (
            engine.full_sync(show_progress=False)
            if full
            else engine.incremental_sync(show_progress=False)
        )

        stored = state.get_item_state("ITEM-1")
        assert result.errors == []
        assert result.items_skipped == 1
        assert result.items_removed == 0
        assert result.missing_citation_keys == ["ITEM-1"]
        assert note.read_bytes() == original
        assert stored is not None and stored.sync_status == "active"
        assert stored.citation_key == "paper"
        assert state.get_last_library_version() == 2


def test_keyless_item_is_not_rerendered_from_cache_after_child_or_template_change(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "paper")
    attachment = _attachment("PDF-1", "ITEM-1")
    zotero = FakeZotero(
        version=1,
        items=[item],
        annotations=[_annotation("ANN-1", "PDF-1", "Original")],
        attachments=[attachment],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        note = output / "paper.md"
        original = note.read_bytes()

        without_key = _item("ITEM-1", None, version=2)
        zotero.version = 2
        zotero.modified_items = [without_key]
        zotero.annotations = [_annotation("ANN-1", "PDF-1", "Revised", version=2)]
        first = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert first.errors == []
        assert first.items_updated == 0
        assert first.missing_citation_keys == ["ITEM-1"]
        assert note.read_bytes() == original
        assert stored is not None and stored.sync_status == "active"
        assert json.loads(stored.item_json or "") == without_key
        assert state.get_last_library_version() == 2

        original_hash = engine.renderer.get_template_hash()
        monkeypatch.setattr(
            engine.renderer,
            "get_template_hash",
            lambda: f"changed:{original_hash}",
        )
        second = engine.incremental_sync(show_progress=False)

        assert second.errors == []
        assert second.items_updated == 0
        assert second.missing_citation_keys == ["ITEM-1"]
        assert note.read_bytes() == original

        restored = _item("ITEM-1", "restored", version=3)
        zotero.version = 3
        zotero.modified_items = [restored]
        third = engine.incremental_sync(show_progress=False)

        assert third.errors == []
        assert third.items_updated == 1
        assert third.items_renamed == 1
        assert not note.exists()
        assert (output / "restored.md").is_file()


@pytest.mark.parametrize("full", [False, True])
def test_trashed_item_is_removed_without_deleted_tombstone(tmp_path, full):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        trashed = _trashed(_item("ITEM-1", None, version=2))
        zotero.version = 2
        zotero.items = [trashed]
        zotero.modified_items = [trashed]
        zotero.deleted = {"items": []}

        result = (
            engine.full_sync(show_progress=False)
            if full
            else engine.incremental_sync(show_progress=False)
        )

        stored = state.get_item_state("ITEM-1")
        assert result.errors == []
        assert result.items_removed == 1
        assert result.missing_citation_keys == []
        assert stored is not None and stored.sync_status == "removed"
        assert (output / "removed" / "paper.md").is_file()
        assert state.get_last_library_version() == 2


def test_restoring_trashed_item_uses_modified_active_record(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        trashed = _trashed(_item("ITEM-1", "paper", version=2))
        zotero.version = 2
        zotero.modified_items = [trashed]
        engine.incremental_sync(show_progress=False)

        restored = _item("ITEM-1", "restored", version=3)
        zotero.version = 3
        zotero.modified_items = [restored]
        zotero.deleted = {"items": []}
        result = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert result.errors == []
        assert result.items_updated == 1
        assert stored is not None and stored.sync_status == "active"
        assert stored.file_path == str(output / "restored.md")
        assert (output / "restored.md").is_file()


def test_incremental_retries_mixed_trash_snapshot_before_removal(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        original = (output / "paper.md").read_bytes()

        zotero.version = 3
        zotero.version_responses = [2, 3, 3, 3]
        zotero.modified_item_responses = [
            [_trashed(_item("ITEM-1", "paper", version=2))],
            [_item("ITEM-1", "paper", version=3)],
        ]
        zotero.deleted_responses = [{"items": []}, {"items": []}]
        result = engine.incremental_sync(show_progress=False)

        stored = state.get_item_state("ITEM-1")
        assert result.errors == []
        assert result.items_removed == 0
        assert stored is not None and stored.sync_status == "active"
        assert stored.zotero_version == 3
        assert state.get_last_library_version() == 3
        assert (output / "paper.md").read_bytes() == original


@pytest.mark.parametrize("full", [False, True])
def test_restored_removed_item_reuses_path_and_preserves_notes(tmp_path, full):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        note = output / "paper.md"
        note.write_text(
            note.read_text(encoding="utf-8").replace(
                "<!-- zotmd:notes:start -->\n<!-- zotmd:notes:end -->",
                "<!-- zotmd:notes:start -->\nPreserve me.\n<!-- zotmd:notes:end -->",
            ),
            encoding="utf-8",
        )
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1"]}
        engine.incremental_sync(show_progress=False)
        removed = output / "removed" / "paper.md"
        assert removed.is_file()

        restored_item = _item("ITEM-1", "restored", version=3)
        zotero.version = 3
        zotero.items = [restored_item]
        zotero.modified_items = [restored_item]
        zotero.deleted = {"items": []}
        result = (
            engine.full_sync(show_progress=False)
            if full
            else engine.incremental_sync(show_progress=False)
        )

        restored = output / "restored.md"
        stored = state.get_item_state("ITEM-1")
        assert result.errors == []
        assert result.items_updated == 1
        assert not removed.exists()
        assert "Preserve me." in restored.read_text(encoding="utf-8")
        assert stored is not None and stored.sync_status == "active"
        assert stored.file_path == str(restored)


def test_symlinked_removed_directory_is_rejected_without_escape(tmp_path):
    output = tmp_path / "references"
    external = tmp_path / "external"
    output.mkdir()
    external.mkdir()
    (output / "removed").symlink_to(external, target_is_directory=True)
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        result = _engine(zotero, state, output).full_sync(show_progress=False)

        assert result.errors == [
            f"Output removal path must not be a symbolic link: {output / 'removed'}"
        ]
        assert state.get_last_library_version() is None

    assert list(external.iterdir()) == []
    assert list(output.glob("*.md")) == []


def test_output_symlink_replacement_before_initial_layout_does_not_escape(
    tmp_path, monkeypatch
):
    output = tmp_path / "references"
    hidden_output = tmp_path / "hidden-references"
    external = tmp_path / "external"
    external.mkdir()
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        original_render = engine._render_items

        def render_then_replace(*args, **kwargs):
            plans = original_render(*args, **kwargs)
            output.mkdir()
            output.rename(hidden_output)
            output.symlink_to(external, target_is_directory=True)
            return plans

        monkeypatch.setattr(engine, "_render_items", render_then_replace)

        with pytest.raises(
            (RuntimeError, ValueError), match="symbolic link|output directory"
        ):
            engine.full_sync(show_progress=False)

        assert state.get_item_state("ITEM-1") is None
        assert state.get_last_library_version() is None

    assert list(external.iterdir()) == []
    assert list(hidden_output.iterdir()) == []


def test_removed_directory_replacement_before_move_does_not_escape(
    tmp_path, monkeypatch
):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"
    external = tmp_path / "external"
    external.mkdir()

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        source = output / "paper.md"
        assert engine.files.removed_dir is not None
        removed = engine.files.removed_dir
        hidden_removed = output / "hidden-removed"
        original_move = engine.files.move_path
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": ["ITEM-1"]}

        def replace_removed_then_move(source_path, target_path, **kwargs):
            removed.rename(hidden_removed)
            removed.symlink_to(external, target_is_directory=True)
            return original_move(source_path, target_path, **kwargs)

        monkeypatch.setattr(engine.files, "move_path", replace_removed_then_move)
        result = engine.incremental_sync(show_progress=False)

        assert len(result.errors) == 1
        assert source.is_file()
        assert state.get_item_state("ITEM-1").sync_status == "active"  # type: ignore[union-attr]
        assert state.get_last_library_version() == 1

    assert list(external.iterdir()) == []
    assert list(hidden_removed.iterdir()) == []


def test_dry_run_from_missing_state_reports_without_mutating(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"
    before = set(tmp_path.iterdir())

    result = _engine(zotero, None, output, dry_run=True).incremental_sync(
        show_progress=False
    )

    assert result.dry_run is True
    assert result.items_created == 1
    assert result.errors == []
    assert set(tmp_path.iterdir()) == before
    assert not output.exists()
    assert zotero.calls == [
        "version",
        "items",
        "annotations",
        "attachments",
        "version",
    ]


def test_sync_engine_requires_file_manager_mode_to_match_dry_run(tmp_path):
    output = tmp_path / "references"
    zotero = FakeZotero(version=1)
    db_path = tmp_path / "sync.sqlite"
    with StateManager(db_path, LIBRARY_ID, output):
        pass

    with StateManager(db_path, read_only=True) as state:
        with pytest.raises(ValueError, match="requires a read-only file manager"):
            SyncEngine(
                zotero,
                state,
                TemplateRenderer(),
                FileManager(output, create=False),
                LIBRARY_ID,
                dry_run=True,
            )

    with StateManager(db_path, LIBRARY_ID, output) as state:
        with pytest.raises(ValueError, match="requires a writable file manager"):
            SyncEngine(
                zotero,
                state,
                TemplateRenderer(),
                FileManager(output, create=False, read_only=True),
                LIBRARY_ID,
            )


def test_dry_run_successful_output_relocation_preserves_everything(tmp_path):
    db_path = tmp_path / "sync.sqlite"
    old_output = tmp_path / "old-references"
    new_output = tmp_path / "new-references"
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])
    with StateManager(db_path, LIBRARY_ID, old_output) as state:
        _engine(zotero, state, old_output).full_sync(show_progress=False)
    before_tree = _tree_snapshot(tmp_path)
    zotero.calls.clear()

    with StateManager(db_path, read_only=True) as state:
        before_checkpoint = state.get_checkpoint()
        result = _engine(zotero, state, new_output, dry_run=True).incremental_sync(
            show_progress=False
        )

        assert state.get_checkpoint() == before_checkpoint

    assert result.errors == []
    assert result.output_items_moved == 1
    assert zotero.calls == ["version"]
    assert _tree_snapshot(tmp_path) == before_tree


def test_dry_run_rewrite_preserves_files_state_and_checkpoint(tmp_path):
    db_path = tmp_path / "sync.sqlite"
    output = tmp_path / "references"
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])
    with StateManager(db_path, LIBRARY_ID, output) as state:
        _engine(zotero, state, output).full_sync(show_progress=False)
    before_tree = _tree_snapshot(tmp_path)
    zotero.version = 2
    zotero.modified_items = [
        _item("ITEM-1", "paper", version=2, title="Rewritten title")
    ]
    zotero.calls.clear()

    with StateManager(db_path, read_only=True) as state:
        before_checkpoint = state.get_checkpoint()
        result = _engine(zotero, state, output, dry_run=True).incremental_sync(
            show_progress=False
        )

        assert state.get_checkpoint() == before_checkpoint

    assert result.errors == []
    assert result.items_updated == 1
    assert _tree_snapshot(tmp_path) == before_tree


@pytest.mark.parametrize(
    ("deletion_behavior", "expected_deleted"),
    [("move", 0), ("delete", 1)],
)
def test_dry_run_removal_preserves_files_state_and_checkpoint(
    tmp_path, deletion_behavior, expected_deleted
):
    db_path = tmp_path / "sync.sqlite"
    output = tmp_path / "references"
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])
    with StateManager(db_path, LIBRARY_ID, output) as state:
        _engine(
            zotero,
            state,
            output,
            deletion_behavior=deletion_behavior,
        ).full_sync(show_progress=False)
    before_tree = _tree_snapshot(tmp_path)
    zotero.version = 2
    zotero.modified_items = []
    zotero.deleted = {"items": ["ITEM-1"]}
    zotero.calls.clear()

    with StateManager(db_path, read_only=True) as state:
        before_checkpoint = state.get_checkpoint()
        result = _engine(
            zotero,
            state,
            output,
            dry_run=True,
            deletion_behavior=deletion_behavior,
        ).incremental_sync(show_progress=False)

        assert state.get_checkpoint() == before_checkpoint

    assert result.errors == []
    assert result.items_removed == 1
    assert result.items_deleted == expected_deleted
    assert _tree_snapshot(tmp_path) == before_tree


def test_dry_run_reports_impossible_target_parent_without_mutating(tmp_path):
    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    output = blocked_parent / "references"
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    result = _engine(zotero, None, output, dry_run=True).full_sync(show_progress=False)

    assert result.items_created == 0
    assert result.errors == [
        "Output path is unavailable: "
        f"target parent is not a directory: {blocked_parent}"
    ]
    assert blocked_parent.read_text(encoding="utf-8") == "not a directory"


def test_dry_run_rejects_non_directory_removed_path(tmp_path):
    output = tmp_path / "references"
    output.mkdir()
    removed = output / "removed"
    removed.write_text("not a directory", encoding="utf-8")
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    result = _engine(zotero, None, output, dry_run=True).full_sync(show_progress=False)

    assert result.items_created == 0
    assert result.errors == [f"Output removal path is not a directory: {removed}"]
    assert removed.read_text(encoding="utf-8") == "not a directory"


def test_dry_run_existing_state_is_byte_and_file_stable(tmp_path):
    item = _item("ITEM-1", "paper", version=1)
    zotero = FakeZotero(version=1, items=[item])
    db_path = tmp_path / "sync.sqlite"
    output = tmp_path / "references"
    with StateManager(db_path, LIBRARY_ID, output) as state:
        _engine(zotero, state, output).full_sync(show_progress=False)

    before_tree = _tree_snapshot(tmp_path)
    revised = _item("ITEM-1", "renamed", version=2)
    zotero.version = 2
    zotero.items = [revised]
    zotero.modified_items = [revised]
    zotero.calls.clear()

    with StateManager(db_path, read_only=True) as state:
        before_checkpoint = state.get_checkpoint()
        result = _engine(zotero, state, output, dry_run=True).incremental_sync(
            show_progress=False
        )

        assert state.get_checkpoint() == before_checkpoint

    assert result.dry_run is True
    assert result.items_updated == 1
    assert result.items_renamed == 1
    assert _tree_snapshot(tmp_path) == before_tree
    assert not (output / "renamed.md").exists()
    assert zotero.calls == [
        "version",
        "modified:1",
        "deleted:1",
        "annotations",
        "attachments",
        "version",
    ]


def test_dry_run_stops_when_output_relocation_has_a_collision(tmp_path):
    db_path = tmp_path / "sync.sqlite"
    old_output = tmp_path / "old-references"
    new_output = tmp_path / "new-references"
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "first"), _item("ITEM-2", "second")],
    )
    with StateManager(db_path, LIBRARY_ID, old_output) as state:
        _engine(zotero, state, old_output).full_sync(show_progress=False)
    new_output.mkdir()
    (new_output / "first.md").write_text("collision", encoding="utf-8")
    zotero.version = 2
    zotero.modified_items = [_item("ITEM-2", "second", version=2, title="Revised")]
    zotero.calls.clear()

    with StateManager(db_path, read_only=True) as state:
        result = _engine(zotero, state, new_output, dry_run=True).incremental_sync(
            show_progress=False
        )

    assert len(result.errors) == 1
    assert "target already exists" in result.errors[0]
    assert result.output_items_moved == 0
    assert result.items_updated == 0
    assert zotero.calls == []


def test_unchanged_incremental_detects_missing_managed_note(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        note = output / "paper.md"
        note.unlink()
        zotero.calls.clear()

        result = engine.incremental_sync(show_progress=False)

        assert result.errors == [
            f"Error syncing item ITEM-1: stored file does not exist: {note}"
        ]
        assert state.get_last_library_version() == 1
        assert zotero.calls == []


def test_malformed_annotation_blocks_sync_before_mutation(tmp_path):
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "paper")],
        annotations=[{"key": "BROKEN", "version": 1, "data": {}}],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        with pytest.raises(
            ValueError, match="annotation BROKEN has no parent attachment"
        ):
            _engine(zotero, state, output).full_sync(show_progress=False)

        assert state.get_active_items() == []
        assert state.get_last_library_version() is None

    assert not output.exists()


def test_annotation_on_standalone_attachment_is_ignored(tmp_path):
    standalone = _attachment("PDF-STANDALONE", "ITEM-1")
    del standalone["data"]["parentItem"]
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "paper")],
        annotations=[_annotation("ANN-1", "PDF-STANDALONE", "Standalone")],
        attachments=[standalone],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        result = _engine(zotero, state, output).full_sync(show_progress=False)

        assert result.errors == []
        assert result.annotations_synced == 0
        assert state.get_last_library_version() == 1


@pytest.mark.parametrize(
    "annotation_data",
    [
        {"parentItem": "PDF-1", "annotationType": 42},
        {"parentItem": "PDF-1", "annotationType": "highlight", "annotationText": []},
    ],
)
def test_malformed_annotation_fields_block_checkpoint(tmp_path, annotation_data):
    annotation = {"key": "ANN-1", "version": 1, "data": annotation_data}
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "paper")],
        annotations=[annotation],
        attachments=[_attachment("PDF-1", "ITEM-1")],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        with pytest.raises(ValueError, match="Malformed annotation ANN-1"):
            _engine(zotero, state, output).full_sync(show_progress=False)

        assert state.get_last_library_version() is None
        assert not output.exists()


def test_malformed_attachment_parent_blocks_checkpoint(tmp_path):
    attachment = _attachment("PDF-1", "ITEM-1")
    attachment["data"]["parentItem"] = 42
    zotero = FakeZotero(
        version=1,
        items=[_item("ITEM-1", "paper")],
        attachments=[attachment],
    )
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        with pytest.raises(ValueError, match="parentItem is not a string"):
            _engine(zotero, state, output).full_sync(show_progress=False)

        assert state.get_last_library_version() is None


def test_malformed_deleted_response_blocks_checkpoint(tmp_path):
    item = _item("ITEM-1", "paper")
    zotero = FakeZotero(version=1, items=[item])
    output = tmp_path / "references"

    with StateManager(tmp_path / "sync.sqlite", LIBRARY_ID, output) as state:
        engine = _engine(zotero, state, output)
        engine.full_sync(show_progress=False)
        zotero.version = 2
        zotero.modified_items = []
        zotero.deleted = {"items": "ITEM-1"}  # type: ignore[dict-item]

        with pytest.raises(ValueError, match="deleted items is not a list"):
            engine.incremental_sync(show_progress=False)

        assert state.get_last_library_version() == 1
        assert (output / "paper.md").is_file()


def test_dry_run_can_preview_new_library_in_distinct_empty_output(tmp_path):
    db_path = tmp_path / "sync.sqlite"
    old_output = tmp_path / "old-references"
    new_output = tmp_path / "new-references"
    with StateManager(db_path, "OLD-LIBRARY", old_output):
        pass
    zotero = FakeZotero(version=1, items=[_item("ITEM-1", "paper")])

    with StateManager(db_path, read_only=True) as state:
        engine = SyncEngine(
            zotero_client=zotero,
            state_manager=state,
            renderer=TemplateRenderer(),
            file_manager=FileManager(new_output, create=False, read_only=True),
            library_id=LIBRARY_ID,
            dry_run=True,
        )
        result = engine.incremental_sync(show_progress=False)

    assert result.errors == []
    assert result.items_created == 1
    assert not new_output.exists()
