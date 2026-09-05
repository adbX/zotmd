"""SQLite database manager for tracking sync state."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 4
DEFAULT_RENDER_CONTRACT_VERSION = 2


class StateManagerError(RuntimeError):
    """Base error for state database failures."""


class LegacyStateError(StateManagerError):
    """Raised when pre-0.4 state must be archived instead of migrated."""


class IncompatibleStateError(StateManagerError):
    """Raised when state does not match the supported schema."""


class StateIdentityError(StateManagerError):
    """Raised when configured library and output identities are unsafe."""


class ReadOnlyStateError(StateManagerError):
    """Raised when a state mutation is attempted in read-only mode."""


class StateManagerClosedError(StateManagerError):
    """Raised when closed state is accessed."""


@dataclass
class ItemState:
    """Sync state for one top-level Zotero item."""

    zotero_key: str
    citation_key: str
    item_type: str
    zotero_version: int
    file_path: str
    last_synced_at: datetime
    sync_status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    item_json: str | None = None
    child_signature: str = ""
    annotation_count: int = 0


@dataclass
class TemplateVersion:
    """A recorded template and render-contract checkpoint."""

    template_hash: str
    template_path: str
    render_contract_version: int = DEFAULT_RENDER_CONTRACT_VERSION
    recorded_at: datetime | None = None


@dataclass(frozen=True)
class SyncCheckpoint:
    """Exact metadata values needed to restore a pending checkpoint."""

    last_library_version: int | None
    last_full_sync: str | None
    last_incremental_sync: str | None
    template_hash: str | None
    template_path: str | None
    template_version_at: str | None
    render_contract_version: int | None


class StateManager:
    """Manage the versioned SQLite sync state."""

    def __init__(
        self,
        db_path: Path,
        library_id: str | None = None,
        output_root: Path | None = None,
        *,
        read_only: bool = False,
    ) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.read_only = read_only
        self.conn: sqlite3.Connection | None = None
        self.library_id: str | None = None
        self.output_root: Path | None = None
        self._previous_output_root: Path | None = None
        self._savepoint_number = 0

        if read_only:
            self._open_read_only()
            return

        if not library_id or output_root is None:
            raise ValueError(
                "Writable state requires nonempty library_id and output_root values"
            )

        requested_output = Path(output_root).expanduser().resolve()
        self.library_id = library_id
        self.output_root = requested_output
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._open_writable(library_id, requested_output)

    def _open_read_only(self) -> None:
        """Open and validate an existing database without changing it."""
        if not self.db_path.is_file():
            raise FileNotFoundError(f"State database does not exist: {self.db_path}")

        connection = self._connect_read_only()
        try:
            self._validate_existing_database(connection)
            library_id, output_root = self._read_identity(connection)
        except Exception:
            connection.close()
            raise

        self.conn = connection
        self.library_id = library_id
        self.output_root = output_root

    def _open_writable(self, library_id: str, output_root: Path) -> None:
        """Create fresh state or open compatible state after identity checks."""
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            self.conn = self._connect_writable()
            self._create_schema(library_id, output_root)
            return

        inspection = self._connect_read_only()
        try:
            is_empty = self._validate_existing_database(inspection, allow_empty=True)
            if is_empty:
                stored_identity = None
            else:
                stored_identity = self._read_identity(inspection)
        except Exception:
            inspection.close()
            raise
        inspection.close()

        if stored_identity is None:
            self.conn = self._connect_writable()
            self._create_schema(library_id, output_root)
            return

        stored_library_id, stored_output_root = stored_identity
        if stored_library_id == library_id:
            if stored_output_root != output_root:
                self._previous_output_root = stored_output_root
            self.conn = self._connect_writable()
            return

        if stored_output_root == output_root:
            raise StateIdentityError(
                "State belongs to personal library "
                f"{stored_library_id}, not {library_id}. A different library cannot use "
                "the same output root; select a distinct empty output directory."
            )

        if not self._output_is_empty(output_root):
            raise StateIdentityError(
                f"Cannot start state for personal library {library_id}: the distinct "
                f"output root is not empty: {output_root}"
            )

        self.db_path.replace(self._next_archive_path())
        self.conn = self._connect_writable()
        self._create_schema(library_id, output_root)

    def _connect_read_only(self) -> sqlite3.Connection:
        uri = f"{self.db_path.as_uri()}?mode=ro"
        try:
            connection = sqlite3.connect(
                uri,
                uri=True,
                check_same_thread=False,
            )
        except sqlite3.Error as error:
            raise IncompatibleStateError(
                f"Cannot open state database read-only: {self.db_path}"
            ) from error
        connection.row_factory = sqlite3.Row
        return connection

    def _connect_writable(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _validate_existing_database(
        self,
        connection: sqlite3.Connection,
        *,
        allow_empty: bool = False,
    ) -> bool:
        """Validate an existing database, returning whether it has no user tables."""
        try:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT name
                    FROM sqlite_schema
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    """
                )
            }
        except sqlite3.Error as error:
            raise IncompatibleStateError(
                f"State database is not a readable SQLite database: {self.db_path}"
            ) from error

        if version == 0 and tables:
            raise LegacyStateError(
                "This is legacy ZotMD 0.3 state and cannot be opened by ZotMD 0.4. "
                f"Archive {self.db_path}, then run a fresh sync to create new 0.4 state. "
                "The legacy database was not modified."
            )

        if version == 0 and not tables:
            if allow_empty:
                return True
            raise IncompatibleStateError(
                f"State database is empty and cannot be opened read-only: {self.db_path}"
            )

        if version != SCHEMA_VERSION:
            raise IncompatibleStateError(
                f"Unsupported state schema version {version}; expected {SCHEMA_VERSION}"
            )

        expected_tables = {"sync_items", "sync_metadata"}
        if tables != expected_tables:
            raise IncompatibleStateError(
                "State schema version 4 does not contain exactly the expected tables"
            )

        required_item_columns = {
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
        required_metadata_columns = {
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
        if self._column_names(connection, "sync_items") != required_item_columns:
            raise IncompatibleStateError(
                "State schema version 4 has incompatible sync_items columns"
            )
        if self._column_names(connection, "sync_metadata") != required_metadata_columns:
            raise IncompatibleStateError(
                "State schema version 4 has incompatible sync_metadata columns"
            )

        rows = connection.execute("SELECT COUNT(*) FROM sync_metadata").fetchone()[0]
        if rows != 1:
            raise IncompatibleStateError(
                "State schema version 4 must contain one metadata identity row"
            )
        return False

    @staticmethod
    def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        }

    def _create_schema(self, library_id: str, output_root: Path) -> None:
        """Create the schema in a new or empty database."""
        connection = self._connection()
        try:
            connection.execute("BEGIN")
            connection.execute(
                """
                CREATE TABLE sync_metadata (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    library_id TEXT NOT NULL,
                    output_root TEXT NOT NULL,
                    last_library_version INTEGER,
                    last_full_sync TEXT,
                    last_incremental_sync TEXT,
                    template_hash TEXT,
                    template_path TEXT,
                    template_version_at TEXT,
                    render_contract_version INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE sync_items (
                    zotero_key TEXT PRIMARY KEY,
                    citation_key TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    zotero_version INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    last_synced_at TEXT NOT NULL,
                    sync_status TEXT NOT NULL
                        CHECK (sync_status IN ('active', 'removed')),
                    item_json TEXT,
                    child_signature TEXT NOT NULL DEFAULT '',
                    annotation_count INTEGER NOT NULL DEFAULT 0
                        CHECK (annotation_count >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX idx_sync_items_citation_key
                ON sync_items(citation_key)
                """
            )
            connection.execute(
                """
                CREATE INDEX idx_sync_items_status
                ON sync_items(sync_status)
                """
            )
            connection.execute(
                """
                INSERT INTO sync_metadata (id, library_id, output_root)
                VALUES (1, ?, ?)
                """,
                (library_id, str(output_root)),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _read_identity(connection: sqlite3.Connection) -> tuple[str, Path]:
        row = connection.execute(
            "SELECT library_id, output_root FROM sync_metadata WHERE id = 1"
        ).fetchone()
        if row is None or not row[0] or not row[1]:
            raise IncompatibleStateError(
                "State metadata does not contain a valid library and output identity"
            )
        return str(row[0]), Path(str(row[1]))

    @staticmethod
    def _output_is_empty(output_root: Path) -> bool:
        if not output_root.exists():
            return True
        if not output_root.is_dir():
            return False
        try:
            next(output_root.iterdir())
        except StopIteration:
            return True
        except OSError as error:
            raise StateIdentityError(
                f"Cannot inspect proposed output root: {output_root}"
            ) from error
        return False

    def _next_archive_path(self) -> Path:
        suffix = self.db_path.suffix
        base = self.db_path.with_name(f"{self.db_path.stem}.0.4-archive{suffix}")
        if not base.exists():
            return base

        number = 2
        while True:
            candidate = self.db_path.with_name(
                f"{self.db_path.stem}.0.4-archive-{number}{suffix}"
            )
            if not candidate.exists():
                return candidate
            number += 1

    def _connection(self) -> sqlite3.Connection:
        """Return the live connection with a nonoptional type."""
        if self.conn is None:
            raise StateManagerClosedError("StateManager is closed")
        return self.conn

    def _writable_connection(self) -> sqlite3.Connection:
        connection = self._connection()
        if self.read_only:
            raise ReadOnlyStateError("StateManager is read-only")
        return connection

    @staticmethod
    def _commit_if_standalone(
        connection: sqlite3.Connection, was_in_transaction: bool
    ) -> None:
        if not was_in_transaction:
            connection.commit()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="microseconds")

    @staticmethod
    def _datetime_to_iso(value: datetime) -> str:
        return value.isoformat(timespec="microseconds")

    @staticmethod
    def _datetime_from_iso(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    def close(self) -> None:
        """Close the database connection."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "StateManager":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator["StateManager"]:
        """Commit grouped mutations together, or roll all of them back."""
        connection = self._writable_connection()
        was_in_transaction = connection.in_transaction
        original_output_root = self.output_root
        original_previous_output_root = self._previous_output_root
        self._savepoint_number += 1
        savepoint = f"zotmd_state_{self._savepoint_number}"
        connection.execute(f"SAVEPOINT {savepoint}")
        try:
            yield self
        except BaseException as error:
            try:
                self._roll_back_savepoint(connection, savepoint, was_in_transaction)
            except BaseException as rollback_error:
                raise StateManagerError(
                    f"State transaction rollback failed: {rollback_error}"
                ) from error
            finally:
                self.output_root = original_output_root
                self._previous_output_root = original_previous_output_root
            raise
        else:
            try:
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            except BaseException as error:
                if not was_in_transaction and not connection.in_transaction:
                    raise
                try:
                    self._roll_back_savepoint(
                        connection,
                        savepoint,
                        was_in_transaction,
                    )
                except BaseException as rollback_error:
                    raise StateManagerError(
                        f"State transaction rollback failed: {rollback_error}"
                    ) from error
                finally:
                    self.output_root = original_output_root
                    self._previous_output_root = original_previous_output_root
                raise

    def _roll_back_savepoint(
        self,
        connection: sqlite3.Connection,
        savepoint: str,
        was_in_transaction: bool,
    ) -> None:
        """End a failed savepoint without leaving pending state visible."""
        try:
            if was_in_transaction:
                connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                connection.rollback()
        except BaseException:
            connection.close()
            self.conn = None
            raise

    def get_identity(self) -> tuple[str, Path]:
        """Return the library and output identity stored in metadata."""
        return self._read_identity(self._connection())

    @property
    def previous_output_root(self) -> Path | None:
        """Return the stored root when this instance requests a new root."""
        return self._previous_output_root

    def update_output_root(self, output_root: Path | None = None) -> None:
        """Checkpoint a completed move to the configured or supplied output root."""
        connection = self._writable_connection()
        target = output_root or self.output_root
        if target is None:
            raise ValueError("No output root is available to record")
        resolved_target = Path(target).expanduser().resolve()
        was_in_transaction = connection.in_transaction
        connection.execute(
            "UPDATE sync_metadata SET output_root = ? WHERE id = 1",
            (str(resolved_target),),
        )
        self.output_root = resolved_target
        self._previous_output_root = None
        self._commit_if_standalone(connection, was_in_transaction)

    def get_last_library_version(self) -> int | None:
        """Return the most recent completed library checkpoint."""
        row = (
            self._connection()
            .execute("SELECT last_library_version FROM sync_metadata WHERE id = 1")
            .fetchone()
        )
        return int(row[0]) if row is not None and row[0] is not None else None

    def get_checkpoint(self) -> SyncCheckpoint:
        """Return the exact synchronization checkpoint metadata."""
        row = (
            self._connection()
            .execute(
                """
                SELECT last_library_version, last_full_sync, last_incremental_sync,
                       template_hash, template_path, template_version_at,
                       render_contract_version
                FROM sync_metadata WHERE id = 1
                """
            )
            .fetchone()
        )
        if row is None:
            raise IncompatibleStateError("State has no synchronization metadata")
        return SyncCheckpoint(
            last_library_version=(int(row[0]) if row[0] is not None else None),
            last_full_sync=row[1],
            last_incremental_sync=row[2],
            template_hash=row[3],
            template_path=row[4],
            template_version_at=row[5],
            render_contract_version=(int(row[6]) if row[6] is not None else None),
        )

    def restore_checkpoint(self, checkpoint: SyncCheckpoint) -> None:
        """Restore checkpoint metadata after post-commit verification fails."""
        connection = self._writable_connection()
        was_in_transaction = connection.in_transaction
        connection.execute(
            """
            UPDATE sync_metadata
            SET last_library_version = ?,
                last_full_sync = ?,
                last_incremental_sync = ?,
                template_hash = ?,
                template_path = ?,
                template_version_at = ?,
                render_contract_version = ?
            WHERE id = 1
            """,
            (
                checkpoint.last_library_version,
                checkpoint.last_full_sync,
                checkpoint.last_incremental_sync,
                checkpoint.template_hash,
                checkpoint.template_path,
                checkpoint.template_version_at,
                checkpoint.render_contract_version,
            ),
        )
        self._commit_if_standalone(connection, was_in_transaction)

    def update_library_version(self, version: int) -> None:
        """Record completion of an incremental sync."""
        connection = self._writable_connection()
        was_in_transaction = connection.in_transaction
        connection.execute(
            """
            UPDATE sync_metadata
            SET last_library_version = ?, last_incremental_sync = ?
            WHERE id = 1
            """,
            (version, self._now_iso()),
        )
        self._commit_if_standalone(connection, was_in_transaction)

    def record_full_sync(self, version: int) -> None:
        """Record completion of a full sync."""
        connection = self._writable_connection()
        was_in_transaction = connection.in_transaction
        now = self._now_iso()
        connection.execute(
            """
            UPDATE sync_metadata
            SET last_library_version = ?,
                last_full_sync = ?,
                last_incremental_sync = ?
            WHERE id = 1
            """,
            (version, now, now),
        )
        self._commit_if_standalone(connection, was_in_transaction)

    def get_item_state(self, zotero_key: str) -> ItemState | None:
        """Return state for one Zotero item."""
        row = (
            self._connection()
            .execute("SELECT * FROM sync_items WHERE zotero_key = ?", (zotero_key,))
            .fetchone()
        )
        return self._item_from_row(row) if row is not None else None

    @classmethod
    def _item_from_row(cls, row: sqlite3.Row) -> ItemState:
        last_synced_at = cls._datetime_from_iso(row["last_synced_at"])
        if last_synced_at is None:
            raise IncompatibleStateError("Item state has no last_synced_at timestamp")
        return ItemState(
            zotero_key=str(row["zotero_key"]),
            citation_key=str(row["citation_key"]),
            item_type=str(row["item_type"]),
            zotero_version=int(row["zotero_version"]),
            file_path=str(row["file_path"]),
            last_synced_at=last_synced_at,
            sync_status=str(row["sync_status"]),
            created_at=cls._datetime_from_iso(row["created_at"]),
            updated_at=cls._datetime_from_iso(row["updated_at"]),
            item_json=row["item_json"],
            child_signature=str(row["child_signature"]),
            annotation_count=int(row["annotation_count"]),
        )

    def upsert_item(self, item_state: ItemState, item_json: str | None = None) -> None:
        """Insert or update item state, preserving cached JSON when omitted."""
        connection = self._writable_connection()
        if item_state.sync_status not in {"active", "removed"}:
            raise ValueError("sync_status must be 'active' or 'removed'")
        if item_state.annotation_count < 0:
            raise ValueError("annotation_count cannot be negative")

        cached_json = item_json if item_json is not None else item_state.item_json
        now = self._now_iso()
        created_at = (
            self._datetime_to_iso(item_state.created_at)
            if item_state.created_at is not None
            else now
        )
        was_in_transaction = connection.in_transaction
        connection.execute(
            """
            INSERT INTO sync_items (
                zotero_key, citation_key, item_type, zotero_version, file_path,
                last_synced_at, sync_status, item_json, child_signature,
                annotation_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(zotero_key) DO UPDATE SET
                citation_key = excluded.citation_key,
                item_type = excluded.item_type,
                zotero_version = excluded.zotero_version,
                file_path = excluded.file_path,
                last_synced_at = excluded.last_synced_at,
                sync_status = excluded.sync_status,
                item_json = COALESCE(excluded.item_json, sync_items.item_json),
                child_signature = excluded.child_signature,
                annotation_count = excluded.annotation_count,
                updated_at = excluded.updated_at
            """,
            (
                item_state.zotero_key,
                item_state.citation_key,
                item_state.item_type,
                item_state.zotero_version,
                item_state.file_path,
                self._datetime_to_iso(item_state.last_synced_at),
                item_state.sync_status,
                cached_json,
                item_state.child_signature,
                item_state.annotation_count,
                created_at,
                now,
            ),
        )
        self._commit_if_standalone(connection, was_in_transaction)

    def mark_item_removed(self, zotero_key: str) -> None:
        """Mark an item as removed."""
        connection = self._writable_connection()
        was_in_transaction = connection.in_transaction
        connection.execute(
            """
            UPDATE sync_items
            SET sync_status = 'removed', updated_at = ?
            WHERE zotero_key = ?
            """,
            (self._now_iso(), zotero_key),
        )
        self._commit_if_standalone(connection, was_in_transaction)

    def get_active_items(self) -> list[ItemState]:
        """Return all active items in stable key order."""
        rows = self._connection().execute(
            """
            SELECT * FROM sync_items
            WHERE sync_status = 'active'
            ORDER BY zotero_key
            """
        )
        return [self._item_from_row(row) for row in rows]

    def get_managed_items(self) -> list[ItemState]:
        """Return every active and removed managed item in stable key order."""
        rows = self._connection().execute(
            "SELECT * FROM sync_items ORDER BY zotero_key"
        )
        return [self._item_from_row(row) for row in rows]

    def get_all_item_keys(self) -> set[str]:
        """Return all active Zotero item keys."""
        rows = self._connection().execute(
            "SELECT zotero_key FROM sync_items WHERE sync_status = 'active'"
        )
        return {str(row[0]) for row in rows}

    def get_sync_stats(self) -> dict[str, int | str | None]:
        """Calculate current item and active-annotation statistics."""
        counts = (
            self._connection()
            .execute(
                """
            SELECT
                SUM(CASE WHEN sync_status = 'active' THEN 1 ELSE 0 END),
                SUM(CASE WHEN sync_status = 'removed' THEN 1 ELSE 0 END),
                SUM(
                    CASE WHEN sync_status = 'active' THEN annotation_count ELSE 0 END
                )
            FROM sync_items
            """
            )
            .fetchone()
        )
        metadata = (
            self._connection()
            .execute(
                """
            SELECT last_library_version, last_full_sync, last_incremental_sync
            FROM sync_metadata WHERE id = 1
            """
            )
            .fetchone()
        )
        return {
            "active_items": int(counts[0] or 0),
            "removed_items": int(counts[1] or 0),
            "total_annotations": int(counts[2] or 0),
            "last_library_version": metadata[0],
            "last_full_sync": metadata[1],
            "last_incremental_sync": metadata[2],
        }

    def get_template_version(self) -> TemplateVersion | None:
        """Return the recorded template and render-contract checkpoint."""
        row = (
            self._connection()
            .execute(
                """
            SELECT template_hash, template_path, render_contract_version,
                   template_version_at
            FROM sync_metadata WHERE id = 1
            """
            )
            .fetchone()
        )
        if row is None or row[0] is None:
            return None
        return TemplateVersion(
            template_hash=str(row[0]),
            template_path=str(row[1]),
            render_contract_version=int(row[2]),
            recorded_at=self._datetime_from_iso(row[3]),
        )

    def record_template_version(
        self,
        template_hash: str,
        template_path: str,
        render_contract_version: int = DEFAULT_RENDER_CONTRACT_VERSION,
    ) -> None:
        """Record a completed template and render-contract checkpoint."""
        connection = self._writable_connection()
        was_in_transaction = connection.in_transaction
        connection.execute(
            """
            UPDATE sync_metadata
            SET template_hash = ?,
                template_path = ?,
                render_contract_version = ?,
                template_version_at = ?
            WHERE id = 1
            """,
            (
                template_hash,
                template_path,
                render_contract_version,
                self._now_iso(),
            ),
        )
        self._commit_if_standalone(connection, was_in_transaction)
