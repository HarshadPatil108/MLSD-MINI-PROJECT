"""Unit tests for SQLite quarantine store (F2, D1)."""

from src.api.quarantine import QuarantineStore
from src.api.schemas import QuarantineErrorDetail


def test_quarantine_store_crud():
    """Test quarantine insert, retrieve, list, count, and clear in memory."""
    store = QuarantineStore(db_path=":memory:")
    assert store.count() == 0

    # 1. Record an invalid payload
    raw_payload = {"alert_name": "BadAlert", "pg_version": "14"}
    errors = [
        QuarantineErrorDetail(
            field="pg_version",
            message="Version 14 unsupported",
            type="value_error",
            input_value="14",
        )
    ]
    record = store.record_quarantine(
        raw_payload=raw_payload,
        errors=errors,
        client_info="127.0.0.1",
        reason="Invalid PG version",
    )

    assert record.id.startswith("quar-")
    assert record.raw_payload == raw_payload
    assert len(record.errors) == 1
    assert record.errors[0].field == "pg_version"
    assert store.count() == 1

    # 2. Retrieve record
    retrieved = store.get_record(record.id)
    assert retrieved is not None
    assert retrieved.id == record.id
    assert retrieved.errors[0].message == "Version 14 unsupported"
    assert retrieved.client_info == "127.0.0.1"

    # 3. Retrieve non-existent
    assert store.get_record("quar-nonexistent") is None

    # 4. List records with pagination
    records, total = store.list_records(limit=10, offset=0)
    assert total == 1
    assert len(records) == 1
    assert records[0].id == record.id

    # 5. Clear records
    store.clear()
    assert store.count() == 0
    records, total = store.list_records(limit=10, offset=0)
    assert total == 0
    assert len(records) == 0
