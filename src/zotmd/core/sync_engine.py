"""Safe reconciliation for Zotero-to-Markdown synchronization."""

import hashlib
import json
import os
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from alive_progress import alive_bar

from ..file_ops.file_manager import (
    FileIdentity,
    FileManager,
    MutationGuard,
    PathOperation,
)
from ..models.annotation import Annotation
from ..models.item import VENUE_FIELDS, ZoteroItem
from ..templates.renderer import RENDER_CONTRACT_VERSION, TemplateRenderer
from ..utils.citation_key import CitationKeyExtractor
from .state_manager import ItemState, StateManager
from .template_manager import TemplateChangeDetector
from .zotero_client import ZoteroClient

_SNAPSHOT_ATTEMPTS = 3
_PENDING_CHANGE_KEY = "_zotmd_pending_change"


@dataclass
class SyncResult:
    """Results from a completed or planned sync operation."""

    total_items_processed: int = 0
    items_created: int = 0
    items_updated: int = 0
    items_removed: int = 0
    items_skipped: int = 0
    annotations_synced: int = 0
    items_renamed: int = 0
    output_items_moved: int = 0
    items_deleted: int = 0
    target_collisions: int = 0
    dry_run: bool = False
    missing_citation_keys: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class BatchData:
    """Annotations and attachment relationships fetched for one interval."""

    annotations_by_item: dict[str, list[Annotation]] = field(default_factory=dict)
    attachments_by_item: dict[str, list[dict[str, object]]] = field(
        default_factory=dict
    )
    pdf_attachment_keys_by_item: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class _ItemPlan:
    raw_item: dict[str, Any]
    item: ZoteroItem
    existing: ItemState | None
    annotations: list[Annotation]
    child_signature: str
    target_path: Path
    existing_content: str | None = None
    source_identity: FileIdentity | None = None
    markdown: str | None = None
    applied_at: datetime | None = None
    move_operation: PathOperation = field(default_factory=PathOperation)
    write_operation: PathOperation = field(default_factory=PathOperation)

    @property
    def renamed(self) -> bool:
        return (
            self.existing is not None
            and self.existing.citation_key != self.item.citation_key
        )

    @property
    def moves_path(self) -> bool:
        return (
            self.existing is not None
            and Path(self.existing.file_path) != self.target_path
        )


@dataclass
class _RemovalPlan:
    item_state: ItemState
    source_path: Path
    target_path: Path | None
    existing_content: str
    source_identity: FileIdentity
    operation: PathOperation = field(default_factory=PathOperation)


@dataclass(frozen=True)
class _AppliedChange:
    zotero_key: str
    target_path: Path | None
    target_identity: FileIdentity | None
    content_sha256: str | None
    absent_paths: tuple[Path, ...]


@dataclass(frozen=True)
class _LayoutIdentity:
    root: tuple[int, int]
    removed: tuple[int, int] | None


class _OutputRootChangedError(RuntimeError):
    """Raised when the output directory changes during reconciliation."""


class SyncEngine:
    """Reconcile a personal Zotero library with generated Markdown notes."""

    def __init__(
        self,
        zotero_client: ZoteroClient,
        state_manager: StateManager | None,
        renderer: TemplateRenderer,
        file_manager: FileManager,
        library_id: str,
        *,
        dry_run: bool = False,
    ) -> None:
        if state_manager is None and not dry_run:
            raise ValueError("Writable synchronization requires a state manager")
        if dry_run and not file_manager.read_only:
            raise ValueError(
                "Dry-run synchronization requires a read-only file manager"
            )
        if not dry_run and file_manager.read_only:
            raise ValueError(
                "Writable synchronization requires a writable file manager"
            )
        self._dry_run_fresh_state = False
        if state_manager is not None:
            stored_library_id, stored_output = state_manager.get_identity()
            if dry_run and not state_manager.read_only:
                raise ValueError("Dry-run synchronization requires read-only state")
            if not dry_run and state_manager.read_only:
                raise ValueError("Writable synchronization requires writable state")
            if stored_library_id != library_id:
                target_output = file_manager.base_dir.expanduser().resolve()
                if not dry_run or target_output == stored_output:
                    raise ValueError(
                        f"State belongs to personal library {stored_library_id}, "
                        f"not {library_id}"
                    )
                if target_output.exists() and (
                    not target_output.is_dir() or any(target_output.iterdir())
                ):
                    raise ValueError(
                        "A different library requires a distinct empty output directory: "
                        f"{target_output}"
                    )
                self._dry_run_fresh_state = True

        self.zotero = zotero_client
        self.state = state_manager
        self.renderer = renderer
        self.files = file_manager
        self.library_id = library_id
        self.dry_run = dry_run

    def _fetch_batch_records(
        self, show_progress: bool = True
    ) -> tuple[list[dict], list[dict]]:
        """Fetch all annotations and attachments serially."""
        if show_progress:
            with alive_bar(
                2,
                title="Fetching library data",
                monitor=False,
                stats=False,
                enrich_print=False,
            ) as bar:
                annotations = self.zotero.get_all_annotations()
                bar.text = f"-> {len(annotations)} annotations"
                bar()
                attachments = self.zotero.get_all_attachments()
                bar.text = f"-> {len(attachments)} attachments"
                bar()
        else:
            annotations = self.zotero.get_all_annotations()
            attachments = self.zotero.get_all_attachments()
        return annotations, attachments

    def _build_batch_data(
        self,
        annotations: list[dict],
        attachments: list[dict],
    ) -> BatchData:
        """Validate child records and retain their parent relationships."""
        batch = BatchData()
        attachment_to_parent: dict[str, str] = {}
        standalone_attachments: set[str] = set()
        attachment_keys: set[str] = set()
        for raw_attachment in attachments:
            key, data, version = self._validate_child(raw_attachment, "attachment")
            if key in attachment_keys:
                raise ValueError(f"Duplicate attachment key: {key}")
            attachment_keys.add(key)
            parent_key = data.get("parentItem")
            if parent_key is None or parent_key == "":
                # Standalone attachments are top-level records and have no generated parent.
                standalone_attachments.add(key)
                continue
            if not isinstance(parent_key, str):
                raise ValueError(
                    f"Malformed attachment {key}: parentItem is not a string"
                )
            for field_name in ("contentType", "linkMode"):
                value = data.get(field_name)
                if value is not None and not isinstance(value, str):
                    raise ValueError(
                        f"Malformed attachment {key}: {field_name} is not a string"
                    )

            attachment_to_parent[key] = parent_key
            content_type = str(data.get("contentType", ""))
            normalized: dict[str, object] = {
                "key": key,
                "version": version,
                "parent_key": parent_key,
                "content_type": content_type,
                "link_mode": str(data.get("linkMode", "")),
            }
            batch.attachments_by_item.setdefault(parent_key, []).append(normalized)
            if "pdf" in content_type.lower():
                batch.pdf_attachment_keys_by_item.setdefault(parent_key, []).append(key)

        annotation_keys: set[str] = set()
        for raw_annotation in annotations:
            key, data, _ = self._validate_child(raw_annotation, "annotation")
            if key in annotation_keys:
                raise ValueError(f"Duplicate annotation key: {key}")
            annotation_keys.add(key)
            attachment_key = data.get("parentItem")
            if not isinstance(attachment_key, str) or not attachment_key:
                raise ValueError(f"annotation {key} has no parent attachment")
            parent_key = attachment_to_parent.get(attachment_key)
            if parent_key is None:
                if attachment_key in standalone_attachments:
                    continue
                raise ValueError(
                    f"annotation {key} references unknown attachment {attachment_key}"
                )
            annotation_type = data.get("annotationType")
            if not isinstance(annotation_type, str) or not annotation_type:
                raise ValueError(
                    f"Malformed annotation {key}: annotationType is not a string"
                )
            for field_name in (
                "annotationText",
                "annotationComment",
                "annotationColor",
                "annotationPageLabel",
                "annotationPosition",
                "dateAdded",
                "dateModified",
                "annotationSortIndex",
            ):
                value = data.get(field_name)
                if value is not None and not isinstance(value, str):
                    raise ValueError(
                        f"Malformed annotation {key}: {field_name} is not a string"
                    )
            annotation = Annotation.from_api_response(raw_annotation)
            batch.annotations_by_item.setdefault(parent_key, []).append(annotation)

        for keys in batch.pdf_attachment_keys_by_item.values():
            keys.sort()
        return batch

    def _stable_full_snapshot(
        self,
        show_progress: bool,
    ) -> tuple[int, list[tuple[str, dict[str, Any]]], BatchData]:
        for _ in range(_SNAPSHOT_ATTEMPTS):
            before = self.zotero.get_library_version()
            raw_items = self.zotero.get_all_items()
            annotations, attachments = self._fetch_batch_records(show_progress)
            after = self.zotero.get_library_version()
            if before == after:
                return (
                    after,
                    self._validate_top_level_items(raw_items),
                    self._build_batch_data(annotations, attachments),
                )
        raise RuntimeError(
            "Could not read a stable Zotero library snapshot after 3 attempts"
        )

    def _stable_incremental_snapshot(
        self,
        last_version: int,
        template_changed: bool,
        show_progress: bool,
    ) -> (
        tuple[
            int,
            list[tuple[str, dict[str, Any]]],
            set[str],
            BatchData,
        ]
        | None
    ):
        for _ in range(_SNAPSHOT_ATTEMPTS):
            before = self.zotero.get_library_version()
            if before == last_version and not template_changed:
                return None
            modified_items = (
                self.zotero.get_items_since_version(last_version)
                if before != last_version
                else []
            )
            deleted = (
                self.zotero.get_deleted_items(last_version)
                if before != last_version
                else {"items": []}
            )
            annotations, attachments = self._fetch_batch_records(show_progress)
            after = self.zotero.get_library_version()
            if before == after:
                return (
                    after,
                    self._validate_top_level_items(modified_items),
                    self._deleted_item_keys(deleted),
                    self._build_batch_data(annotations, attachments),
                )
        raise RuntimeError(
            "Could not read a stable Zotero library snapshot after 3 attempts"
        )

    @staticmethod
    def _validate_child(
        raw_child: object, child_type: str
    ) -> tuple[str, dict[str, Any], int]:
        if not isinstance(raw_child, dict):
            raise ValueError(f"Malformed {child_type} record")
        key = raw_child.get("key")
        data = raw_child.get("data")
        version = raw_child.get("version")
        if not isinstance(key, str) or not key:
            raise ValueError(f"Malformed {child_type} record without a key")
        if not isinstance(data, dict):
            raise ValueError(f"Malformed {child_type} {key}: data is not an object")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError(f"Malformed {child_type} {key}: version is not an integer")
        return key, data, version

    @staticmethod
    def _annotation_payload(annotation: Annotation) -> dict[str, object]:
        payload = asdict(annotation)
        for key in ("date_added", "date_modified"):
            value = payload[key]
            payload[key] = value.isoformat() if isinstance(value, datetime) else None
        return payload

    @classmethod
    def _child_signature(cls, batch: BatchData, item_key: str) -> str:
        payload = {
            "annotations": sorted(
                (
                    cls._annotation_payload(annotation)
                    for annotation in batch.annotations_by_item.get(item_key, [])
                ),
                key=lambda annotation: (
                    str(annotation["key"]),
                    str(annotation["version"]),
                ),
            ),
            "attachments": sorted(
                batch.attachments_by_item.get(item_key, []),
                key=lambda attachment: (
                    str(attachment["key"]),
                    str(attachment["version"]),
                ),
            ),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"v1:{hashlib.sha256(canonical).hexdigest()}"

    @staticmethod
    def _validate_top_level_item(raw_item: object) -> tuple[str, dict[str, Any]]:
        if not isinstance(raw_item, dict):
            raise ValueError("Malformed top-level item record")
        key = raw_item.get("key")
        data = raw_item.get("data")
        version = raw_item.get("version")
        if not isinstance(key, str) or not key:
            raise ValueError("Malformed top-level item record without a key")
        if not isinstance(data, dict):
            raise ValueError(f"Malformed top-level item {key}: data is not an object")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError(
                f"Malformed top-level item {key}: version is not an integer"
            )
        meta = raw_item.get("meta", {})
        if not isinstance(meta, dict):
            raise ValueError(f"Malformed top-level item {key}: meta is not an object")
        string_fields = (
            "key",
            "itemType",
            "title",
            "extra",
            "date",
            "dateAdded",
            "dateModified",
            "abstractNote",
            "DOI",
            "url",
            *VENUE_FIELDS,
            "volume",
            "issue",
            "pages",
        )
        for field_name in string_fields:
            value = data.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"Malformed top-level item {key}: {field_name} is not a string"
                )
        for field_name in ("creators", "tags", "collections"):
            value = data.get(field_name, [])
            if not isinstance(value, list):
                raise ValueError(
                    f"Malformed top-level item {key}: {field_name} is not a list"
                )
        if any(not isinstance(value, dict) for value in data.get("creators", [])):
            raise ValueError(
                f"Malformed top-level item {key}: creators contains a non-object"
            )
        if any(not isinstance(value, dict) for value in data.get("tags", [])):
            raise ValueError(
                f"Malformed top-level item {key}: tags contains a non-object"
            )
        deleted = data.get("deleted")
        if deleted is not None and (
            not isinstance(deleted, int) or isinstance(deleted, bool) or deleted != 1
        ):
            raise ValueError(
                f"Malformed top-level item {key}: deleted is not the integer 1"
            )
        return key, raw_item

    @classmethod
    def _validate_top_level_items(
        cls, raw_items: list[dict[str, Any]]
    ) -> list[tuple[str, dict[str, Any]]]:
        validated_items: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            key, validated = cls._validate_top_level_item(raw_item)
            if key in seen:
                raise ValueError(f"Duplicate top-level item key: {key}")
            seen.add(key)
            validated_items.append((key, validated))
        return validated_items

    def _parse_item(self, raw_item: dict[str, Any]) -> ZoteroItem | None:
        citation_key = CitationKeyExtractor.extract(raw_item)
        if citation_key is None:
            return None
        item = ZoteroItem.from_api_response(raw_item, self.library_id)
        if item is None:
            key = raw_item["key"]
            raise ValueError(f"Malformed top-level item {key}: cannot parse item data")
        return item

    @staticmethod
    def _is_trashed(raw_item: dict[str, Any]) -> bool:
        return raw_item["data"].get("deleted") == 1

    @staticmethod
    def _cached_raw_item(item_json: str) -> dict[str, Any]:
        cached = json.loads(item_json)
        if not isinstance(cached, dict):
            raise ValueError("cached item data is not an object")
        raw_item = dict(cached)
        raw_item.pop(_PENDING_CHANGE_KEY, None)
        return raw_item

    @staticmethod
    def _serialize_cached_item(
        raw_item: dict[str, Any],
        pending: _AppliedChange | None = None,
    ) -> str:
        cached = dict(raw_item)
        cached.pop(_PENDING_CHANGE_KEY, None)
        if pending is not None:
            cached[_PENDING_CHANGE_KEY] = {
                "target_path": (
                    str(pending.target_path)
                    if pending.target_path is not None
                    else None
                ),
                "target_identity": (
                    list(pending.target_identity)
                    if pending.target_identity is not None
                    else None
                ),
                "content_sha256": pending.content_sha256,
                "absent_paths": [str(path) for path in pending.absent_paths],
            }
        return json.dumps(
            cached,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _pending_change(item_state: ItemState) -> _AppliedChange | None:
        if item_state.item_json is None:
            return None
        cached = json.loads(item_state.item_json)
        if not isinstance(cached, dict):
            raise ValueError("cached item data is not an object")
        if _PENDING_CHANGE_KEY not in cached:
            return None
        marker = cached.get(_PENDING_CHANGE_KEY)
        if not isinstance(marker, dict):
            raise ValueError("pending file receipt is not an object")

        target_value = marker.get("target_path")
        identity_value = marker.get("target_identity")
        hash_value = marker.get("content_sha256")
        absent_value = marker.get("absent_paths")
        if target_value is None:
            if identity_value is not None or hash_value is not None:
                raise ValueError("pending absent receipt has target metadata")
            target_path = None
            target_identity = None
            content_sha256 = None
        else:
            if not isinstance(target_value, str) or not target_value:
                raise ValueError("pending target path is invalid")
            if (
                not isinstance(identity_value, list)
                or len(identity_value) != 2
                or any(
                    not isinstance(value, int) or isinstance(value, bool)
                    for value in identity_value
                )
            ):
                raise ValueError("pending target identity is invalid")
            if not isinstance(hash_value, str) or len(hash_value) != 64:
                raise ValueError("pending content hash is invalid")
            target_path = Path(target_value)
            target_identity = identity_value[0], identity_value[1]
            content_sha256 = hash_value
        if not isinstance(absent_value, list) or any(
            not isinstance(value, str) or not value for value in absent_value
        ):
            raise ValueError("pending absent paths are invalid")
        return _AppliedChange(
            zotero_key=item_state.zotero_key,
            target_path=target_path,
            target_identity=target_identity,
            content_sha256=content_sha256,
            absent_paths=tuple(Path(value) for value in absent_value),
        )

    def _pending_changes(self, result: SyncResult) -> list[_AppliedChange]:
        changes: list[_AppliedChange] = []
        if self.state is None or self._dry_run_fresh_state:
            return changes
        _, stored_root = self.state.get_identity()
        for item_state in self._managed_items():
            try:
                change = self._pending_change(item_state)
                if change is None:
                    continue
                paths = [*change.absent_paths]
                if change.target_path is not None:
                    paths.append(change.target_path)
                for path in paths:
                    self._relative_managed_path(path, stored_root)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                result.errors.append(
                    f"Error reading pending file receipt for item "
                    f"{item_state.zotero_key}: {error}"
                )
                continue
            changes.append(change)
        return changes

    def _make_plan(
        self,
        raw_item: dict[str, Any],
        existing: ItemState | None,
        batch: BatchData,
    ) -> _ItemPlan | None:
        item = self._parse_item(raw_item)
        if item is None:
            return None
        return _ItemPlan(
            raw_item=raw_item,
            item=item,
            existing=existing,
            annotations=batch.annotations_by_item.get(item.key, []),
            child_signature=self._child_signature(batch, item.key),
            target_path=self.files.get_file_path(item.citation_key),
        )

    def _active_items(self) -> list[ItemState]:
        if self._dry_run_fresh_state:
            return []
        return self.state.get_active_items() if self.state is not None else []

    def _managed_items(self) -> list[ItemState]:
        if self._dry_run_fresh_state:
            return []
        return self.state.get_managed_items() if self.state is not None else []

    @staticmethod
    def _path_identity(path: Path) -> str:
        absolute = str(path.expanduser().absolute())
        return unicodedata.normalize("NFD", absolute).casefold()

    @staticmethod
    def _path_exists(path: Path) -> bool:
        return os.path.lexists(path)

    @classmethod
    def _target_parent_error(cls, target: Path) -> str | None:
        existing = target.parent
        while not cls._path_exists(existing):
            parent = existing.parent
            if parent == existing:
                break
            existing = parent
        if not existing.is_dir():
            return f"target parent is not a directory: {existing}"
        if not os.access(existing, os.W_OK | os.X_OK):
            return f"target parent is not writable: {existing}"
        try:
            name_max = os.pathconf(existing, "PC_NAME_MAX")
        except (OSError, ValueError):
            name_max = 255
        if len(target.name.encode("utf-8")) > name_max:
            return f"target filename is too long: {target.name}"
        return None

    @staticmethod
    def _source_parent_error(source: Path) -> str | None:
        if not os.access(source.parent, os.W_OK | os.X_OK):
            return f"stored file parent is not writable: {source.parent}"
        return None

    def _preflight_layout(self, result: SyncResult) -> bool:
        base = self.files.base_dir
        if self._path_exists(base) and not base.is_dir():
            result.errors.append(f"Output path is not a directory: {base}")
            return False
        if target_error := self._target_parent_error(base / "placeholder.md"):
            result.errors.append(f"Output path is unavailable: {target_error}")
            return False
        if self.files.deletion_behavior == "move":
            assert self.files.removed_dir is not None
            removed = self.files.removed_dir
            if removed.is_symlink():
                result.errors.append(
                    f"Output removal path must not be a symbolic link: {removed}"
                )
                return False
            if self._path_exists(removed) and not removed.is_dir():
                result.errors.append(
                    f"Output removal path is not a directory: {removed}"
                )
                return False
        return True

    def _layout_identity(self) -> _LayoutIdentity:
        root = self.files.path_identity(self.files.base_dir)
        if root is None or self.files.base_dir.is_symlink():
            raise _OutputRootChangedError(
                "output directory became unavailable during synchronization"
            )
        removed_identity = None
        if self.files.removed_dir is not None:
            if self.files.removed_dir.is_symlink():
                raise _OutputRootChangedError(
                    "output removal directory changed during synchronization"
                )
            removed_identity = self.files.path_identity(self.files.removed_dir)
            if removed_identity is None:
                raise _OutputRootChangedError(
                    "output removal directory became unavailable during synchronization"
                )
        return _LayoutIdentity(root=root, removed=removed_identity)

    def _prepare_layout(self) -> _LayoutIdentity:
        root, removed = self.files.ensure_directories()
        identity = _LayoutIdentity(root=root, removed=removed)
        self._require_layout_identity(identity)
        return identity

    def _require_applied_changes(
        self,
        changes: list[_AppliedChange],
        layout_identity: _LayoutIdentity,
    ) -> None:
        def require_layout() -> None:
            self._require_layout_identity(layout_identity)

        require_layout()
        for change in changes:
            try:
                if change.target_path is not None:
                    assert change.target_identity is not None
                    assert change.content_sha256 is not None
                    self.files.verify_path(
                        change.target_path,
                        change.target_identity,
                        change.content_sha256,
                        guard=require_layout,
                    )
                for path in change.absent_paths:
                    self.files.require_path_absent(path, guard=require_layout)
            except Exception as error:
                raise RuntimeError(f"item {change.zotero_key}: {error}") from error
        require_layout()

    def _validate_pending_changes(
        self,
        changes: list[_AppliedChange],
        result: SyncResult,
    ) -> bool:
        if not changes:
            return True
        assert self.state is not None
        _, stored_root = self.state.get_identity()
        target_root = self.files.base_dir.expanduser().resolve()
        if target_root != stored_root:
            result.errors.append(
                "Pending file verification must be resolved before changing the "
                "output directory"
            )
            return False
        try:
            self._require_applied_changes(changes, self._layout_identity())
        except Exception as error:
            result.errors.append(f"Error verifying pending sync change: {error}")
            return False
        return True

    def _clear_pending_changes(
        self,
        changes: list[_AppliedChange],
        result: SyncResult,
    ) -> bool:
        if not changes or self.dry_run:
            return True
        assert self.state is not None
        try:
            with self.state.transaction():
                for change in changes:
                    stored_item = self.state.get_item_state(change.zotero_key)
                    if stored_item is None or stored_item.item_json is None:
                        raise RuntimeError(
                            f"pending item state is unavailable: {change.zotero_key}"
                        )
                    self.state.upsert_item(
                        stored_item,
                        item_json=self._serialize_cached_item(
                            self._cached_raw_item(stored_item.item_json)
                        ),
                    )
        except Exception as error:
            result.errors.append(f"Error clearing pending file receipts: {error}")
            return False
        return True

    def _require_layout_identity(self, expected: _LayoutIdentity) -> None:
        if self.files.base_dir.is_symlink() or not self.files.path_matches(
            self.files.base_dir,
            expected.root,
        ):
            raise _OutputRootChangedError(
                "output directory changed during synchronization"
            )
        if expected.removed is not None:
            assert self.files.removed_dir is not None
            if self.files.removed_dir.is_symlink() or not self.files.path_matches(
                self.files.removed_dir,
                expected.removed,
            ):
                raise _OutputRootChangedError(
                    "output removal directory changed during synchronization"
                )

    @staticmethod
    def _managed_existing(
        managed_by_key: dict[str, ItemState], key: str
    ) -> ItemState | None:
        existing = managed_by_key.get(key)
        if existing is not None and not existing.file_path:
            return None
        return existing

    @staticmethod
    def _relative_managed_path(path: Path, root: Path) -> Path:
        if not path.is_absolute():
            raise ValueError
        return path.resolve(strict=False).relative_to(root.resolve(strict=False))

    def _validate_managed_notes(self, result: SyncResult) -> bool:
        if self.state is None or self._dry_run_fresh_state:
            return True
        _, stored_root = self.state.get_identity()
        valid = True
        for item_state in self.state.get_managed_items():
            if not item_state.file_path:
                continue
            path = Path(item_state.file_path)
            try:
                self._relative_managed_path(path, stored_root)
            except ValueError:
                result.errors.append(
                    f"Managed item {item_state.zotero_key} is outside the output root: "
                    f"{path}"
                )
                valid = False
                continue
            if path.is_symlink() or not path.is_file():
                result.errors.append(
                    f"Error syncing item {item_state.zotero_key}: "
                    f"stored file does not exist: {path}"
                )
                valid = False
        return valid

    @staticmethod
    def _deleted_item_keys(deleted: object) -> set[str]:
        if not isinstance(deleted, dict):
            raise ValueError("Malformed deleted response: expected an object")
        items = deleted.get("items")
        if not isinstance(items, list):
            raise ValueError("Malformed deleted response: deleted items is not a list")
        if any(not isinstance(item, str) or not item for item in items):
            raise ValueError(
                "Malformed deleted response: deleted items contains an invalid key"
            )
        return set(items)

    def _reconcile_output_root(self, result: SyncResult) -> bool:
        if self.state is None or self._dry_run_fresh_state:
            return True
        _, stored_root = self.state.get_identity()
        target_root = self.files.base_dir.expanduser().resolve()
        if stored_root == target_root:
            return True

        moves: list[tuple[ItemState, Path, Path, FileIdentity, bytes]] = []
        seen_targets: set[str] = set()
        for item_state in self.state.get_managed_items():
            if item_state.sync_status == "removed" and not item_state.file_path:
                continue
            source = Path(item_state.file_path)
            try:
                relative_path = self._relative_managed_path(source, stored_root)
            except ValueError:
                result.errors.append(
                    f"Error moving output item {item_state.zotero_key}: "
                    f"stored path is outside the output root: {source}"
                )
                continue
            target = target_root / relative_path
            if source == target:
                continue
            if source.is_symlink() or not source.is_file():
                result.errors.append(
                    f"Error moving output item {item_state.zotero_key}: "
                    f"stored file does not exist: {source}"
                )
                continue
            try:
                source_content, source_identity = self.files.read_path_with_identity(
                    source
                )
            except (OSError, UnicodeError) as error:
                result.errors.append(
                    f"Error moving output item {item_state.zotero_key}: {error}"
                )
                continue
            if source_content is None or source_identity is None:
                result.errors.append(
                    f"Error moving output item {item_state.zotero_key}: "
                    f"stored file does not exist: {source}"
                )
                continue
            source_bytes = source_content.encode("utf-8")
            if source_error := self._source_parent_error(source):
                result.errors.append(
                    f"Error moving output item {item_state.zotero_key}: {source_error}"
                )
                continue
            target_identity = self._path_identity(target)
            if target_identity in seen_targets or self._path_exists(target):
                result.errors.append(
                    f"Error moving output item {item_state.zotero_key}: "
                    f"target already exists: {target}"
                )
                continue
            if target_error := self._target_parent_error(target):
                result.errors.append(
                    f"Error moving output item {item_state.zotero_key}: {target_error}"
                )
                continue
            seen_targets.add(target_identity)
            moves.append((item_state, source, target, source_identity, source_bytes))

        if result.errors:
            return False

        source_parent_identities: dict[Path, FileIdentity] = {}
        for item_state, source, _, _, _ in moves:
            source_parent = source.parent
            source_parent_identity = self.files.path_identity(source_parent)
            if source_parent.is_symlink() or source_parent_identity is None:
                result.errors.append(
                    f"Error moving output item {item_state.zotero_key}: "
                    f"stored file parent changed: {source_parent}"
                )
                continue
            source_parent_identities[source_parent] = source_parent_identity
        if result.errors:
            return False
        if not self.dry_run:
            for source_parent in source_parent_identities:
                try:
                    self.files.require_atomic_mutations(source_parent)
                except Exception as error:
                    result.errors.append(
                        f"Source output filesystem cannot be mutated safely: {error}"
                    )
                    return False
        if self.dry_run:
            result.output_items_moved += len(moves)
            return True

        assert self.state is not None
        source_root_identity = self.files.path_identity(stored_root)
        target_layout_identity = self._prepare_layout()

        def require_move_layout() -> None:
            if (
                source_root_identity is None
                or stored_root.is_symlink()
                or not self.files.path_matches(stored_root, source_root_identity)
            ):
                raise _OutputRootChangedError(
                    "source output directory changed during synchronization"
                )
            for source_parent, identity in source_parent_identities.items():
                if source_parent.is_symlink() or not self.files.path_matches(
                    source_parent,
                    identity,
                ):
                    raise _OutputRootChangedError(
                        "source output directory changed during synchronization"
                    )
            self._require_layout_identity(target_layout_identity)

        operations: list[tuple[Path, Path, PathOperation]] = []
        try:
            with self.state.transaction():
                for item_state, source, target, source_identity, source_bytes in moves:
                    self.files.ensure_parent_directory(target)
                    operation = PathOperation()
                    operations.append((source, target, operation))
                    self.files.move_path(
                        source,
                        target,
                        operation=operation,
                        guard=require_move_layout,
                        expected_source_identity=source_identity,
                        expected_source_bytes=source_bytes,
                    )
                    self.state.upsert_item(
                        replace(
                            item_state,
                            file_path=str(target),
                            last_synced_at=datetime.now(),
                        )
                    )
                self.state.update_output_root(target_root)
        except BaseException as error:
            if self._output_state_matches(moves, target_root):
                raise
            rollback_errors = self._roll_back_moves(operations, require_move_layout)
            if not isinstance(error, Exception):
                if rollback_errors:
                    raise RuntimeError(
                        f"{error}; output rollback failed: {'; '.join(rollback_errors)}"
                    ) from error
                raise
            message = f"Error moving output directory: {error}"
            if rollback_errors:
                message += f"; rollback failed: {'; '.join(rollback_errors)}"
            result.errors.append(message)
            return False

        result.output_items_moved += len(moves)
        return True

    def full_sync(self, show_progress: bool = True) -> SyncResult:
        """Fetch the complete library and reconcile every managed note."""
        result = SyncResult(dry_run=self.dry_run)
        pending_changes = self._pending_changes(result)
        if result.errors or not self._validate_pending_changes(
            pending_changes,
            result,
        ):
            return result
        if not self._reconcile_output_root(result):
            return result
        if not self._preflight_layout(result) or not self._validate_managed_notes(
            result
        ):
            return result

        current_version, validated_items, batch = self._stable_full_snapshot(
            show_progress
        )
        active_by_key = {item.zotero_key: item for item in self._active_items()}
        managed_by_key = {item.zotero_key: item for item in self._managed_items()}
        present_keys: set[str] = set()
        plans: list[_ItemPlan] = []
        keyless_updates: list[tuple[ItemState, dict[str, Any]]] = []

        for key, validated in validated_items:
            result.total_items_processed += 1
            if self._is_trashed(validated):
                continue
            present_keys.add(key)
            plan = self._make_plan(
                validated,
                self._managed_existing(managed_by_key, key),
                batch,
            )
            if plan is None:
                result.items_skipped += 1
                result.missing_citation_keys.append(key)
                if existing := active_by_key.get(key):
                    keyless_updates.append((existing, validated))
                continue
            plans.append(plan)

        removals = [
            item_state
            for key, item_state in active_by_key.items()
            if key not in present_keys
        ]
        layout_identity, applied_items = self._reconcile(
            plans,
            removals,
            result,
            show_progress,
        )
        self._checkpoint(
            current_version,
            result,
            full=True,
            layout_identity=layout_identity,
            pending_changes=pending_changes,
            applied_changes=applied_items,
            keyless_updates=keyless_updates,
        )
        return result

    def incremental_sync(self, show_progress: bool = True) -> SyncResult:
        """Reconcile top-level and child changes since the last checkpoint."""
        if self.state is None or self._dry_run_fresh_state:
            return self.full_sync(show_progress=show_progress)

        result = SyncResult(dry_run=self.dry_run)
        pending_changes = self._pending_changes(result)
        if result.errors or not self._validate_pending_changes(
            pending_changes,
            result,
        ):
            return result
        if not self._reconcile_output_root(result):
            return result
        if not self._preflight_layout(result) or not self._validate_managed_notes(
            result
        ):
            return result

        last_version = self.state.get_last_library_version()
        if last_version is None:
            return self.full_sync(show_progress=show_progress)

        current_hash = self.renderer.get_template_hash()
        current_path = self.renderer.get_template_path_identifier()
        template_changed = TemplateChangeDetector.has_template_changed(
            current_hash,
            current_path,
            self.state.get_template_version(),
            RENDER_CONTRACT_VERSION,
        )
        snapshot = self._stable_incremental_snapshot(
            last_version,
            template_changed,
            show_progress,
        )
        if snapshot is None:
            self._clear_pending_changes(pending_changes, result)
            return result
        current_version, modified_items, permanently_deleted_keys, batch = snapshot
        active_by_key = {item.zotero_key: item for item in self._active_items()}
        managed_by_key = {item.zotero_key: item for item in self._managed_items()}
        raw_by_key: dict[str, dict[str, Any]] = {}
        keyless_keys: set[str] = set()
        trashed_keys: set[str] = set()
        keyless_updates: list[tuple[ItemState, dict[str, Any]]] = []

        for key, validated in modified_items:
            if self._is_trashed(validated):
                trashed_keys.add(key)
                continue
            parsed = self._parse_item(validated)
            if parsed is None:
                result.total_items_processed += 1
                result.items_skipped += 1
                result.missing_citation_keys.append(key)
                keyless_keys.add(key)
                if existing := active_by_key.get(key):
                    keyless_updates.append((existing, validated))
                continue
            raw_by_key[key] = validated

        deleted_keys = (permanently_deleted_keys | trashed_keys) & active_by_key.keys()

        plans: list[_ItemPlan] = []
        candidate_keys = set(raw_by_key)
        for key, item_state in active_by_key.items():
            if key in deleted_keys or key in keyless_keys:
                continue
            signature_changed = item_state.child_signature != self._child_signature(
                batch, key
            )
            if template_changed or signature_changed:
                candidate_keys.add(key)

        for key in sorted(candidate_keys):
            existing = self._managed_existing(managed_by_key, key)
            candidate_raw = raw_by_key.get(key)
            if candidate_raw is None:
                if existing is None or existing.item_json is None:
                    result.errors.append(
                        f"Error reconciling item {key}: cached item data is unavailable"
                    )
                    continue
                try:
                    cached = self._cached_raw_item(existing.item_json)
                except (json.JSONDecodeError, TypeError, ValueError) as error:
                    result.errors.append(
                        f"Error reconciling item {key}: invalid cached item data: {error}"
                    )
                    continue
                _, candidate_raw = self._validate_top_level_item(cached)

            plan = self._make_plan(candidate_raw, existing, batch)
            if plan is None:
                result.total_items_processed += 1
                result.items_skipped += 1
                if key not in result.missing_citation_keys:
                    result.missing_citation_keys.append(key)
                continue
            if (
                existing is not None
                and existing.sync_status == "active"
                and not template_changed
                and existing.zotero_version == plan.item.version
                and existing.child_signature == plan.child_signature
                and existing.citation_key == plan.item.citation_key
            ):
                continue
            result.total_items_processed += 1
            plans.append(plan)

        removals = [active_by_key[key] for key in sorted(deleted_keys)]
        layout_identity, applied_items = self._reconcile(
            plans,
            removals,
            result,
            show_progress,
        )
        self._checkpoint(
            current_version,
            result,
            full=False,
            layout_identity=layout_identity,
            pending_changes=pending_changes,
            applied_changes=applied_items,
            keyless_updates=keyless_updates,
        )
        return result

    def _reconcile(
        self,
        plans: list[_ItemPlan],
        removals: list[ItemState],
        result: SyncResult,
        show_progress: bool,
    ) -> tuple[_LayoutIdentity | None, list[_AppliedChange]]:
        if not self._preflight_layout(result):
            return None, []
        valid_plans, collided_keys = self._preflight_items(plans, result)
        rendered_plans = self._render_items(valid_plans, result)
        removal_plans = self._preflight_removals(
            [
                removal
                for removal in removals
                if removal.zotero_key not in collided_keys
            ],
            result,
        )

        if self.dry_run:
            for plan in rendered_plans:
                self._record_item_result(plan, result)
            for removal in removal_plans:
                self._record_removal_result(removal, result)
            return None, []

        layout_identity = self._prepare_layout()
        mutation_parents = {plan.target_path.parent for plan in rendered_plans} | {
            Path(plan.existing.file_path).parent
            for plan in rendered_plans
            if plan.existing is not None
        }
        mutation_parents.update(plan.source_path.parent for plan in removal_plans)
        mutation_parents.update(
            plan.target_path.parent
            for plan in removal_plans
            if plan.target_path is not None
        )
        for parent in mutation_parents:
            self.files.require_atomic_mutations(parent)
        applied_items: list[_AppliedChange] = []

        def apply_changes(bar: Any | None = None) -> None:
            for plan in rendered_plans:
                try:
                    applied = self._execute_item(plan, layout_identity)
                except Exception as error:
                    result.errors.append(f"Error syncing item {plan.item.key}: {error}")
                else:
                    applied_items.append(applied)
                    self._record_item_result(plan, result)
                if bar is not None:
                    bar()
            for removal in removal_plans:
                try:
                    applied = self._execute_removal(removal, layout_identity)
                except Exception as error:
                    result.errors.append(
                        f"Error removing item {removal.item_state.zotero_key}: {error}"
                    )
                else:
                    applied_items.append(applied)
                    self._record_removal_result(removal, result)
                if bar is not None:
                    bar()

        action_count = len(rendered_plans) + len(removal_plans)
        if show_progress and action_count:
            with alive_bar(
                action_count,
                title="Syncing items",
                monitor=False,
                stats=False,
                enrich_print=False,
            ) as bar:
                apply_changes(bar)
        else:
            apply_changes()
        return layout_identity, applied_items

    def _preflight_items(
        self, plans: list[_ItemPlan], result: SyncResult
    ) -> tuple[list[_ItemPlan], set[str]]:
        plans_by_target: dict[str, list[_ItemPlan]] = {}
        for plan in plans:
            identity = self._path_identity(plan.target_path)
            plans_by_target.setdefault(identity, []).append(plan)

        collided_keys: set[str] = set()
        for target_plans in plans_by_target.values():
            if len(target_plans) < 2:
                continue
            for plan in target_plans:
                collided_keys.add(plan.item.key)
                result.target_collisions += 1
                result.errors.append(
                    f"Target collision for item {plan.item.key}: {plan.target_path}"
                )

        owners = {
            self._path_identity(Path(item.file_path)): item.zotero_key
            for item in self._active_items()
        }
        managed_collisions: dict[tuple[str, str], tuple[_ItemPlan, str]] = {}
        for plan in plans:
            target_identity = self._path_identity(plan.target_path)
            owner = owners.get(target_identity)
            if owner is None or owner == plan.item.key:
                continue
            target_keys = {item.item.key for item in plans_by_target[target_identity]}
            if owner in target_keys and len(target_keys) > 1:
                continue
            participants = plan.item.key, owner
            pair = min(participants), max(participants)
            managed_collisions.setdefault(pair, (plan, owner))

        for pair, (plan, owner) in sorted(managed_collisions.items()):
            result.target_collisions += len(set(pair) - collided_keys)
            collided_keys.update(pair)
            result.errors.extend(
                [
                    f"Target collision for item {plan.item.key}: {plan.target_path} "
                    f"is managed by {owner}",
                    f"Target collision for item {owner}: {plan.target_path} "
                    f"is targeted by {plan.item.key}",
                ]
            )

        valid: list[_ItemPlan] = []
        for plan in plans:
            if plan.item.key in collided_keys:
                continue
            target_identity = self._path_identity(plan.target_path)
            own_path = (
                Path(plan.existing.file_path) if plan.existing is not None else None
            )
            own_identity = (
                self._path_identity(own_path) if own_path is not None else None
            )
            if self._path_exists(plan.target_path) and own_identity != target_identity:
                result.target_collisions += 1
                result.errors.append(
                    f"Target collision for item {plan.item.key}: "
                    f"{plan.target_path} already exists"
                )
                continue
            if plan.existing is not None:
                source = Path(plan.existing.file_path)
                if not source.is_file():
                    result.errors.append(
                        f"Error syncing item {plan.item.key}: "
                        f"stored file does not exist: {source}"
                    )
                    continue
                if source_error := self._source_parent_error(source):
                    result.errors.append(
                        f"Error syncing item {plan.item.key}: {source_error}"
                    )
                    continue
            if target_error := self._target_parent_error(plan.target_path):
                result.errors.append(
                    f"Error syncing item {plan.item.key}: {target_error}"
                )
                continue
            valid.append(plan)
        return valid, collided_keys

    def _render_items(
        self, plans: list[_ItemPlan], result: SyncResult
    ) -> list[_ItemPlan]:
        rendered: list[_ItemPlan] = []
        for plan in plans:
            try:
                if plan.existing is not None:
                    plan.existing_content, plan.source_identity = (
                        self.files.read_path_with_identity(plan.existing.file_path)
                    )
                    if plan.existing_content is None or plan.source_identity is None:
                        raise FileNotFoundError(
                            f"stored file does not exist: {plan.existing.file_path}"
                        )
                preserved_notes = (
                    self.renderer.extract_notes_section(plan.existing_content)
                    if plan.existing_content is not None
                    else None
                )
                plan.markdown = self.renderer.render_item(
                    item=plan.item,
                    annotations=plan.annotations,
                    library_id=self.library_id,
                    preserved_notes=preserved_notes,
                )
            except Exception as error:
                result.errors.append(f"Error rendering item {plan.item.key}: {error}")
                continue
            rendered.append(plan)
        return rendered

    def _preflight_removals(
        self, removals: list[ItemState], result: SyncResult
    ) -> list[_RemovalPlan]:
        plans: list[_RemovalPlan] = []
        targets: set[str] = set()
        for item_state in removals:
            source = Path(item_state.file_path)
            try:
                content, source_identity = self.files.read_path_with_identity(source)
            except Exception as error:
                result.errors.append(
                    f"Error removing item {item_state.zotero_key}: {error}"
                )
                continue
            if content is None or source_identity is None:
                result.errors.append(
                    f"Error removing item {item_state.zotero_key}: "
                    f"stored file does not exist: {source}"
                )
                continue
            if source.is_symlink():
                result.errors.append(
                    f"Error removing item {item_state.zotero_key}: "
                    f"stored path is a symbolic link: {source}"
                )
                continue
            if source_error := self._source_parent_error(source):
                result.errors.append(
                    f"Error removing item {item_state.zotero_key}: {source_error}"
                )
                continue

            target: Path | None = None
            if self.files.deletion_behavior == "move":
                assert self.files.removed_dir is not None
                target = self.files.removed_dir / source.name
                if target.parent.resolve() != self.files.removed_dir.resolve():
                    result.errors.append(
                        f"Error removing item {item_state.zotero_key}: "
                        f"target escapes the removal directory: {target}"
                    )
                    continue
                target_identity = self._path_identity(target)
                if target_identity in targets or self._path_exists(target):
                    result.errors.append(
                        f"Error removing item {item_state.zotero_key}: "
                        f"target already exists: {target}"
                    )
                    continue
                if target_error := self._target_parent_error(target):
                    result.errors.append(
                        f"Error removing item {item_state.zotero_key}: {target_error}"
                    )
                    continue
                targets.add(target_identity)
            plans.append(
                _RemovalPlan(item_state, source, target, content, source_identity)
            )
        return plans

    def _execute_item(
        self,
        plan: _ItemPlan,
        layout_identity: _LayoutIdentity,
    ) -> _AppliedChange:
        assert self.state is not None
        assert plan.markdown is not None
        source = Path(plan.existing.file_path) if plan.existing is not None else None
        expected_bytes = (
            plan.existing_content.encode("utf-8")
            if plan.existing_content is not None
            else None
        )
        vacated_path = (
            source
            if source is not None
            and plan.moves_path
            and not self.files.paths_alias(source, plan.target_path)
            else None
        )

        def require_layout() -> None:
            self._require_layout_identity(layout_identity)

        applied_at = datetime.now()
        plan.applied_at = applied_at
        try:
            with self.state.transaction():
                require_layout()
                if source is not None and not source.is_file():
                    raise FileNotFoundError(f"stored file does not exist: {source}")
                if plan.moves_path:
                    assert source is not None
                    self.files.rename_path(
                        source,
                        plan.target_path,
                        operation=plan.move_operation,
                        guard=require_layout,
                        expected_source_identity=plan.source_identity,
                        expected_source_bytes=expected_bytes,
                    )
                self.files.write_path(
                    plan.target_path,
                    plan.markdown,
                    overwrite=plan.existing is not None,
                    operation=plan.write_operation,
                    guard=require_layout,
                    expected_target_identity=(
                        plan.move_operation.target_identity
                        if plan.moves_path
                        else plan.source_identity
                    ),
                    expected_target_bytes=expected_bytes,
                )
                require_layout()
                assert plan.write_operation.target_identity is not None
                applied = _AppliedChange(
                    zotero_key=plan.item.key,
                    target_path=plan.target_path,
                    target_identity=plan.write_operation.target_identity,
                    content_sha256=hashlib.sha256(
                        plan.markdown.encode("utf-8")
                    ).hexdigest(),
                    absent_paths=(vacated_path,) if vacated_path is not None else (),
                )
                self.state.upsert_item(
                    ItemState(
                        zotero_key=plan.item.key,
                        citation_key=plan.item.citation_key,
                        item_type=plan.item.item_type,
                        zotero_version=plan.item.version,
                        file_path=str(plan.target_path),
                        last_synced_at=applied_at,
                        sync_status="active",
                        child_signature=plan.child_signature,
                        annotation_count=len(plan.annotations),
                    ),
                    item_json=self._serialize_cached_item(
                        plan.raw_item,
                        applied,
                    ),
                )
                require_layout()
        except BaseException as error:
            if self._item_state_matches(plan):
                raise
            rollback_error = self._roll_back_item(
                plan,
                source,
                require_layout,
            )
            if rollback_error is not None:
                raise RuntimeError(
                    f"{error}; file rollback failed: {rollback_error}"
                ) from error
            raise
        return applied

    def _roll_back_item(
        self,
        plan: _ItemPlan,
        source: Path | None,
        guard: MutationGuard,
    ) -> BaseException | None:
        if not self.files.guard_passes(guard):
            return None
        try:
            if plan.existing is None:
                if (
                    not plan.write_operation.target_claimed
                    or self.files.path_identity(plan.target_path) is None
                ):
                    return None
                raise RuntimeError(
                    "created note was retained for recovery after state rollback at "
                    f"{plan.target_path}"
                )

            assert source is not None
            assert plan.existing_content is not None
            assert plan.markdown is not None
            if (
                not plan.move_operation.target_claimed
                and not plan.move_operation.source_removed
                and not plan.write_operation.target_claimed
            ):
                return None
            target_text, target_identity = self.files.read_path_with_identity(
                plan.target_path
            )
            target_content = (
                target_text.encode("utf-8") if target_text is not None else None
            )
            target_owned = (
                plan.write_operation.target_claimed
                and target_identity == plan.write_operation.target_identity
                and target_content == plan.markdown.encode("utf-8")
            ) or (
                plan.move_operation.target_claimed
                and target_identity == plan.move_operation.target_identity
                and target_content == plan.existing_content.encode("utf-8")
            )
            source_identity = (
                plan.move_operation.source_identity
                if plan.moves_path
                else plan.write_operation.source_identity
            )
            source_owned = self.files.path_matches(source, source_identity)
            source_missing = self.files.path_identity(source) is None
            case_only_move = plan.moves_path and self._path_identity(
                source
            ) == self._path_identity(plan.target_path)
            if plan.moves_path and target_owned and (source_missing or case_only_move):
                restore_operation = PathOperation()
                self.files.write_path(
                    plan.target_path,
                    plan.existing_content,
                    operation=restore_operation,
                    guard=guard,
                    expected_target_identity=target_identity,
                    expected_target_bytes=target_content,
                )
                self.files.rename_path(
                    plan.target_path,
                    source,
                    guard=guard,
                    expected_source_identity=restore_operation.target_identity,
                    expected_source_bytes=plan.existing_content.encode("utf-8"),
                )
            elif plan.moves_path and target_owned and source_owned:
                if target_identity != source_identity:
                    raise RuntimeError(
                        f"Copied file retained for recovery at {plan.target_path}"
                    )
                self.files.delete_path(
                    plan.target_path,
                    guard=guard,
                    expected_source_identity=target_identity,
                    expected_source_bytes=target_content,
                )
                self.files.write_path(
                    source,
                    plan.existing_content,
                    guard=guard,
                    expected_target_identity=source_identity,
                    expected_target_bytes=plan.existing_content.encode("utf-8"),
                )
            elif not plan.moves_path and target_owned:
                self.files.write_path(
                    source,
                    plan.existing_content,
                    guard=guard,
                    expected_target_identity=target_identity,
                    expected_target_bytes=target_content,
                )
            elif not source_owned:
                raise FileNotFoundError(f"cannot restore managed file: {source}")
        except BaseException as error:
            return error
        return None

    def _item_state_matches(self, plan: _ItemPlan) -> bool:
        assert self.state is not None
        try:
            stored = self.state.get_item_state(plan.item.key)
        except Exception:
            return False
        return (
            stored is not None
            and stored.sync_status == "active"
            and stored.citation_key == plan.item.citation_key
            and stored.zotero_version == plan.item.version
            and stored.file_path == str(plan.target_path)
            and stored.child_signature == plan.child_signature
            and stored.last_synced_at == plan.applied_at
        )

    def _execute_removal(
        self,
        plan: _RemovalPlan,
        layout_identity: _LayoutIdentity,
    ) -> _AppliedChange:
        assert self.state is not None
        if plan.item_state.item_json is None:
            raise ValueError("cached item data is unavailable")
        raw_item = self._cached_raw_item(plan.item_state.item_json)

        def require_layout() -> None:
            self._require_layout_identity(layout_identity)

        try:
            with self.state.transaction():
                require_layout()
                if not plan.source_path.is_file():
                    raise FileNotFoundError(
                        f"stored file does not exist: {plan.source_path}"
                    )
                if plan.target_path is not None:
                    self.files.move_path(
                        plan.source_path,
                        plan.target_path,
                        operation=plan.operation,
                        guard=require_layout,
                        expected_source_identity=plan.source_identity,
                        expected_source_bytes=plan.existing_content.encode("utf-8"),
                    )
                    stored_path = plan.target_path
                    deleted = False
                else:
                    self.files.delete_path(
                        plan.source_path,
                        operation=plan.operation,
                        guard=require_layout,
                        expected_source_identity=plan.source_identity,
                        expected_source_bytes=plan.existing_content.encode("utf-8"),
                    )
                    stored_path = Path()
                    deleted = True
                require_layout()
                applied = _AppliedChange(
                    zotero_key=plan.item_state.zotero_key,
                    target_path=None if deleted else stored_path,
                    target_identity=(
                        None if deleted else plan.operation.target_identity
                    ),
                    content_sha256=(
                        None
                        if deleted
                        else hashlib.sha256(
                            plan.existing_content.encode("utf-8")
                        ).hexdigest()
                    ),
                    absent_paths=(plan.source_path,),
                )
                if not deleted:
                    assert applied.target_identity is not None
                self.state.upsert_item(
                    replace(
                        plan.item_state,
                        file_path="" if deleted else str(stored_path),
                        last_synced_at=datetime.now(),
                        sync_status="removed",
                    ),
                    item_json=self._serialize_cached_item(raw_item, applied),
                )
                require_layout()
        except BaseException as error:
            if self._removal_state_matches(plan):
                raise
            if not self.files.guard_passes(require_layout):
                raise
            try:
                source_text, source_identity = self.files.read_path_with_identity(
                    plan.source_path
                )
                source_content = (
                    source_text.encode("utf-8") if source_text is not None else None
                )
                source_owned = (
                    source_identity == plan.operation.source_identity
                    and source_content == plan.existing_content.encode("utf-8")
                )
                source_missing = source_identity is None
                target_text, target_identity = (
                    self.files.read_path_with_identity(plan.target_path)
                    if plan.target_path is not None
                    else (None, None)
                )
                target_content = (
                    target_text.encode("utf-8") if target_text is not None else None
                )
                target_owned = (
                    plan.target_path is not None
                    and plan.operation.target_claimed
                    and target_identity == plan.operation.target_identity
                    and target_content == plan.existing_content.encode("utf-8")
                )
                if plan.target_path is not None and target_owned and source_missing:
                    self.files.rename_path(
                        plan.target_path,
                        plan.source_path,
                        guard=require_layout,
                        expected_source_identity=target_identity,
                        expected_source_bytes=target_content,
                    )
                elif plan.target_path is not None and target_owned and source_owned:
                    if target_identity != plan.operation.source_identity:
                        raise RuntimeError(
                            f"Copied file retained for recovery at {plan.target_path}"
                        )
                    self.files.delete_path(
                        plan.target_path,
                        guard=require_layout,
                        expected_source_identity=target_identity,
                        expected_source_bytes=target_content,
                    )
                elif (
                    plan.target_path is None
                    and plan.operation.source_removed
                    and source_missing
                ):
                    self.files.write_path(
                        plan.source_path,
                        plan.existing_content,
                        overwrite=False,
                        guard=require_layout,
                        mode=plan.operation.source_mode,
                    )
            except BaseException as rollback_error:
                raise RuntimeError(
                    f"{error}; file rollback failed: {rollback_error}"
                ) from error
            raise
        return applied

    def _removal_state_matches(self, plan: _RemovalPlan) -> bool:
        assert self.state is not None
        try:
            stored = self.state.get_item_state(plan.item_state.zotero_key)
        except Exception:
            return False
        expected_path = str(plan.target_path) if plan.target_path is not None else ""
        return (
            stored is not None
            and stored.sync_status == "removed"
            and stored.file_path == expected_path
        )

    @staticmethod
    def _record_item_result(plan: _ItemPlan, result: SyncResult) -> None:
        if plan.existing is None:
            result.items_created += 1
        else:
            result.items_updated += 1
        if plan.renamed:
            result.items_renamed += 1
        result.annotations_synced += len(plan.annotations)

    def _record_removal_result(self, plan: _RemovalPlan, result: SyncResult) -> None:
        result.items_removed += 1
        if self.files.deletion_behavior == "delete":
            result.items_deleted += 1

    def _checkpoint(
        self,
        current_version: int,
        result: SyncResult,
        *,
        full: bool,
        layout_identity: _LayoutIdentity | None,
        pending_changes: list[_AppliedChange],
        applied_changes: list[_AppliedChange],
        keyless_updates: list[tuple[ItemState, dict[str, Any]]],
    ) -> None:
        if self.dry_run or result.errors:
            return
        assert self.state is not None
        current_hash = self.renderer.get_template_hash()
        current_path = self.renderer.get_template_path_identifier()
        if layout_identity is None:
            result.errors.append(
                "Error recording sync checkpoint: output layout was not prepared"
            )
            return
        changes_by_key = {change.zotero_key: change for change in pending_changes}
        changes_by_key.update({change.zotero_key: change for change in applied_changes})
        changes = list(changes_by_key.values())
        previous_checkpoint = self.state.get_checkpoint()
        try:
            with self.state.transaction():
                self._require_applied_changes(changes, layout_identity)
                for item_state, raw_item in keyless_updates:
                    self.state.upsert_item(
                        item_state,
                        item_json=self._serialize_cached_item(
                            raw_item,
                            changes_by_key.get(item_state.zotero_key),
                        ),
                    )
                if full:
                    self.state.record_full_sync(current_version)
                else:
                    self.state.update_library_version(current_version)
                self.state.record_template_version(
                    current_hash,
                    current_path,
                    RENDER_CONTRACT_VERSION,
                )
        except Exception as error:
            result.errors.append(f"Error recording sync checkpoint: {error}")
            return

        try:
            self._require_applied_changes(changes, layout_identity)
        except Exception as error:
            try:
                with self.state.transaction():
                    self.state.restore_checkpoint(previous_checkpoint)
            except Exception as restore_error:
                result.errors.append(
                    "Error confirming sync checkpoint: "
                    f"{error}; checkpoint restore failed: {restore_error}"
                )
            else:
                result.errors.append(f"Error confirming sync checkpoint: {error}")
            return

        if self._clear_pending_changes(changes, result):
            return
        try:
            with self.state.transaction():
                self.state.restore_checkpoint(previous_checkpoint)
        except Exception as restore_error:
            result.errors.append(
                "Error restoring sync checkpoint after pending file receipt cleanup "
                f"failure: {restore_error}"
            )

    def _roll_back_moves(
        self,
        completed: list[tuple[Path, Path, PathOperation]],
        guard: MutationGuard,
    ) -> list[str]:
        errors: list[str] = []
        if not self.files.guard_passes(guard):
            return errors
        for source, target, operation in reversed(completed):
            try:
                if not operation.target_claimed or not self.files.path_matches(
                    target,
                    operation.target_identity,
                ):
                    continue
                source_owned = self.files.path_matches(
                    source,
                    operation.source_identity,
                )
                if (
                    operation.source_removed
                    and self.files.path_identity(source) is None
                ):
                    self.files.rename_path(target, source, guard=guard)
                elif source_owned:
                    if operation.target_identity != operation.source_identity:
                        errors.append(f"copied file retained for recovery at {target}")
                        continue
                    self.files.delete_path(target, guard=guard)
                else:
                    errors.append(f"cannot safely restore moved file: {source}")
            except BaseException as error:
                errors.append(str(error))
        return errors

    def _output_state_matches(
        self,
        moves: list[tuple[ItemState, Path, Path, FileIdentity, bytes]],
        target_root: Path,
    ) -> bool:
        assert self.state is not None
        try:
            _, stored_root = self.state.get_identity()
            if stored_root != target_root:
                return False
            return all(
                (stored := self.state.get_item_state(item_state.zotero_key)) is not None
                and stored.file_path == str(target)
                for item_state, _, target, _, _ in moves
            )
        except Exception:
            return False

    def get_sync_status(self) -> dict[str, int | str | None]:
        """Return current state statistics."""
        if self.state is None:
            return {
                "active_items": 0,
                "removed_items": 0,
                "total_annotations": 0,
                "last_full_sync": None,
                "last_incremental_sync": None,
                "last_library_version": None,
            }
        return self.state.get_sync_stats()
