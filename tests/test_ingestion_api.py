"""Integration tests for ingestion boundary, validation quarantine, and task queue (F1, F2, D1)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.quarantine import QuarantineStore
from src.worker.queue import InMemoryTaskQueue


def test_valid_request_starts_run_and_enqueues(
    test_client: TestClient,
    mock_quarantine_store: QuarantineStore,
    mock_task_queue: InMemoryTaskQueue,
    valid_alert_payload: dict[str, Any],
):
    """Test valid alert request returns 202, enqueues to task queue, and is not quarantined."""
    response = test_client.post("/runs", json=valid_alert_payload)

    # 1. Verify HTTP 202 Accepted
    assert response.status_code == 202
    data = response.json()
    assert "run_id" in data
    assert data["status"] == "queued"
    assert data["alert_name"] == valid_alert_payload["alert_name"]

    # 2. Provably verify task is enqueued in the task queue
    assert mock_task_queue.length() == 1
    dequeued = mock_task_queue.dequeue()
    assert dequeued is not None
    run_id, payload = dequeued
    assert run_id == data["run_id"]
    assert payload["alert_name"] == valid_alert_payload["alert_name"]
    assert payload["pg_version"] == "18.0"

    # 3. Verify quarantine store remains empty
    assert mock_quarantine_store.count() == 0


@pytest.mark.parametrize(
    "case_name,mutator,expected_field,expected_msg_substring",
    [
        (
            "schema_missing_metrics",
            lambda p: p.pop("metrics"),
            "metrics",
            "Field required",
        ),
        (
            "schema_missing_alert_name",
            lambda p: p.pop("alert_name"),
            "alert_name",
            "Field required",
        ),
        (
            "type_metrics_string_not_dict",
            lambda p: p.update({"metrics": "invalid_string"}),
            "metrics",
            "Input should be a valid dictionary",
        ),
        (
            "range_cpu_utilization_over_100",
            lambda p: p.update({"metrics": {"cpu_utilization": 142.0}}),
            "metrics",
            "violates upper bound",
        ),
        (
            "range_replication_lag_negative",
            lambda p: p.update({"metrics": {"replication_lag_bytes": -99.0}}),
            "metrics",
            "violates lower bound",
        ),
        (
            "category_severity_hint_invalid_enum",
            lambda p: p.update({"severity_hint": "SEV1_CRITICAL"}),
            "severity_hint",
            "Input should be 'CRITICAL', 'WARNING' or 'INFO'",
        ),
        (
            "length_on_call_note_too_short",
            lambda p: p.update({"on_call_note": "bad"}),
            "on_call_note",
            "at least 5 characters",
        ),
        (
            "cross_field_future_fired_at",
            lambda p: p.update({"fired_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()}),
            "body",
            "cannot be in the future",
        ),
        (
            "cross_field_unsupported_pg_version",
            lambda p: p.update({"pg_version": "15.4"}),
            "body",
            "is unsupported. Must match indexed corpus version",
        ),
    ],
)
def test_invalid_request_classes_quarantine_and_never_enqueue(
    test_client: TestClient,
    mock_quarantine_store: QuarantineStore,
    mock_task_queue: InMemoryTaskQueue,
    valid_alert_payload: dict[str, Any],
    case_name: str,
    mutator: Any,
    expected_field: str,
    expected_msg_substring: str,
):
    """Test that each invalid request class returns 422, is logged to quarantine, and provably does NOT enqueue."""
    payload = valid_alert_payload.copy()
    mutator(payload)

    initial_quarantine_count = mock_quarantine_store.count()
    initial_queue_length = mock_task_queue.length()

    response = test_client.post("/runs", json=payload)

    # 1. Must return 422
    assert response.status_code == 422, f"Failed on {case_name}: {response.text}"
    body = response.json()
    assert "quarantine_id" in body
    assert body["detail"] == "Request validation failed. Payload has been quarantined."

    # 2. Field error details must contain the expected failure
    errors = body["errors"]
    assert len(errors) > 0
    matched = any(
        expected_field in err["field"] and expected_msg_substring.lower() in err["message"].lower()
        for err in errors
    )
    assert matched, (
        f"Case {case_name} expected field '{expected_field}' with '{expected_msg_substring}', got: {errors}"
    )

    # 3. Provably verify task queue length has NOT increased (no job enqueued)
    assert mock_task_queue.length() == initial_queue_length, (
        f"Case {case_name} incorrectly enqueued a job!"
    )

    # 4. Verify record in quarantine store
    quarantine_id = body["quarantine_id"]
    stored_record = mock_quarantine_store.get_record(quarantine_id)
    assert stored_record is not None
    assert stored_record.id == quarantine_id
    assert mock_quarantine_store.count() == initial_quarantine_count + 1


def test_malformed_json_body_quarantined_without_enqueue(
    test_client: TestClient,
    mock_quarantine_store: QuarantineStore,
    mock_task_queue: InMemoryTaskQueue,
):
    """Test raw malformed JSON body is rejected, quarantined, and not enqueued."""
    malformed_raw = '{"alert_name": "Broken", "source": missing_quotes}'

    response = test_client.post(
        "/runs", content=malformed_raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    body = response.json()
    assert "quarantine_id" in body

    # Provably verify no job enqueued
    assert mock_task_queue.length() == 0

    # Stored in quarantine
    record = mock_quarantine_store.get_record(body["quarantine_id"])
    assert record is not None


def test_quarantine_query_endpoints(
    test_client: TestClient,
    mock_quarantine_store: QuarantineStore,
    valid_alert_payload: dict[str, Any],
):
    """Test GET /quarantine and GET /quarantine/{id} endpoints."""
    # Send an invalid payload to create a quarantine record
    bad_payload = valid_alert_payload.copy()
    bad_payload["pg_version"] = "13.1"
    post_res = test_client.post("/runs", json=bad_payload)
    assert post_res.status_code == 422
    quarantine_id = post_res.json()["quarantine_id"]

    # List quarantine items
    list_res = test_client.get("/quarantine?limit=10&offset=0")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 1
    assert any(item["id"] == quarantine_id for item in list_data["items"])

    # Get specific quarantine record
    item_res = test_client.get(f"/quarantine/{quarantine_id}")
    assert item_res.status_code == 200
    item_data = item_res.json()
    assert item_data["id"] == quarantine_id
    assert item_data["raw_payload"]["pg_version"] == "13.1"

    # Query non-existent record returns 404
    missing_res = test_client.get("/quarantine/quar-does-not-exist")
    assert missing_res.status_code == 404


def test_health_check_endpoint(test_client: TestClient):
    """Test GET /health returns 200 OK and reports service and index status."""
    response = test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "api"
    assert "index" in data
