"""Pytest fixtures for ingestion tests."""

from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.quarantine import QuarantineStore, set_quarantine_store
from src.worker.queue import InMemoryTaskQueue, set_task_queue


@pytest.fixture
def mock_quarantine_store() -> Generator[QuarantineStore, None, None]:
    """Provide an isolated in-memory quarantine store."""
    store = QuarantineStore(db_path=":memory:")
    set_quarantine_store(store)
    yield store


@pytest.fixture
def mock_task_queue() -> Generator[InMemoryTaskQueue, None, None]:
    """Provide an isolated in-memory task queue."""
    queue = InMemoryTaskQueue()
    set_task_queue(queue)
    yield queue


@pytest.fixture
def test_client(
    mock_quarantine_store: QuarantineStore, mock_task_queue: InMemoryTaskQueue
) -> Generator[TestClient, None, None]:
    """Provide FastAPI test client wired with mock store and task queue."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def valid_alert_payload() -> dict[str, Any]:
    """Provide a standard valid alert request payload."""
    return {
        "alert_id": "alert-test-12345",
        "alert_name": "PostgresWalAccumulationWarning",
        "source": "prometheus",
        "fired_at": datetime.now(UTC).isoformat(),
        "metrics": {
            "replication_lag_bytes": 52428800.0,
            "active_connections": 150.0,
            "cpu_utilization": 72.5,
        },
        "pg_version": "18.0",
        "severity_hint": "CRITICAL",
        "on_call_note": "Disk usage on pg-primary rising rapidly; unused replication slot suspected.",
        "tags": {
            "environment": "production",
            "cluster": "us-east-cluster",
        },
    }
