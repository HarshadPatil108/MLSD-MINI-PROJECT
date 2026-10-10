"""Unit tests for Pydantic schema validation rules (F1, D1)."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.api.schemas import AlertRequest, SeverityHint


def test_valid_alert_request_full(valid_alert_payload):
    """Test full valid payload passes validation."""
    alert = AlertRequest(**valid_alert_payload)
    assert alert.alert_name == "PostgresWalAccumulationWarning"
    assert alert.source == "prometheus"
    assert alert.severity_hint == SeverityHint.CRITICAL
    assert alert.metrics["cpu_utilization"] == 72.5
    assert alert.pg_version == "18.0"
    assert alert.alert_id == "alert-test-12345"


def test_valid_alert_request_generates_id_and_tags_default(valid_alert_payload):
    """Test optional alert_id and tags are populated if missing."""
    payload = valid_alert_payload.copy()
    del payload["alert_id"]
    del payload["tags"]
    alert = AlertRequest(**payload)
    assert alert.alert_id is not None
    assert alert.alert_id.startswith("alert-")
    assert alert.tags == {}


def test_valid_pg_versions(valid_alert_payload):
    """Test accepted PostgreSQL version patterns matching indexed corpus (PG 18)."""
    for v in ["18", "18.0", "18.1", "18.99"]:
        payload = valid_alert_payload.copy()
        payload["pg_version"] = v
        alert = AlertRequest(**payload)
        assert alert.pg_version == v


def test_invalid_pg_version_mismatch(valid_alert_payload):
    """Test PostgreSQL versions other than 18 are rejected."""
    for v in ["14", "15", "16", "17", "19", "180", "postgres18"]:
        payload = valid_alert_payload.copy()
        payload["pg_version"] = v
        with pytest.raises(ValidationError) as exc:
            AlertRequest(**payload)
        assert "is unsupported. Must match indexed corpus version" in str(exc.value)


def test_fired_at_future_rejected(valid_alert_payload):
    """Test fired_at in the future is rejected."""
    payload = valid_alert_payload.copy()
    future_time = datetime.now(UTC) + timedelta(minutes=10)
    payload["fired_at"] = future_time.isoformat()
    with pytest.raises(ValidationError) as exc:
        AlertRequest(**payload)
    assert "cannot be in the future" in str(exc.value)


def test_fired_at_past_accepted(valid_alert_payload):
    """Test fired_at in the past is accepted."""
    payload = valid_alert_payload.copy()
    past_time = datetime.now(UTC) - timedelta(hours=3)
    payload["fired_at"] = past_time.isoformat()
    alert = AlertRequest(**payload)
    assert alert.fired_at is not None


def test_metric_cpu_utilization_bounds(valid_alert_payload):
    """Test CPU utilization bounds (0.0 to 100.0)."""
    # Over 100
    payload = valid_alert_payload.copy()
    payload["metrics"] = {"cpu_utilization": 105.0}
    with pytest.raises(ValidationError) as exc:
        AlertRequest(**payload)
    assert "violates upper bound" in str(exc.value)

    # Below 0
    payload["metrics"] = {"cpu_utilization": -1.0}
    with pytest.raises(ValidationError) as exc:
        AlertRequest(**payload)
    assert "violates lower bound" in str(exc.value)

    # Valid bounds
    payload["metrics"] = {"cpu_utilization": 0.0}
    assert AlertRequest(**payload).metrics["cpu_utilization"] == 0.0
    payload["metrics"] = {"cpu_utilization": 100.0}
    assert AlertRequest(**payload).metrics["cpu_utilization"] == 100.0


def test_metric_non_negative_bounds(valid_alert_payload):
    """Test non-negative metric requirements for byte/count metrics."""
    payload = valid_alert_payload.copy()
    payload["metrics"] = {"replication_lag_bytes": -100.0}
    with pytest.raises(ValidationError) as exc:
        AlertRequest(**payload)
    assert "lower bound" in str(exc.value) or "cannot be negative" in str(exc.value)


def test_metric_empty_rejected(valid_alert_payload):
    """Test empty metrics dict is rejected."""
    payload = valid_alert_payload.copy()
    payload["metrics"] = {}
    with pytest.raises(ValidationError) as exc:
        AlertRequest(**payload)
    assert "at least one metric" in str(exc.value)


def test_metric_non_finite_rejected(valid_alert_payload):
    """Test NaN and Inf metric values are rejected."""
    payload = valid_alert_payload.copy()
    payload["metrics"] = {"cpu_utilization": float("nan")}
    with pytest.raises(ValidationError) as exc:
        AlertRequest(**payload)
    assert "finite numeric value" in str(exc.value)

    payload["metrics"] = {"cpu_utilization": float("inf")}
    with pytest.raises(ValidationError) as exc:
        AlertRequest(**payload)
    assert "finite numeric value" in str(exc.value)


def test_severity_hint_invalid_enum(valid_alert_payload):
    """Test invalid severity_hint values are rejected."""
    payload = valid_alert_payload.copy()
    payload["severity_hint"] = "SEV1"
    with pytest.raises(ValidationError):
        AlertRequest(**payload)


def test_on_call_note_length_bounds(valid_alert_payload):
    """Test on_call_note min and max length bounds."""
    payload = valid_alert_payload.copy()
    payload["on_call_note"] = "hi"  # < 5 chars
    with pytest.raises(ValidationError):
        AlertRequest(**payload)

    payload["on_call_note"] = "x" * 2001  # > 2000 chars
    with pytest.raises(ValidationError):
        AlertRequest(**payload)


def test_extra_fields_forbidden(valid_alert_payload):
    """Test unexpected extra fields are forbidden."""
    payload = valid_alert_payload.copy()
    payload["malicious_extra_field"] = "injection_payload"
    with pytest.raises(ValidationError):
        AlertRequest(**payload)
