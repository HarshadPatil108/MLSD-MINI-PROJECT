# Runbook: PostgreSQL Inactive Replication Slot WAL Accumulation

## Overview and Symptom
A primary PostgreSQL database node experiences sudden or steady disk utilization growth in the `pg_wal` directory. Disk space alerts trigger as disk usage crosses warning (80%) and critical (90%) thresholds.

### Symptoms
- Disk space critical alert on primary PostgreSQL host.
- Rapid growth of `pg_wal` storage volume.
- Metric `replication_lag_bytes` increasing monotonically.
- Write operations stalling or threatened by impending disk exhaustion (read-only filesystem risk).

## Root Cause Analysis
Write-ahead log (WAL) segments are retained on the primary server when a replication slot is configured, because PostgreSQL guarantees that WAL needed by any existing replication slot will not be removed before the slot consumes it.
If a downstream replica, logical replication subscriber, or data pipeline (e.g. Debezium, Kafka connect, backup tool) disconnects or fails without dropping its replication slot:
1. The replication slot becomes inactive (`active = false` in `pg_replication_slots`).
2. The slot's `restart_lsn` stops advancing.
3. PostgreSQL checkpoint processes cannot purge or recycle WAL segments created after `restart_lsn`.
4. WAL files accumulate in `pg_wal` until disk space is exhausted.

## Diagnostic Procedures

### 1. Identify Inactive Replication Slots and Retained WAL
Execute the following diagnostic query on the primary database:
```sql
SELECT
    slot_name,
    plugin,
    slot_type,
    active,
    restart_lsn,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal_bytes
FROM pg_replication_slots
ORDER BY pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) DESC;
```

### 2. Verify If Slot Is Active or Abandoned
Check whether the slot has been inactive for an extended duration:
```sql
SELECT
    slot_name,
    active,
    active_pid,
    wal_status
FROM pg_replication_slots
WHERE active = false;
```
If `active = false` and `wal_status = 'extended'` or `retained_wal_bytes` matches the disk deficit, this confirms an abandoned replication slot is the root cause.

## Remediation Steps

### Step 1: Drop the Inactive Replication Slot
Once the slot is confirmed inactive and authorized for removal, execute:
```sql
SELECT pg_drop_replication_slot('slot_name_here');
```

### Step 2: Trigger Checkpoint to Free Disk Space
Force a database checkpoint to immediately recycle retained WAL files:
```sql
CHECKPOINT;
```
Verify disk space recovery on the underlying filesystem:
```bash
df -h /var/lib/postgresql/data/pg_wal
```

### Step 3: Configure Safety Safeguards
To prevent recurrence, set `max_slot_wal_keep_size` in `postgresql.conf`:
```text
# Limit WAL retention for any slot to 10GB
max_slot_wal_keep_size = 10GB
```
Reload PostgreSQL configuration:
```sql
SELECT pg_reload_conf();
```

## Escalation Criteria
- If multiple replication slots are inactive and represent critical production read-replicas, page secondary engineer (`page-secondary`).
- If disk utilization exceeds 95% and disk space is within 10 minutes of complete exhaustion, escalate immediately to Incident Commander (`incident-commander`).
- If dropping the slot does not recover disk space, check for failed archiving commands (`archive_mode`).
