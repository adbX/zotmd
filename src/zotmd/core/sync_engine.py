"""Main sync orchestrator for Zotero-Obsidian synchronization."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict
from alive_progress import alive_bar

from .zotero_client import ZoteroClient
from .state_manager import StateManager, ItemState
from .template_manager import TemplateChangeDetector
from ..models.item import ZoteroItem
from ..models.annotation import Annotation
from ..templates.renderer import TemplateRenderer
from ..file_ops.file_manager import FileManager


logger = logging.getLogger(__name__)

# Maximum number of parallel workers for item processing
MAX_WORKERS = 4


@dataclass
class SyncResult:
    """Results from a sync operation (thread-safe)."""

    total_items_processed: int = 0
    items_created: int = 0
    items_updated: int = 0
    items_removed: int = 0
    items_skipped: int = 0
    annotations_synced: int = 0
    errors: List[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def increment_processed(self) -> None:
        """Thread-safe increment of processed count."""
        with self._lock:
            self.total_items_processed += 1

    def increment_created(self) -> None:
        """Thread-safe increment of created count."""
        with self._lock:
            self.items_created += 1

    def increment_updated(self) -> None:
        """Thread-safe increment of updated count."""
        with self._lock:
            self.items_updated += 1

    def increment_skipped(self) -> None:
        """Thread-safe increment of skipped count."""
        with self._lock:
            self.items_skipped += 1

    def add_annotations(self, count: int) -> None:
        """Thread-safe addition of annotation count."""
        with self._lock:
            self.annotations_synced += count

    def add_error(self, error: str) -> None:
        """Thread-safe addition of error message."""
        with self._lock:
            self.errors.append(error)


@dataclass
class BatchData:
    """Pre-fetched data for batch processing."""

    # item_key -> list of Annotation objects
    annotations_by_item: Dict[str, List[Annotation]] = field(default_factory=dict)
    # item_key -> attachment_key (for PDF link)
    attachment_keys: Dict[str, str] = field(default_factory=dict)


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
        self._db_lock = threading.Lock()  # Lock for thread-safe DB writes

        logger.info("SyncEngine initialized")

    def _build_batch_data(self, show_progress: bool = True) -> BatchData:
        """
        Pre-fetch all annotations and attachments in batch.

        This dramatically reduces API calls by fetching everything upfront
        instead of making per-item requests.

        Args:
            show_progress: Show progress spinner during fetch

        Returns:
            BatchData with pre-fetched annotations and attachment mappings
        """
        batch_data = BatchData()

        if show_progress:
            # Use unknown mode (no total) for indeterminate progress
            with alive_bar(
                title="Fetching library data",
                monitor=False,  # Don't show "it/s" for unknown mode
                stats=False,  # Don't show stats
                enrich_print=False,
            ) as bar:
                # Fetch all annotations
                bar.text = "-> annotations..."
                logger.info("Batch fetching all annotations...")
                all_annotations = self.zotero.get_all_annotations()
                logger.info(f"Fetched {len(all_annotations)} annotations in batch")
                bar.text = f"-> fetched {len(all_annotations)} annotations"
                bar()

                # Fetch all attachments
                bar.text = "-> attachments..."
                logger.info("Batch fetching all attachments...")
                all_attachments = self.zotero.get_all_attachments()
                logger.info(f"Fetched {len(all_attachments)} attachments in batch")
                bar.text = f"-> fetched {len(all_attachments)} attachments"
                bar()

                # Build attachment_key -> parent_item_key mapping
                bar.text = "-> building mappings..."
                attachment_to_parent: Dict[str, str] = {}
                for attachment in all_attachments:
                    attachment_key = attachment.get("key")
                    parent_key = attachment.get("data", {}).get("parentItem")
                    content_type = attachment.get("data", {}).get("contentType", "")

                    if attachment_key and parent_key:
                        attachment_to_parent[attachment_key] = parent_key
                        # Track PDF attachment keys for items
                        if "pdf" in content_type.lower():
                            batch_data.attachment_keys[parent_key] = attachment_key

                # Build item_key -> [annotations] mapping
                for annotation_data in all_annotations:
                    annotation = Annotation.from_api_response(annotation_data)
                    # annotation.parent_key is the attachment key
                    parent_item_key = attachment_to_parent.get(annotation.parent_key)

                    if parent_item_key:
                        if parent_item_key not in batch_data.annotations_by_item:
                            batch_data.annotations_by_item[parent_item_key] = []
                        batch_data.annotations_by_item[parent_item_key].append(annotation)

                logger.info(
                    f"Built batch data: {len(batch_data.annotations_by_item)} items with annotations, "
                    f"{len(batch_data.attachment_keys)} items with PDF attachments"
                )
                bar.text = f"-> ready ({len(batch_data.annotations_by_item)} items with annotations)"
                bar()
        else:
            # No progress - existing code
            logger.info("Batch fetching all annotations...")
            all_annotations = self.zotero.get_all_annotations()
            logger.info(f"Fetched {len(all_annotations)} annotations in batch")

            logger.info("Batch fetching all attachments...")
            all_attachments = self.zotero.get_all_attachments()
            logger.info(f"Fetched {len(all_attachments)} attachments in batch")

            # Build attachment_key -> parent_item_key mapping
            attachment_to_parent: Dict[str, str] = {}
            for attachment in all_attachments:
                attachment_key = attachment.get("key")
                parent_key = attachment.get("data", {}).get("parentItem")
                content_type = attachment.get("data", {}).get("contentType", "")

                if attachment_key and parent_key:
                    attachment_to_parent[attachment_key] = parent_key
                    # Track PDF attachment keys for items
                    if "pdf" in content_type.lower():
                        batch_data.attachment_keys[parent_key] = attachment_key

            # Build item_key -> [annotations] mapping
            for annotation_data in all_annotations:
                annotation = Annotation.from_api_response(annotation_data)
                # annotation.parent_key is the attachment key
                parent_item_key = attachment_to_parent.get(annotation.parent_key)

                if parent_item_key:
                    if parent_item_key not in batch_data.annotations_by_item:
                        batch_data.annotations_by_item[parent_item_key] = []
                    batch_data.annotations_by_item[parent_item_key].append(annotation)

            logger.info(
                f"Built batch data: {len(batch_data.annotations_by_item)} items with annotations, "
                f"{len(batch_data.attachment_keys)} items with PDF attachments"
            )

        return batch_data

    def full_sync(self, show_progress: bool = True) -> SyncResult:
        """
        Perform full library sync (initial import).

        Uses batch fetching and parallel processing for performance.

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

            # Batch fetch annotations and attachments (major optimization)
            batch_data = self._build_batch_data(show_progress=show_progress)

            # Process items with parallel execution
            if show_progress:
                with alive_bar(
                    len(items),
                    title="Syncing items",
                    dual_line=True,
                    enrich_print=False,
                ) as bar:
                    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                        # Submit all items for parallel processing
                        # Force re-render during full sync to ensure template updates
                        futures = {
                            executor.submit(
                                self._sync_single_item_batch,
                                item_data,
                                result,
                                batch_data,
                                force_rerender=True,
                            ): item_data
                            for item_data in items
                        }

                        # Process completed futures
                        for future in as_completed(futures):
                            item_data = futures[future]
                            try:
                                title = item_data.get("data", {}).get(
                                    "title", "Unknown"
                                )
                                bar.text = f"-> {title}"
                                future.result()  # Raise any exception
                            except Exception as e:
                                error_msg = f"Error syncing item {item_data.get('key', 'UNKNOWN')}: {e}"
                                logger.error(error_msg)
                                result.add_error(error_msg)
                            finally:
                                bar()
            else:
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    # Force re-render during full sync to ensure template updates
                    futures = {
                        executor.submit(
                            self._sync_single_item_batch,
                            item_data,
                            result,
                            batch_data,
                            force_rerender=True,
                        ): item_data
                        for item_data in items
                    }

                    for future in as_completed(futures):
                        item_data = futures[future]
                        try:
                            future.result()
                        except Exception as e:
                            error_msg = f"Error syncing item {item_data.get('key', 'UNKNOWN')}: {e}"
                            logger.error(error_msg)
                            result.add_error(error_msg)

            # Detect and handle removed items
            removed_count = self._handle_removed_items()
            result.items_removed = removed_count

            # Update sync metadata
            self.state.record_full_sync(current_version)

            # Record template version after successful sync
            current_hash = self.renderer.get_template_hash()
            current_path = self.renderer.get_template_path_identifier()
            self.state.record_template_version(current_hash, current_path)

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

        Uses batch fetching and parallel processing for performance.

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

            # Check for template changes
            current_hash = self.renderer.get_template_hash()
            current_path = self.renderer.get_template_path_identifier()
            stored_version = self.state.get_template_version()

            template_changed = TemplateChangeDetector.has_template_changed(
                current_hash, current_path, stored_version
            )

            if template_changed:
                logger.warning(
                    "Template changed since last sync. Re-rendering all items..."
                )
                return self._full_rerender_all_items(show_progress)

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

            # Batch fetch annotations and attachments (major optimization)
            batch_data = self._build_batch_data(show_progress=show_progress)

            # Process modified items with parallel execution
            if show_progress:
                with alive_bar(
                    len(modified_items),
                    title="Syncing changes",
                    dual_line=True,
                    enrich_print=False,
                ) as bar:
                    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                        futures = {
                            executor.submit(
                                self._sync_single_item_batch,
                                item_data,
                                result,
                                batch_data,
                            ): item_data
                            for item_data in modified_items
                        }

                        for future in as_completed(futures):
                            item_data = futures[future]
                            try:
                                title = item_data.get("data", {}).get(
                                    "title", "Unknown"
                                )
                                bar.text = f"-> {title}"
                                future.result()
                            except Exception as e:
                                error_msg = f"Error syncing item {item_data.get('key', 'UNKNOWN')}: {e}"
                                logger.error(error_msg)
                                result.add_error(error_msg)
                            finally:
                                bar()
            else:
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    futures = {
                        executor.submit(
                            self._sync_single_item_batch,
                            item_data,
                            result,
                            batch_data,
                        ): item_data
                        for item_data in modified_items
                    }

                    for future in as_completed(futures):
                        item_data = futures[future]
                        try:
                            future.result()
                        except Exception as e:
                            error_msg = f"Error syncing item {item_data.get('key', 'UNKNOWN')}: {e}"
                            logger.error(error_msg)
                            result.add_error(error_msg)

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

            # Record template version after successful sync
            current_hash = self.renderer.get_template_hash()
            current_path = self.renderer.get_template_path_identifier()
            self.state.record_template_version(current_hash, current_path)

            logger.info(
                f"Incremental sync complete: {result.items_updated} updated, {result.items_removed} removed"
            )
            return result

        except Exception as e:
            logger.error(f"Incremental sync failed: {e}")
            raise

    def _sync_single_item_batch(
        self,
        item_data: dict,
        result: SyncResult,
        batch_data: BatchData,
        force_rerender: bool = False,
    ) -> None:
        """
        Sync a single Zotero item using pre-fetched batch data.

        This is the optimized version that uses pre-fetched annotations
        and attachment data instead of making per-item API calls.

        Args:
            item_data: Zotero API item data
            result: SyncResult to update (thread-safe)
            batch_data: Pre-fetched annotations and attachment mappings
            force_rerender: If True, skip optimization and always re-render
        """
        result.increment_processed()

        # Parse item
        item = ZoteroItem.from_api_response(item_data, self.library_id)

        if not item:
            # No citation key - skip
            logger.debug(f"Skipping item {item_data.get('key')} - no citation key")
            result.increment_skipped()
            return

        # Check if item exists in database (thread-safe read)
        with self._db_lock:
            existing_state = self.state.get_item_state(item.key)

        # Get annotations from pre-fetched batch data (no API call!)
        annotations = batch_data.annotations_by_item.get(item.key, [])
        result.add_annotations(len(annotations))

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
            # UNLESS force_rerender is set (e.g., during --full sync)
            if (
                not force_rerender
                and not item_version_changed
                and not annotations_changed
            ):
                logger.debug(f"Item {item.key} and annotations unchanged, skipping")
                return

            is_update = True

        # Get PDF attachment key from pre-fetched batch data (no API call!)
        attachment_key = batch_data.attachment_keys.get(item.key)

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

        # Write markdown file (each file is different, no locking needed)
        file_path = self.files.write_markdown(item.citation_key, markdown)

        # Compute content hash
        content_hash = self.files.get_content_hash(item.citation_key)

        # Store item JSON for future re-rendering
        import json

        item_json = json.dumps(item_data)

        # Update database (thread-safe write)
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
        with self._db_lock:
            self.state.upsert_item(item_state, item_json=item_json)

        # Update sync statistics (thread-safe)
        if is_update:
            result.increment_updated()
            logger.debug(f"Updated item: {item.citation_key}")
        else:
            result.increment_created()
            logger.debug(f"Created item: {item.citation_key}")

    def _sync_single_item(self, item_data: dict, result: SyncResult) -> None:
        """
        Sync a single Zotero item (legacy method).

        This is the original implementation that makes per-item API calls.
        Kept for backwards compatibility but not used by default.

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

    def _full_rerender_all_items(self, show_progress: bool = True) -> SyncResult:
        """
        Re-render all active items from cached data (no Zotero API calls).

        Used when template changes and we need to re-render existing files
        without fetching fresh data from Zotero.

        Args:
            show_progress: Show progress bar

        Returns:
            SyncResult with re-render statistics
        """
        result = SyncResult()

        # Get current template version
        current_hash = self.renderer.get_template_hash()
        current_path = self.renderer.get_template_path_identifier()

        # Get all active items from database
        active_items = self.state.get_active_items()
        logger.info(f"Re-rendering {len(active_items)} items due to template change")

        # Batch fetch current annotations and attachments
        batch_data = self._build_batch_data(show_progress=show_progress)

        # Re-render each item in parallel
        if show_progress:
            with alive_bar(
                len(active_items),
                title="Re-rendering items",
                dual_line=True,
                enrich_print=False,
            ) as bar:
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    futures = {
                        executor.submit(
                            self._rerender_single_item,
                            item_state,
                            result,
                            batch_data,
                        ): item_state
                        for item_state in active_items
                    }

                    for future in as_completed(futures):
                        item_state = futures[future]
                        try:
                            bar.text = f"-> {item_state.citation_key}"
                            future.result()
                        except Exception as e:
                            error_msg = (
                                f"Error re-rendering {item_state.citation_key}: {e}"
                            )
                            logger.error(error_msg)
                            result.add_error(error_msg)
                        finally:
                            bar()
        else:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = [
                    executor.submit(
                        self._rerender_single_item, item_state, result, batch_data
                    )
                    for item_state in active_items
                ]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"Error during re-render: {e}")
                        result.add_error(str(e))

        # Record template version after successful re-render
        self.state.record_template_version(current_hash, current_path)

        logger.info(f"Re-rendered {len(active_items)} items successfully")
        return result

    def _rerender_single_item(
        self,
        item_state: ItemState,
        result: SyncResult,
        batch_data: BatchData,
    ) -> None:
        """
        Re-render a single item from cached database data.

        Args:
            item_state: Item state from database
            result: SyncResult to update (thread-safe)
            batch_data: Pre-fetched annotations and attachments
        """
        import json

        # Get item JSON from database
        with self._db_lock:
            cursor = self.state.conn.cursor()
            cursor.execute(
                "SELECT item_json FROM sync_items WHERE zotero_key = ?",
                (item_state.zotero_key,),
            )
            row = cursor.fetchone()

        if not row or not row[0]:
            # Fallback: Fetch from Zotero API if JSON not cached
            logger.warning(
                f"No cached JSON for {item_state.citation_key}, fetching from API"
            )
            try:
                item_data = self.zotero.zot.item(item_state.zotero_key)
            except Exception as e:
                logger.error(f"Failed to fetch item {item_state.zotero_key}: {e}")
                result.add_error(f"Failed to re-render {item_state.citation_key}: {e}")
                return
        else:
            item_data = json.loads(row[0])

        # Parse item from JSON
        item = ZoteroItem.from_api_response(item_data, self.library_id)
        if not item:
            logger.warning(f"Failed to parse item {item_state.zotero_key}")
            return

        # Get annotations and attachment from batch data
        annotations = batch_data.annotations_by_item.get(item_state.zotero_key, [])
        attachment_key = batch_data.attachment_keys.get(item_state.zotero_key)

        # Read existing file to preserve notes
        existing_content = self.files.read_existing(item_state.citation_key)
        preserved_notes = None
        if existing_content:
            preserved_notes = self.renderer.extract_notes_section(existing_content)

        # Re-render with new template
        markdown = self.renderer.render_item(
            item=item,
            annotations=annotations,
            library_id=self.library_id,
            preserved_notes=preserved_notes,
            attachment_key=attachment_key,
        )

        # Write file
        self.files.write_markdown(item_state.citation_key, markdown)

        # Update content hash
        content_hash = self.files.get_content_hash(item_state.citation_key)

        # Store item JSON for future re-rendering
        item_json = json.dumps(item_data)

        # Update database with new hash and timestamp
        updated_state = ItemState(
            zotero_key=item_state.zotero_key,
            citation_key=item_state.citation_key,
            item_type=item_state.item_type,
            zotero_version=item_state.zotero_version,
            file_path=item_state.file_path,
            last_synced_at=datetime.now(),
            sync_status=item_state.sync_status,
            content_hash=content_hash,
        )

        with self._db_lock:
            self.state.upsert_item(updated_state, item_json=item_json)

        result.increment_updated()
