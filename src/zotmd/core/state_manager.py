"""SQLite database manager for tracking sync state."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class ItemState:
    """Represents sync state for a single Zotero item."""

    zotero_key: str
    citation_key: str
    item_type: str
    zotero_version: int
    file_path: str
    last_synced_at: datetime
    sync_status: str  # 'active' or 'removed'
    content_hash: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class AnnotationState:
    """Represents sync state for a single annotation."""

    annotation_key: str
    parent_item_key: str
    zotero_version: int
    annotation_text: Optional[str] = None
    annotation_comment: Optional[str] = None
    annotation_color: Optional[str] = None
    color_category: Optional[str] = None
    page_label: Optional[str] = None
    created_at: Optional[datetime] = None
    synced_at: Optional[datetime] = None


class StateManager:
    """Manages SQLite database for sync state tracking."""

    def __init__(self, db_path: Path):
        """
        Initialize StateManager with database path.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self._initialize_database()

    def _initialize_database(self) -> None:
        """Create database tables if they don't exist."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Access columns by name

        cursor = self.conn.cursor()

        # Create sync_items table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_items (
                zotero_key TEXT PRIMARY KEY,
                citation_key TEXT NOT NULL,
                item_type TEXT NOT NULL,
                zotero_version INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                last_synced_at TIMESTAMP NOT NULL,
                sync_status TEXT NOT NULL,
                content_hash TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """
        )

        # Create sync_annotations table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_annotations (
                annotation_key TEXT PRIMARY KEY,
                parent_item_key TEXT NOT NULL,
                zotero_version INTEGER NOT NULL,
                annotation_text TEXT,
                annotation_comment TEXT,
                annotation_color TEXT,
                color_category TEXT,
                page_label TEXT,
                created_at TIMESTAMP NOT NULL,
                synced_at TIMESTAMP NOT NULL,
                FOREIGN KEY (parent_item_key) REFERENCES sync_items(zotero_key) ON DELETE CASCADE
            )
        """
        )

        # Create sync_metadata table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_metadata (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_library_version INTEGER,
                last_full_sync TIMESTAMP,
                last_incremental_sync TIMESTAMP,
                total_items_synced INTEGER DEFAULT 0,
                total_annotations_synced INTEGER DEFAULT 0
            )
        """
        )

        # Create indices
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sync_items_citation_key
            ON sync_items(citation_key)
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sync_items_status
            ON sync_items(sync_status)
        """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sync_annotations_parent
            ON sync_annotations(parent_item_key)
        """
        )

        # Initialize sync_metadata if empty
        cursor.execute("SELECT COUNT(*) FROM sync_metadata")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                """
                INSERT INTO sync_metadata (id, total_items_synced, total_annotations_synced)
                VALUES (1, 0, 0)
            """
            )

        self.conn.commit()

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    # Sync metadata methods

    def get_last_library_version(self) -> Optional[int]:
        """Get version from last sync."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT last_library_version FROM sync_metadata WHERE id = 1")
        row = cursor.fetchone()
        return row[0] if row and row[0] else None

    def update_library_version(self, version: int) -> None:
        """Update library version after sync."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE sync_metadata
            SET last_library_version = ?,
                last_incremental_sync = ?
            WHERE id = 1
        """,
            (version, datetime.now()),
        )
        self.conn.commit()

    def record_full_sync(self, version: int) -> None:
        """Record completion of full sync."""
        cursor = self.conn.cursor()
        now = datetime.now()
        cursor.execute(
            """
            UPDATE sync_metadata
            SET last_library_version = ?,
                last_full_sync = ?,
                last_incremental_sync = ?
            WHERE id = 1
        """,
            (version, now, now),
        )
        self.conn.commit()

    # Item state methods

    def get_item_state(self, zotero_key: str) -> Optional[ItemState]:
        """Get sync state for specific item."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sync_items WHERE zotero_key = ?
        """,
            (zotero_key,),
        )
        row = cursor.fetchone()

        if not row:
            return None

        return ItemState(
            zotero_key=row["zotero_key"],
            citation_key=row["citation_key"],
            item_type=row["item_type"],
            zotero_version=row["zotero_version"],
            file_path=row["file_path"],
            last_synced_at=datetime.fromisoformat(row["last_synced_at"]),
            sync_status=row["sync_status"],
            content_hash=row["content_hash"],
            created_at=(
                datetime.fromisoformat(row["created_at"]) if row["created_at"] else None
            ),
            updated_at=(
                datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
            ),
        )

    def upsert_item(self, item_state: ItemState) -> None:
        """Insert or update item sync state."""
        cursor = self.conn.cursor()
        now = datetime.now()

        # Check if exists
        existing = self.get_item_state(item_state.zotero_key)

        if existing:
            # Update
            cursor.execute(
                """
                UPDATE sync_items SET
                    citation_key = ?,
                    item_type = ?,
                    zotero_version = ?,
                    file_path = ?,
                    last_synced_at = ?,
                    sync_status = ?,
                    content_hash = ?,
                    updated_at = ?
                WHERE zotero_key = ?
            """,
                (
                    item_state.citation_key,
                    item_state.item_type,
                    item_state.zotero_version,
                    item_state.file_path,
                    item_state.last_synced_at,
                    item_state.sync_status,
                    item_state.content_hash,
                    now,
                    item_state.zotero_key,
                ),
            )
        else:
            # Insert
            cursor.execute(
                """
                INSERT INTO sync_items (
                    zotero_key, citation_key, item_type, zotero_version,
                    file_path, last_synced_at, sync_status, content_hash,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    item_state.zotero_key,
                    item_state.citation_key,
                    item_state.item_type,
                    item_state.zotero_version,
                    item_state.file_path,
                    item_state.last_synced_at,
                    item_state.sync_status,
                    item_state.content_hash,
                    now,
                    now,
                ),
            )

        self.conn.commit()

    def mark_item_removed(self, zotero_key: str) -> None:
        """Mark item as removed."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE sync_items
            SET sync_status = 'removed', updated_at = ?
            WHERE zotero_key = ?
        """,
            (datetime.now(), zotero_key),
        )
        self.conn.commit()

    def get_active_items(self) -> List[ItemState]:
        """Get all active (non-removed) items."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sync_items WHERE sync_status = 'active'
        """
        )

        items = []
        for row in cursor.fetchall():
            items.append(
                ItemState(
                    zotero_key=row["zotero_key"],
                    citation_key=row["citation_key"],
                    item_type=row["item_type"],
                    zotero_version=row["zotero_version"],
                    file_path=row["file_path"],
                    last_synced_at=datetime.fromisoformat(row["last_synced_at"]),
                    sync_status=row["sync_status"],
                    content_hash=row["content_hash"],
                    created_at=(
                        datetime.fromisoformat(row["created_at"])
                        if row["created_at"]
                        else None
                    ),
                    updated_at=(
                        datetime.fromisoformat(row["updated_at"])
                        if row["updated_at"]
                        else None
                    ),
                )
            )

        return items

    def get_all_item_keys(self) -> set[str]:
        """Get all active Zotero item keys."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT zotero_key FROM sync_items WHERE sync_status = 'active'")
        return {row[0] for row in cursor.fetchall()}

    # Annotation methods

    def upsert_annotation(self, annotation: AnnotationState) -> None:
        """Insert or update annotation."""
        cursor = self.conn.cursor()
        now = datetime.now()

        cursor.execute(
            """
            INSERT OR REPLACE INTO sync_annotations (
                annotation_key, parent_item_key, zotero_version,
                annotation_text, annotation_comment, annotation_color,
                color_category, page_label, created_at, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                annotation.annotation_key,
                annotation.parent_item_key,
                annotation.zotero_version,
                annotation.annotation_text,
                annotation.annotation_comment,
                annotation.annotation_color,
                annotation.color_category,
                annotation.page_label,
                annotation.created_at or now,
                annotation.synced_at or now,
            ),
        )

        self.conn.commit()

    def get_annotations_for_item(self, parent_key: str) -> List[AnnotationState]:
        """Get all synced annotations for an item."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sync_annotations WHERE parent_item_key = ?
        """,
            (parent_key,),
        )

        annotations = []
        for row in cursor.fetchall():
            annotations.append(
                AnnotationState(
                    annotation_key=row["annotation_key"],
                    parent_item_key=row["parent_item_key"],
                    zotero_version=row["zotero_version"],
                    annotation_text=row["annotation_text"],
                    annotation_comment=row["annotation_comment"],
                    annotation_color=row["annotation_color"],
                    color_category=row["color_category"],
                    page_label=row["page_label"],
                    created_at=(
                        datetime.fromisoformat(row["created_at"])
                        if row["created_at"]
                        else None
                    ),
                    synced_at=(
                        datetime.fromisoformat(row["synced_at"])
                        if row["synced_at"]
                        else None
                    ),
                )
            )

        return annotations

    # Statistics

    def get_sync_stats(self) -> dict:
        """Get sync statistics."""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM sync_items WHERE sync_status = 'active'")
        active_items = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sync_items WHERE sync_status = 'removed'")
        removed_items = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sync_annotations")
        total_annotations = cursor.fetchone()[0]

        cursor.execute("SELECT * FROM sync_metadata WHERE id = 1")
        meta = cursor.fetchone()

        return {
            "active_items": active_items,
            "removed_items": removed_items,
            "total_annotations": total_annotations,
            "last_library_version": meta["last_library_version"] if meta else None,
            "last_full_sync": meta["last_full_sync"] if meta else None,
            "last_incremental_sync": meta["last_incremental_sync"] if meta else None,
        }
