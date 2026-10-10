"""Quarantine storage repository backed by SQLite (F2, D1)."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import get_settings
from src.api.schemas import QuarantineErrorDetail, QuarantineRecord


class QuarantineStore:
    """Thread-safe SQLite store for logging and auditing invalid ingestion payloads."""

    def __init__(self, db_path: str | None = None):
        """Initialize SQLite quarantine store.

        Args:
            db_path: Path to SQLite DB file, or ':memory:'. If None, uses settings.
        """
        if db_path is None:
            settings = get_settings()
            db_path = settings.QUARANTINE_DB_PATH

        self.db_path = db_path
        self._is_memory = self.db_path == ":memory:"
        self._conn: sqlite3.Connection | None = None

        if self._is_memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        else:
            db_file = Path(self.db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row

        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Return the active database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_schema(self) -> None:
        """Create quarantine table and index if they do not exist."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quarantined_requests (
                    id TEXT PRIMARY KEY,
                    quarantined_at TEXT NOT NULL,
                    client_info TEXT,
                    raw_payload TEXT NOT NULL,
                    errors TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_quarantined_at
                ON quarantined_requests (quarantined_at DESC);
                """
            )
            conn.commit()

    def record_quarantine(
        self,
        raw_payload: dict[str, Any],
        errors: list[QuarantineErrorDetail | dict[str, Any]],
        client_info: str | None = None,
        reason: str = "Request failed validation contract",
    ) -> QuarantineRecord:
        """Store an invalid request in the quarantine table.

        Args:
            raw_payload: The raw request dictionary that failed validation.
            errors: List of field-level errors.
            client_info: Optional client IP or User-Agent.
            reason: High-level failure reason.

        Returns:
            The persisted QuarantineRecord.
        """
        record_id = f"quar-{uuid.uuid4().hex[:12]}"
        now_dt = datetime.now(UTC)
        now_str = now_dt.isoformat()

        # Normalize errors into list of QuarantineErrorDetail objects
        normalized_errors: list[QuarantineErrorDetail] = []
        for err in errors:
            if isinstance(err, QuarantineErrorDetail):
                normalized_errors.append(err)
            elif isinstance(err, dict):
                normalized_errors.append(
                    QuarantineErrorDetail(
                        field=str(err.get("field", "unknown")),
                        message=str(err.get("message", "Validation error")),
                        type=str(err.get("type", "validation_error")),
                        input_value=err.get("input_value", None),
                    )
                )

        errors_json = json.dumps([e.model_dump() for e in normalized_errors])
        payload_json = json.dumps(raw_payload)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO quarantined_requests (id, quarantined_at, client_info, raw_payload, errors, reason)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (record_id, now_str, client_info, payload_json, errors_json, reason),
            )
            conn.commit()

        return QuarantineRecord(
            id=record_id,
            quarantined_at=now_dt,
            client_info=client_info,
            raw_payload=raw_payload,
            errors=normalized_errors,
            reason=reason,
        )

    def get_record(self, record_id: str) -> QuarantineRecord | None:
        """Retrieve a single quarantined record by ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, quarantined_at, client_info, raw_payload, errors, reason
                FROM quarantined_requests
                WHERE id = ?;
                """,
                (record_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return self._row_to_record(row)

    def list_records(self, limit: int = 100, offset: int = 0) -> tuple[list[QuarantineRecord], int]:
        """List quarantined records with pagination."""
        with self._get_connection() as conn:
            total_row = conn.execute("SELECT COUNT(*) as cnt FROM quarantined_requests;").fetchone()
            total = total_row["cnt"] if total_row else 0

            cursor = conn.execute(
                """
                SELECT id, quarantined_at, client_info, raw_payload, errors, reason
                FROM quarantined_requests
                ORDER BY quarantined_at DESC
                LIMIT ? OFFSET ?;
                """,
                (limit, offset),
            )
            rows = cursor.fetchall()
            records = [self._row_to_record(r) for r in rows]
            return records, total

    def count(self) -> int:
        """Return total count of quarantined items."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM quarantined_requests;").fetchone()
            return row["cnt"] if row else 0

    def clear(self) -> None:
        """Clear all records from quarantine (for testing only)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM quarantined_requests;")
            conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> QuarantineRecord:
        """Convert a database row into a QuarantineRecord Pydantic model."""
        raw_payload = json.loads(row["raw_payload"])
        errors_raw = json.loads(row["errors"])
        errors = [QuarantineErrorDetail(**e) for e in errors_raw]
        quarantined_at = datetime.fromisoformat(row["quarantined_at"])

        return QuarantineRecord(
            id=row["id"],
            quarantined_at=quarantined_at,
            client_info=row["client_info"],
            raw_payload=raw_payload,
            errors=errors,
            reason=row["reason"],
        )


# Global default instance
_quarantine_store: QuarantineStore | None = None


def get_quarantine_store() -> QuarantineStore:
    """Get or create singleton quarantine store."""
    global _quarantine_store
    if _quarantine_store is None:
        _quarantine_store = QuarantineStore()
    return _quarantine_store


def set_quarantine_store(store: QuarantineStore) -> None:
    """Override singleton quarantine store (for testing)."""
    global _quarantine_store
    _quarantine_store = store
