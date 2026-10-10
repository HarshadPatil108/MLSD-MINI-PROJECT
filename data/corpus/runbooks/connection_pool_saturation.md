# Runbook: PostgreSQL Connection Pool Saturation and Starvation

## Overview and Symptom
Applications encounter client connection errors, timeouts, or receive database error:
`FATAL: remaining connection slots are reserved for non-replication superuser connections`.
Application latencies spike due to thread exhaustion waiting for available database backend workers.

### Symptoms
- Application logs showing connection timeout or pool acquisition failure.
- PostgreSQL alert `connection_count` or `active_connections` exceeding 85% of `max_connections`.
- HTTP 500 or 503 errors returned to end users.
- High connection latency or backend starvation.

## Root Cause Analysis
Every client connection spawns or consumes an operating system process in PostgreSQL. Connection saturation typically stems from:
1. Connection pool leaks in application services failing to release connections back to the pool.
2. Long-running transactions lingering in `idle in transaction` state holding connections and transaction locks.
3. Sudden traffic surges exceeding allocated pool size without an intermediate connection pooler (e.g. PgBouncer).
4. Cascading microservice retries compounding connection demand.

## Diagnostic Procedures

### 1. Check Connection Breakdown by State
Determine how many connections are active vs idle vs idle in transaction:
```sql
SELECT
    state,
    count(*) AS connections
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY state
ORDER BY connections DESC;
```

### 2. Identify Idle in Transaction Connections
Find sessions holding transactions open without executing queries:
```sql
SELECT
    pid,
    usename,
    client_addr,
    now() - state_change AS idle_duration,
    query
FROM pg_stat_activity
WHERE state = 'idle in transaction'
ORDER BY idle_duration DESC
LIMIT 10;
```

### 3. Check Connection Limits
Check configured maximum connection limits:
```sql
SHOW max_connections;
SHOW superuser_reserved_connections;
```

## Remediation Steps

### Step 1: Terminate Stale Idle in Transaction Sessions
Terminate sessions that have been idle in transaction for more than 5 minutes:
```sql
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND state_change < now() - INTERVAL '5 minutes'
  AND pid <> pg_backend_pid();
```

### Step 2: Configure Session Timeouts
Set protective timeouts to automatically drop abandoned transactions:
```sql
ALTER SYSTEM SET idle_in_transaction_session_timeout = '60s';
SELECT pg_reload_conf();
```

### Step 3: Implement or Tune Connection Pooling
Ensure applications route through a connection pooler like PgBouncer in transaction pooling mode rather than connecting directly to PostgreSQL backends.

## Escalation Criteria
- If connection saturation is accompanied by CPU spikes and query slowness across all services, page secondary database engineer (`page-secondary`).
- If critical user-facing services are completely down (SEV1), escalate to Incident Commander (`incident-commander`).
