"""Pydantic schemas and validation contracts for alert ingestion (F1, F2, D1)."""

import math
import re
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.settings import get_settings


class SeverityHint(str, Enum):
    """Categorical severity hint for the incoming alert."""

    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class MetricRangeRule(BaseModel):
    """Definition for metric range validation."""

    min_val: float | None = None
    max_val: float | None = None
    description: str


# Common metric definitions with realistic operational bounds
KNOWN_METRIC_BOUNDS: dict[str, MetricRangeRule] = {
    "cpu_utilization": MetricRangeRule(
        min_val=0.0, max_val=100.0, description="CPU usage % (0-100)"
    ),
    "cpu_usage_pct": MetricRangeRule(min_val=0.0, max_val=100.0, description="CPU usage % (0-100)"),
    "memory_utilization": MetricRangeRule(
        min_val=0.0, max_val=100.0, description="Memory usage % (0-100)"
    ),
    "memory_usage_pct": MetricRangeRule(
        min_val=0.0, max_val=100.0, description="Memory usage % (0-100)"
    ),
    "disk_utilization": MetricRangeRule(
        min_val=0.0, max_val=100.0, description="Disk usage % (0-100)"
    ),
    "disk_usage_pct": MetricRangeRule(
        min_val=0.0, max_val=100.0, description="Disk usage % (0-100)"
    ),
    "connection_count": MetricRangeRule(
        min_val=0.0, max_val=100000.0, description="Active connection count (>= 0)"
    ),
    "active_connections": MetricRangeRule(
        min_val=0.0, max_val=100000.0, description="Active connection count (>= 0)"
    ),
    "replication_lag_bytes": MetricRangeRule(
        min_val=0.0, max_val=1e15, description="Replication lag in bytes (>= 0)"
    ),
    "replication_lag_seconds": MetricRangeRule(
        min_val=0.0, max_val=864000.0, description="Replication lag in seconds (>= 0)"
    ),
    "wal_keep_size_mb": MetricRangeRule(
        min_val=0.0, max_val=1e9, description="WAL size in MB (>= 0)"
    ),
    "deadlocks_per_second": MetricRangeRule(
        min_val=0.0, max_val=10000.0, description="Deadlock rate (>= 0)"
    ),
}


class AlertRequest(BaseModel):
    """Strict data contract for incoming incident alerts (F1, D1).

    Enforces schema, type, range, category, and cross-field validation rules
    before any multi-agent reasoning or enqueueing can occur.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "alert_id": "alert-wal-001",
                "alert_name": "PostgresReplicationLagHigh",
                "source": "prometheus",
                "fired_at": "2026-10-10T22:30:00Z",
                "metrics": {
                    "replication_lag_bytes": 104857600.0,
                    "active_connections": 42.0,
                    "disk_utilization": 84.5,
                },
                "pg_version": "18.0",
                "severity_hint": "CRITICAL",
                "on_call_note": "Replication slot standby_1 appears inactive and disk is filling up with WAL.",
                "tags": {"cluster": "prod-db-primary", "region": "us-east-1"},
            }
        },
    )

    alert_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Optional unique identifier for the alert. Generated if omitted.",
    )
    alert_name: str = Field(
        ...,
        min_length=2,
        max_length=128,
        description="Canonical alert name / title (e.g. PostgresReplicationLagHigh).",
    )
    source: str = Field(
        ...,
        min_length=2,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_\.-]+$",
        description="Monitoring source originating the alert (e.g. prometheus, datadog, manual).",
    )
    fired_at: datetime = Field(
        ...,
        description="ISO 8601 timestamp when the alert triggered. Must not be in the future.",
    )
    metrics: dict[str, float] = Field(
        ...,
        description="Key-value mapping of metric names to numeric values with range bounds.",
    )
    pg_version: str = Field(
        ...,
        description="PostgreSQL major or dot version. Must match the indexed corpus version (e.g. 18).",
    )
    severity_hint: SeverityHint = Field(
        ...,
        description="Categorical severity hint (CRITICAL, WARNING, INFO).",
    )
    on_call_note: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="Contextual engineer note describing symptoms or triage context (5-2000 chars).",
    )
    tags: dict[str, str] = Field(
        default_factory=dict,
        description="Optional operational tags (environment, host, region, cluster).",
    )

    @field_validator("alert_name")
    @classmethod
    def validate_alert_name(cls, value: str) -> str:
        """Validate alert name is non-empty and well-formed."""
        if not value or not value.strip():
            raise ValueError("alert_name must not be empty or whitespace only")
        return value.strip()

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, metrics_dict: dict[str, float]) -> dict[str, float]:
        """Validate metric keys, finiteness, and ranges."""
        if not metrics_dict:
            raise ValueError("metrics dictionary must contain at least one metric key-value pair")

        validated: dict[str, float] = {}
        for key, val in metrics_dict.items():
            clean_key = key.strip()
            if not clean_key:
                raise ValueError("Metric key cannot be empty or whitespace")

            if not re.match(r"^[a-zA-Z0-9_.-]{1,64}$", clean_key):
                raise ValueError(
                    f"Invalid metric key '{clean_key}'. Must match pattern '^[a-zA-Z0-9_.-]{{1,64}}$'"
                )

            # Ensure numeric finiteness
            if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                raise ValueError(
                    f"Metric '{clean_key}' must have a finite numeric value, got {val}"
                )

            float_val = float(val)

            # Check known bounds if defined
            if clean_key in KNOWN_METRIC_BOUNDS:
                bound = KNOWN_METRIC_BOUNDS[clean_key]
                if bound.min_val is not None and float_val < bound.min_val:
                    raise ValueError(
                        f"Metric '{clean_key}' value {float_val} violates lower bound ({bound.description})"
                    )
                if bound.max_val is not None and float_val > bound.max_val:
                    raise ValueError(
                        f"Metric '{clean_key}' value {float_val} violates upper bound ({bound.description})"
                    )
            else:
                # Generic sanity checks:
                # Percentage checks based on key suffix
                if any(sub in clean_key.lower() for sub in ["pct", "percent", "utilization"]):
                    if float_val < 0.0 or float_val > 100.0:
                        raise ValueError(
                            f"Percentage metric '{clean_key}' value {float_val} must be between 0.0 and 100.0"
                        )
                # Count/lag/duration/bytes checks
                elif (
                    any(
                        sub in clean_key.lower()
                        for sub in ["bytes", "count", "seconds", "lag", "size"]
                    )
                    and float_val < 0.0
                ):
                    raise ValueError(f"Metric '{clean_key}' value {float_val} cannot be negative")
                # Global extreme limit safeguard
                if float_val < -1e12 or float_val > 1e15:
                    raise ValueError(
                        f"Metric '{clean_key}' value {float_val} exceeds realistic range"
                    )

            validated[clean_key] = float_val

        return validated

    @model_validator(mode="after")
    def validate_cross_field_rules(self) -> "AlertRequest":
        """Cross-field validations: fired_at non-future check and pg_version corpus compatibility."""
        # 1. Default alert_id if not supplied
        if not self.alert_id:
            self.alert_id = f"alert-{uuid.uuid4().hex[:12]}"

        # 2. Check fired_at is not in the future (allowing 10s skew buffer)
        now_utc = datetime.now(UTC)
        fired_dt = self.fired_at
        if fired_dt.tzinfo is None:
            # Assume UTC if naive
            fired_dt = fired_dt.replace(tzinfo=UTC)

        skew_buffer = timedelta(seconds=10)
        if fired_dt > (now_utc + skew_buffer):
            raise ValueError(
                f"fired_at timestamp ({self.fired_at.isoformat()}) cannot be in the future. "
                f"Current server time: {now_utc.isoformat()}"
            )

        # 3. Check pg_version matches indexed corpus version
        settings = get_settings()
        expected_version = settings.INDEXED_PG_VERSION.strip()
        version_pattern = rf"^{re.escape(expected_version)}(\.[0-9]+)?$"

        clean_version = self.pg_version.strip()
        if not re.match(version_pattern, clean_version):
            raise ValueError(
                f"PostgreSQL version '{clean_version}' is unsupported. "
                f"Must match indexed corpus version '{expected_version}' (e.g. '{expected_version}' or '{expected_version}.0')."
            )

        return self


class QuarantineErrorDetail(BaseModel):
    """Field-level error detail for quarantined requests."""

    field: str = Field(..., description="Field path or identifier where validation failed.")
    message: str = Field(..., description="Human-readable validation failure reason.")
    type: str = Field(..., description="Pydantic or schema error type code.")
    input_value: Any | None = Field(default=None, description="Provided input value if available.")


class QuarantineRecord(BaseModel):
    """Stored record of a quarantined malformed request."""

    id: str = Field(..., description="Unique quarantine record identifier.")
    quarantined_at: datetime = Field(..., description="UTC timestamp of quarantine event.")
    client_info: str | None = Field(default=None, description="Client IP or agent info.")
    raw_payload: dict[str, Any] = Field(..., description="The rejected raw request payload.")
    errors: list[QuarantineErrorDetail] = Field(..., description="Field-level validation errors.")
    reason: str = Field(..., description="Summary explanation for rejection.")


class QuarantineErrorResponse(BaseModel):
    """HTTP 422 response payload returned when request fails ingestion contract."""

    detail: str = Field(
        default="Request validation failed. Payload has been quarantined.",
        description="High-level status message.",
    )
    quarantine_id: str = Field(..., description="Lookup ID in the quarantine store.")
    quarantined_at: datetime = Field(..., description="Timestamp when record was quarantined.")
    errors: list[QuarantineErrorDetail] = Field(
        ..., description="List of field-level validation errors."
    )


class RunResponse(BaseModel):
    """HTTP 202 response returned when an alert is valid and enqueued."""

    run_id: str = Field(..., description="Unique execution run identifier.")
    status: str = Field(default="queued", description="Initial lifecycle status of the run.")
    created_at: datetime = Field(..., description="Timestamp when the run was enqueued.")
    alert_name: str = Field(..., description="Validated alert name.")
    message: str = Field(
        default="Alert validated successfully and enqueued for multi-agent triage.",
        description="Confirmation message.",
    )


class QuarantineListResponse(BaseModel):
    """Response model for querying the quarantine store."""

    total: int = Field(..., description="Total quarantined records.")
    items: list[QuarantineRecord] = Field(..., description="List of quarantine entries.")
