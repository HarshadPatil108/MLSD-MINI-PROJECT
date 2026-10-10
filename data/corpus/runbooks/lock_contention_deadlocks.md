# Runbook: PostgreSQL Lock Contention and Serialization Deadlocks

## Overview and Symptom
Applications report transaction timeouts, elevated query latency, or database errors:
`ERROR: deadlock detected - Detail: Process X waits for ExclusiveLock on relation...`.
Metric alerts trigger on `deadlocks_per_second > 0` or high blocked queries.

### Symptoms
- Deadlock error log rate increases in PostgreSQL logs.
- Queries blocked waiting for row-level or table-level locks.
- Latency degradation on transactional endpoints (e.g. order checkout, account transfers).
- Active queries piling up in `active` state with wait event types `Lock` or `relation`.

## Root Cause Analysis
Lock contention and deadlocks arise when:
1. Two or more concurrent transactions acquire locks on multiple shared objects in differing orders (e.g., Transaction 1 locks Row A then Row B; Transaction 2 locks Row B then Row A).
2. Unindexed foreign keys causing table-wide share locks during parent key updates.
3. Long-running analytical batch queries (or `pg_dump`) holding share locks while concurrent OLTP transactions attempt exclusive row or schema updates.
4. Schema migrations (DDL) running during business hours requesting `ACCESS EXCLUSIVE` locks.

## Diagnostic Procedures

### 1. Identify Blocked and Blocking Queries
Execute the lock contention query to find the blocker tree:
```sql
SELECT
    blocked_activity.pid AS blocked_pid,
    blocked_activity.query AS blocked_query,
    blocking_activity.pid AS blocking_pid,
    blocking_activity.query AS blocking_query,
    now() - blocked_activity.query_start AS waiting_duration
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

### 2. Inspect Recent Deadlocks
Examine PostgreSQL log entries containing `deadlock detected` to identify conflicting statements and application modules.

## Remediation Steps

### Step 1: Cancel or Terminate the Blocker
First attempt graceful query cancellation of the blocking session:
```sql
SELECT pg_cancel_backend(blocking_pid);
```
If the blocking backend does not release the lock within 15 seconds, terminate it:
```sql
SELECT pg_terminate_backend(blocking_pid);
```

### Step 2: Set Lock and Statement Timeouts
Prevent transactions from hanging indefinitely behind locks:
```sql
ALTER SYSTEM SET lock_timeout = '5s';
ALTER SYSTEM SET statement_timeout = '30s';
SELECT pg_reload_conf();
```

### Step 3: Application Remediation
Ensure application transactions consistently acquire locks in uniform canonical order (e.g., sort IDs before batch `SELECT ... FOR UPDATE`). Add missing indexes on foreign keys.

## Escalation Criteria
- If lock contention affects core business tables and query termination fails to unblock locks, page secondary database engineer (`page-secondary`).
- If deadlocks cause widespread transaction rollback cascade across core customer paths, escalate to Incident Commander (`incident-commander`).
