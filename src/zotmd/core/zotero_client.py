"""Zotero API client wrapper using pyzotero."""

from typing import List, Optional
import logging
from pyzotero import zotero


logger = logging.getLogger(__name__)


class ZoteroClient:
    """Wrapper around pyzotero with additional functionality for sync."""

    def __init__(self, library_id: str, library_type: str, api_key: str):
        """
        Initialize Zotero client.

        Args:
            library_id: Zotero library ID
            library_type: 'user' or 'group'
            api_key: Zotero API key

        Raises:
            ValueError: If library_type is invalid
        """
        if library_type not in ("user", "group"):
            raise ValueError(
                f"library_type must be 'user' or 'group', got: {library_type}"
            )

        self.library_id = library_id
        self.library_type = library_type
        self.zot = zotero.Zotero(library_id, library_type, api_key)

        logger.info(
            f"Initialized Zotero client for {library_type} library {library_id}"
        )

    def get_library_version(self) -> int:
        """
        Get current library version number.

        Returns:
            Library version as integer

        Raises:
            Exception: If API request fails
        """
        try:
            version = self.zot.last_modified_version()
            logger.debug(f"Current library version: {version}")
            return version
        except Exception as e:
            logger.error(f"Failed to get library version: {e}")
            raise

    def get_all_items(self, batch_size: int = 100) -> List[dict]:
        """
        Fetch all top-level items using pagination.

        Args:
            batch_size: Number of items per batch (default: 100)

        Returns:
            List of all item dictionaries

        Raises:
            Exception: If API request fails
        """
        try:
            logger.info(f"Fetching all items (batch size: {batch_size})")

            # Use pyzotero's everything() method for automatic pagination
            items = self.zot.everything(self.zot.top(limit=batch_size))

            logger.info(f"Fetched {len(items)} total items")
            return items

        except Exception as e:
            logger.error(f"Failed to fetch all items: {e}")
            raise

    def get_items_since_version(
        self, version: int, batch_size: int = 100
    ) -> List[dict]:
        """
        Fetch items modified since a specific version (incremental sync).

        Args:
            version: Library version to fetch changes since
            batch_size: Number of items per batch

        Returns:
            List of modified item dictionaries

        Raises:
            Exception: If API request fails
        """
        try:
            logger.info(f"Fetching items since version {version}")

            # Fetch items modified since version
            items = self.zot.everything(self.zot.top(limit=batch_size, since=version))

            logger.info(f"Fetched {len(items)} modified items since version {version}")
            return items

        except Exception as e:
            logger.error(f"Failed to fetch items since version {version}: {e}")
            raise

    def get_item_children(self, item_key: str) -> List[dict]:
        """
        Get child items (attachments, notes) for a specific item.

        Args:
            item_key: Zotero item key

        Returns:
            List of child item dictionaries

        Raises:
            Exception: If API request fails
        """
        try:
            children = self.zot.children(item_key)
            logger.debug(f"Fetched {len(children)} children for item {item_key}")
            return children

        except Exception as e:
            logger.error(f"Failed to fetch children for item {item_key}: {e}")
            raise

    def get_annotations_for_item(self, item_key: str) -> List[dict]:
        """
        Fetch all annotations for a specific item.

        Annotations in Zotero are children of PDF attachments, not direct
        children of the parent item. This method:
        1. Gets all children of the item (attachments, notes)
        2. For each attachment, gets its children (annotations)
        3. Returns all annotations found

        Args:
            item_key: Zotero item key

        Returns:
            List of annotation dictionaries

        Raises:
            Exception: If API request fails
        """
        try:
            annotations = []

            # Get all children of the item (attachments, notes, etc.)
            children = self.get_item_children(item_key)

            # For each child, if it's an attachment, get its children (annotations)
            for child in children:
                child_data = child.get("data", {})
                child_type = child_data.get("itemType")

                # Check if this child is an attachment
                if child_type == "attachment":
                    attachment_key = child.get("key")
                    content_type = child_data.get("contentType", "")
                    link_mode = child_data.get("linkMode", "")

                    # Only fetch children for PDF, EPUB, and snapshot attachments
                    # Other attachment types (linked_file, etc.) don't support /children
                    if (
                        "pdf" in content_type.lower()
                        or "epub" in content_type.lower()
                        or link_mode == "imported_url"
                    ):
                        logger.debug(
                            f"Fetching annotations from attachment {attachment_key}"
                        )

                        try:
                            # Get children of the attachment (these are the annotations)
                            attachment_children = self.get_item_children(attachment_key)

                            # Filter for annotations
                            attachment_annotations = [
                                annot
                                for annot in attachment_children
                                if annot.get("data", {}).get("itemType") == "annotation"
                            ]

                            annotations.extend(attachment_annotations)
                            logger.debug(
                                f"Found {len(attachment_annotations)} annotations in attachment {attachment_key}"
                            )
                        except Exception as e:
                            # Some attachments may not support children - log and continue
                            logger.debug(
                                f"Could not fetch children for attachment {attachment_key}: {e}"
                            )
                            continue
                    else:
                        logger.debug(
                            f"Skipping attachment {attachment_key} (type: {content_type}, mode: {link_mode})"
                        )

            logger.debug(
                f"Found {len(annotations)} total annotations for item {item_key}"
            )
            return annotations

        except Exception as e:
            logger.error(f"Failed to fetch annotations for item {item_key}: {e}")
            raise

    def get_all_annotations(self, batch_size: int = 100) -> List[dict]:
        """
        Fetch all annotations in the library.

        Args:
            batch_size: Number of items per batch

        Returns:
            List of all annotation dictionaries

        Raises:
            Exception: If API request fails
        """
        try:
            logger.info("Fetching all annotations")

            # Fetch all items of type 'annotation'
            annotations = self.zot.everything(
                self.zot.items(itemType="annotation", limit=batch_size)
            )

            logger.info(f"Fetched {len(annotations)} total annotations")
            return annotations

        except Exception as e:
            logger.error(f"Failed to fetch all annotations: {e}")
            raise

    def get_deleted_items(self, since_version: int) -> dict:
        """
        Get items deleted since a specific version.

        Args:
            since_version: Library version to check deletions since

        Returns:
            Dictionary with 'items', 'collections', 'searches', 'tags' lists

        Raises:
            Exception: If API request fails
        """
        try:
            logger.info(f"Fetching deleted items since version {since_version}")
            deleted = self.zot.deleted(since=since_version)

            # Extract item keys from deleted
            deleted_items = deleted.get("items", [])
            logger.info(f"Found {len(deleted_items)} deleted items")

            return deleted

        except Exception as e:
            logger.error(f"Failed to fetch deleted items: {e}")
            raise

    def get_attachment_for_item(self, item_key: str) -> Optional[dict]:
        """
        Get PDF attachment for an item (if exists).

        Args:
            item_key: Zotero item key

        Returns:
            Attachment dict or None if no PDF found

        Raises:
            Exception: If API request fails
        """
        try:
            children = self.get_item_children(item_key)

            # Find first PDF attachment
            for child in children:
                data = child.get("data", {})
                if (
                    data.get("itemType") == "attachment"
                    and data.get("contentType") == "application/pdf"
                ):
                    logger.debug(f"Found PDF attachment for item {item_key}")
                    return child

            logger.debug(f"No PDF attachment found for item {item_key}")
            return None

        except Exception as e:
            logger.error(f"Failed to fetch attachment for item {item_key}: {e}")
            raise

    def test_connection(self) -> bool:
        """
        Test if API connection is working.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Try to fetch library version as a connection test
            version = self.get_library_version()
            logger.info(f"Connection test successful (version: {version})")
            return True

        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
