# Ingestion Boundary Data Contract (F1, F2, D1)

## 1. Overview & Rationale

The IncidentOps ingestion boundary acts as a strict firewall for incoming operational alerts. Malformed, out-of-bounds, or incompatible inputs are prevented from consuming LLM tokens, triggering background worker tasks, or propagating unverified states into the multi-agent system.

### Key Invariants
1. **Zero Agent Invocation on Invalid Input:** Any payload violating schema, types, ranges, categories, or cross-field constraints is rejected with HTTP 422, isolated into the quarantine store, and **provably never enqueued** into the task queue.
2. **Corpus Version Compatibility:** The system diagnoses incidents based on indexed documentation. Alerts specifying a PostgreSQL version that does not match the indexed corpus (`INDEXED_PG_VERSION=18`) are quarantined immediately.
3. **Pure Advisory Output:** The ingestion contract collects diagnostic symptoms and notes; no automated remediation commands are ever accepted or executed.

---

## 2. Ingestion Endpoint: `POST /runs`

### Request Payload: `AlertRequest`

| Field | Type | Required | Constraints / Validation Rules | Description |
|---|---|:---:|---|---|
| `alert_id` | `string` | No | `^[A-Za-z0-9_-]{3,64}$` | Unique identifier for the alert. Generated (`alert-<uuid>`) if omitted. |
| `alert_name` | `string` | **Yes** | 2–128 characters, non-whitespace | Canonical alert name (e.g. `PostgresReplicationLagHigh`). |
| `source` | `string` | **Yes** | 2–64 characters, `^[a-zA-Z0-9_.-]+$` | Originating telemetry system (e.g. `prometheus`, `datadog`). |
| `fired_at` | `datetime` (ISO 8601) | **Yes** | Cannot be in future (<= server time + 10s skew buffer) | Timestamp when the alert triggered. Naive timestamps assumed UTC. |
| `metrics` | `dict[str, float]` | **Yes** | Non-empty dict; keys: `^[a-zA-Z0-9_.-]{1,64}$`; values finite numbers within bounded ranges | Key-value mapping of telemetry metrics. |
| `pg_version` | `string` | **Yes** | Must match indexed corpus version (`^18(\.[0-9]+)?$`) | Major or minor PostgreSQL version. Currently indexed: PostgreSQL 18. |
| `severity_hint` | `string` (Enum) | **Yes** | Value in `["CRITICAL", "WARNING", "INFO"]` | Initial severity categorization hint. |
| `on_call_note` | `string` | **Yes** | 5–2000 characters, non-whitespace | Contextual notes from the on-call engineer describing symptoms. |
| `tags` | `dict[str, str]` | No | Default `{}` | Operational metadata (e.g. `{"cluster": "prod", "env": "prod"}`). |

### Metric Range Invariants

The `metrics` dictionary enforces finite numeric values and explicit range checks:

- **Percentage / Utilization Metrics** (keys matching `cpu_utilization`, `cpu_usage_pct`, `memory_utilization`, `disk_utilization`, or any key containing `pct`/`percent`/`utilization`):
  - Must satisfy: `0.0 <= value <= 100.0`.
- **Count / Magnitude Metrics** (keys matching `connection_count`, `active_connections`, `replication_lag_bytes`, `wal_keep_size_mb`, or keys containing `bytes`/`count`/`seconds`/`lag`):
  - Must satisfy: `value >= 0.0`.
- **Predefined Operational Metrics:**
  - `replication_lag_seconds`: `0.0 <= value <= 864000.0` (up to 10 days)
  - `deadlocks_per_second`: `0.0 <= value <= 10000.0`
  - `connection_count`: `0.0 <= value <= 100000.0`
- **Global Bounds:**
  - `value` must be a finite float (not `NaN`, `+Inf`, or `-Inf`).
  - Absolute bounds: `-1e12 <= value <= 1e15`.

---

## 3. Responses

### 3.1. Successful Ingestion: HTTP 202 Accepted

When the payload satisfies all validation constraints:
1. The alert is accepted.
2. A unique `run_id` is generated.
3. The job is enqueued to the task queue (`RedisTaskQueue` or configured backend).
4. HTTP 202 Accepted is returned immediately:

```json
{
  "run_id": "run-a1b2c3d4e5f6",
  "status": "queued",
  "created_at": "2026-10-10T22:30:00.123456Z",
  "alert_name": "PostgresReplicationLagHigh",
  "message": "Alert validated successfully and enqueued for multi-agent triage."
}
```

### 3.2. Validation Failure: HTTP 422 Unprocessable Entity & Quarantine

When any schema, type, range, categorical, or cross-field validation fails:
1. The request is intercepted by the ingestion exception handler.
2. The raw payload, client details, and field-level error diagnostics are recorded in the SQLite **quarantine store**.
3. **No job is enqueued to the task queue.**
4. HTTP 422 is returned with the `quarantine_id`:

```json
{
  "detail": "Request validation failed. Payload has been quarantined.",
  "quarantine_id": "quar-8f7e6d5c4b3a",
  "quarantined_at": "2026-10-10T22:30:05.654321Z",
  "errors": [
    {
      "field": "pg_version",
      "message": "PostgreSQL version '15' is unsupported. Must match indexed corpus version '18' (e.g. '18' or '18.0').",
      "type": "value_error",
      "input_value": "15"
    },
    {
      "field": "metrics.cpu_utilization",
      "message": "Metric 'cpu_utilization' value 150.0 violates upper bound (CPU usage % (0-100))",
      "type": "value_error",
      "input_value": 150.0
    }
  ]
}
```

---

## 4. Quarantine Store Contract (F2)

Quarantined requests are audited in a dedicated SQLite database table (`quarantined_requests`).

### Schema Definition

```sql
CREATE TABLE IF NOT EXISTS quarantined_requests (
    id TEXT PRIMARY KEY,
    quarantined_at TEXT NOT NULL,
    client_info TEXT,
    raw_payload TEXT NOT NULL,
    errors TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quarantined_at ON quarantined_requests (quarantined_at DESC);
```

### Quarantine Query Endpoints

#### `GET /quarantine`
Returns paginated list of quarantined items:
- Query Parameters: `limit` (default: 100, max: 1000), `offset` (default: 0).
- Response:
```json
{
  "total": 1,
  "items": [
    {
      "id": "quar-8f7e6d5c4b3a",
      "quarantined_at": "2026-10-10T22:30:05.654321Z",
      "client_info": "127.0.0.1 | python-httpx/0.28.1",
      "raw_payload": { ... },
      "errors": [ ... ],
      "reason": "Request failed validation contract"
    }
  ]
}
```

#### `GET /quarantine/{quarantine_id}`
Returns the complete record for a single quarantined payload, or HTTP 404 if not found.

---

## 5. Examples

### 5.1 Valid Request Example

```json
{
  "alert_name": "PostgresWalAccumulationWarning",
  "source": "prometheus",
  "fired_at": "2026-10-10T22:28:00Z",
  "metrics": {
    "disk_utilization": 87.2,
    "replication_lag_bytes": 524288000.0,
    "active_connections": 128.0
  },
  "pg_version": "18.0",
  "severity_hint": "CRITICAL",
  "on_call_note": "Disk usage on pg-primary rising rapidly; unused replication slot suspected.",
  "tags": {
    "environment": "production",
    "cluster": "us-east-cluster"
  }
}
```

### 5.2 Invalid Request Examples Quarantined by Category

1. **Future Timestamp Violation:**
   - `fired_at: "2029-01-01T00:00:00Z"`
   - Quarantined: `fired_at timestamp cannot be in the future`.
2. **Corpus Version Mismatch:**
   - `pg_version: "14.2"`
   - Quarantined: `PostgreSQL version '14.2' is unsupported. Must match indexed corpus version '18'`.
3. **Metric Range Violation:**
   - `metrics: {"cpu_utilization": -10.0}`
   - Quarantined: `Metric 'cpu_utilization' value -10.0 violates lower bound`.
4. **Categorical Enum Violation:**
   - `severity_hint: "URGENT"`
   - Quarantined: `Input should be 'CRITICAL', 'WARNING' or 'INFO'`.
5. **Length Bounds Violation:**
   - `on_call_note: "help"` (4 characters, minimum 5)
   - Quarantined: `String should have at least 5 characters`.
