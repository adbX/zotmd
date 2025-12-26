"""Main sync orchestrator for Zotero-Obsidian synchronization."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List
from alive_progress import alive_bar

from .zotero_client import ZoteroClient
from .state_manager import StateManager, ItemState
from ..models.item import ZoteroItem
from ..models.annotation import Annotation
from ..templates.renderer import TemplateRenderer
from ..file_ops.file_manager import FileManager


logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Results from a sync operation."""

    total_items_processed: int = 0
    items_created: int = 0
    items_updated: int = 0
    items_removed: int = 0
    items_skipped: int = 0
    annotations_synced: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class SyncEngine:
    """Main orchestrator for Zotero-Obsidian synchronization."""

    def __init__(
        self,
        zotero_client: ZoteroClient,
        state_manager: StateManager,
        renderer: TemplateRenderer,
        file_manager: FileManager,
        library_id: str,
    ):
        """
        Initialize sync engine.

        Args:
            zotero_client: Zotero API client
            state_manager: SQLite state manager
            renderer: Template renderer
            file_manager: File manager
            library_id: Zotero library ID
        """
        self.zotero = zotero_client
        self.state = state_manager
        self.renderer = renderer
        self.files = file_manager
        self.library_id = library_id

        logger.info("SyncEngine initialized")

    def full_sync(self, show_progress: bool = True) -> SyncResult:
        """
        Perform full library sync (initial import).

        Args:
            show_progress: Show progress bar

        Returns:
            SyncResult with statistics
        """
        logger.info("Starting full sync")
        result = SyncResult()

        try:
            # Get current library version
            current_version = self.zotero.get_library_version()
            logger.info(f"Current library version: {current_version}")

            # Fetch all items
            logger.info("Fetching all items from Zotero...")
            items = self.zotero.get_all_items()
            logger.info(f"Fetched {len(items)} items")

            # Process items with progress bar
            if show_progress:
                with alive_bar(
                    len(items),
                    title="Syncing items",
                    dual_line=True,
                    enrich_print=False,
                ) as bar:
                    for item_data in items:
                        try:
                            # Update progress bar with full untruncated title
                            title = item_data.get("data", {}).get("title", "Unknown")
                            bar.text = f"-> {title}"

                            self._sync_single_item(item_data, result)
                            bar()
                        except Exception as e:
                            error_msg = f"Error syncing item {item_data.get('key', 'UNKNOWN')}: {e}"
                            logger.error(error_msg)
                            result.errors.append(error_msg)
                            bar()
            else:
                for item_data in items:
                    try:
                        self._sync_single_item(item_data, result)
                    except Exception as e:
                        error_msg = (
                            f"Error syncing item {item_data.get('key', 'UNKNOWN')}: {e}"
                        )
                        logger.error(error_msg)
                        result.errors.append(error_msg)

            # Detect and handle removed items
            removed_count = self._handle_removed_items()
            result.items_removed = removed_count

            # Update sync metadata
            self.state.record_full_sync(current_version)

            logger.info(
                f"Full sync complete: {result.items_created} created, {result.items_updated} updated, {result.items_skipped} skipped"
            )
            return result

        except Exception as e:
            logger.error(f"Full sync failed: {e}")
            raise

    def incremental_sync(self, show_progress: bool = True) -> SyncResult:
        """
        Perform incremental sync (only changes since last sync).

        Args:
            show_progress: Show progress bar

        Returns:
            SyncResult with statistics
        """
        logger.info("Starting incremental sync")
        result = SyncResult()

        try:
            # Get last synced version
            last_version = self.state.get_last_library_version()

            if last_version is None:
                logger.warning("No previous sync found, performing full sync")
                return self.full_sync(show_progress)

            # Get current library version
            current_version = self.zotero.get_library_version()
            logger.info(f"Syncing from version {last_version} to {current_version}")

            if current_version == last_version:
                logger.info("No changes detected")
                return result

            # Check if too many versions behind (>1000 = full sync recommended)
            if current_version - last_version > 1000:
                logger.warning("More than 1000 versions behind, performing full sync")
                return self.full_sync(show_progress)

            # Fetch modified items
            logger.info(f"Fetching items modified since version {last_version}...")
            modified_items = self.zotero.get_items_since_version(last_version)
            logger.info(f"Found {len(modified_items)} modified items")

            # Process modified items
            if show_progress:
                with alive_bar(
                    len(modified_items),
                    title="Syncing changes",
                    dual_line=True,
                    enrich_print=False,
                ) as bar:
                    for item_data in modified_items:
                        try:
                            # Update progress bar with full untruncated title
                            title = item_data.get("data", {}).get("title", "Unknown")
                            bar.text = f"-> {title}"

                            self._sync_single_item(item_data, result)
                            bar()
                        except Exception as e:
                            error_msg = f"Error syncing item {item_data.get('key', 'UNKNOWN')}: {e}"
                            logger.error(error_msg)
                            result.errors.append(error_msg)
                            bar()
            else:
                for item_data in modified_items:
                    try:
                        self._sync_single_item(item_data, result)
                    except Exception as e:
                        error_msg = (
                            f"Error syncing item {item_data.get('key', 'UNKNOWN')}: {e}"
                        )
                        logger.error(error_msg)
                        result.errors.append(error_msg)

            # Check for deleted items
            deleted = self.zotero.get_deleted_items(last_version)
            deleted_item_keys = deleted.get("items", [])

            if deleted_item_keys:
                logger.info(f"Found {len(deleted_item_keys)} deleted items")
                for item_key in deleted_item_keys:
                    self._handle_deleted_item(item_key)
                    result.items_removed += 1

            # Update sync metadata
            self.state.update_library_version(current_version)

            logger.info(
                f"Incremental sync complete: {result.items_updated} updated, {result.items_removed} removed"
            )
            return result

        except Exception as e:
            logger.error(f"Incremental sync failed: {e}")
            raise

    def _sync_single_item(self, item_data: dict, result: SyncResult) -> None:
        """
        Sync a single Zotero item.

        Args:
            item_data: Zotero API item data
            result: SyncResult to update
        """
        result.total_items_processed += 1

        # Parse item
        item = ZoteroItem.from_api_response(item_data, self.library_id)

        if not item:
            # No citation key - skip
            logger.debug(f"Skipping item {item_data.get('key')} - no citation key")
            result.items_skipped += 1
            return

        # Check if item exists in database
        existing_state = self.state.get_item_state(item.key)

        # Always fetch annotations to check for changes
        annotations = self._fetch_annotations(item.key)
        result.annotations_synced += len(annotations)

        # Read existing file once if item exists
        existing_content = None
        is_update = False

        if existing_state:
            # Item exists - check if version or annotations changed
            item_version_changed = existing_state.zotero_version < item.version

            # Read existing file to check annotation count
            existing_content = self.files.read_existing(item.citation_key)
            if existing_content:
                existing_annotations = self.renderer.extract_annotations_section(
                    existing_content
                )
                # Simple heuristic: count annotation markers in existing content
                existing_annot_count = (
                    existing_annotations.count("- <mark class=")
                    if existing_annotations
                    else 0
                )
                new_annot_count = len(annotations)
                annotations_changed = existing_annot_count != new_annot_count
            else:
                annotations_changed = len(annotations) > 0

            # Skip if neither metadata nor annotations changed
            if not item_version_changed and not annotations_changed:
                logger.debug(f"Item {item.key} and annotations unchanged, skipping")
                return

            is_update = True

        # Get PDF attachment key for annotation links
        attachment = self.zotero.get_attachment_for_item(item.key)
        attachment_key = attachment.get("key") if attachment else None

        # Render markdown
        preserved_notes = None
        if is_update and existing_content:
            preserved_notes = self.renderer.extract_notes_section(existing_content)

        markdown = self.renderer.render_item(
            item=item,
            annotations=annotations,
            library_id=self.library_id,
            preserved_notes=preserved_notes,
            attachment_key=attachment_key,
        )

        # Write markdown file
        file_path = self.files.write_markdown(item.citation_key, markdown)

        # Compute content hash
        content_hash = self.files.get_content_hash(item.citation_key)

        # Update database
        item_state = ItemState(
            zotero_key=item.key,
            citation_key=item.citation_key,
            item_type=item.item_type,
            zotero_version=item.version,
            file_path=str(file_path),
            last_synced_at=datetime.now(),
            sync_status="active",
            content_hash=content_hash,
        )
        self.state.upsert_item(item_state)

        # Update sync statistics
        if is_update:
            result.items_updated += 1
            logger.debug(f"Updated item: {item.citation_key}")
        else:
            result.items_created += 1
            logger.debug(f"Created item: {item.citation_key}")

    def _fetch_annotations(self, item_key: str) -> List[Annotation]:
        """
        Fetch and parse annotations for an item.

        Args:
            item_key: Zotero item key

        Returns:
            List of Annotation objects
        """
        try:
            annotation_data = self.zotero.get_annotations_for_item(item_key)
            annotations = [
                Annotation.from_api_response(annot) for annot in annotation_data
            ]
            return annotations

        except Exception as e:
            logger.error(f"Failed to fetch annotations for {item_key}: {e}")
            return []

    def _handle_removed_items(self) -> int:
        """
        Detect and handle items removed from Zotero.

        Returns:
            Number of items moved to removed/
        """
        # Get all item keys from Zotero
        current_items = self.zotero.get_all_items()
        zotero_keys = {item.get("key") for item in current_items}

        # Get all tracked keys from database
        tracked_keys = self.state.get_all_item_keys()

        # Find removed items
        removed_keys = tracked_keys - zotero_keys

        if not removed_keys:
            logger.debug("No removed items detected")
            return 0

        logger.info(f"Found {len(removed_keys)} removed items")

        # Move files and update database
        removed_count = 0
        for item_key in removed_keys:
            moved = self._handle_deleted_item(item_key)
            if moved:
                removed_count += 1

        return removed_count

    def _handle_deleted_item(self, item_key: str) -> bool:
        """
        Handle a deleted Zotero item.

        Args:
            item_key: Zotero item key

        Returns:
            True if successfully handled
        """
        # Get item state from database
        item_state = self.state.get_item_state(item_key)

        if not item_state:
            logger.warning(f"Deleted item {item_key} not found in database")
            return False

        # Handle removed item based on configured behavior
        result_path = self.files.handle_removed_item(item_state.citation_key)

        # Mark as removed in database
        self.state.mark_item_removed(item_key)

        if result_path:
            logger.info(f"Moved removed item to: {result_path}")
        else:
            logger.info(f"Deleted removed item: {item_state.citation_key}")

        return True

    def get_sync_status(self) -> dict:
        """
        Get current sync status and statistics.

        Returns:
            Dictionary with sync status information
        """
        stats = self.state.get_sync_stats()

        return {
            "active_items": stats["active_items"],
            "removed_items": stats["removed_items"],
            "total_annotations": stats["total_annotations"],
            "last_full_sync": stats["last_full_sync"],
            "last_incremental_sync": stats["last_incremental_sync"],
            "last_library_version": stats["last_library_version"],
        }
