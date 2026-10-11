"""Triage Agent for symptom analysis, entity extraction, and cause class hypothesis (A1)."""

import logging
from typing import Any

from src.agent.state import CauseClass, TriageHandOff
from src.gateway.client import get_llm_gateway

logger = logging.getLogger(__name__)

PROMPT_VERSION_TRIAGE = "triage-v1.0.0"

SYSTEM_PROMPT_TRIAGE = """You are an expert PostgreSQL SRE Triage Agent.
Your role is to analyze incoming alert payloads and on-call notes to:
1. Categorize the primary cause class into strictly one of:
   - saturation: Resource capacity exhausted (disk full, memory full, CPU 100%, connection starvation).
   - contention: Conflicting concurrency or lock blocks (deadlocks, row lock wait queues).
   - configuration: Misconfigured parameters or unconfigured limits (max_slot_wal_keep_size, idle_in_transaction_timeout).
   - dependency_failure: External component failure (network partition, backup server unreachable).
   - data_volume: Unexpected query volume or unindexed scan volume.
2. Extract operational entities (metrics, thresholds, replica names, symptoms).
3. Synthesize candidate causes and formulate initial search queries for the investigator agent.

You MUST produce output strictly matching the TriageHandOff schema.
"""


def default_deterministic_triage(alert: dict[str, Any]) -> TriageHandOff:
    """Deterministic fallback triage analyzer based on alert symptoms and metrics."""
    alert_name = str(alert.get("alert_name", "UnknownAlert"))
    metrics = alert.get("metrics", {})
    note = str(alert.get("on_call_note", "")).lower()

    entities = {
        "source": alert.get("source", "unknown"),
        "pg_version": alert.get("pg_version", "18"),
        "severity_hint": alert.get("severity_hint", "WARNING"),
        "metrics": metrics,
    }

    # Case 1: WAL / Disk / Replication slot symptoms
    if (
        "wal" in alert_name.lower()
        or "lag" in alert_name.lower()
        or "disk" in note
        or "wal" in note
        or "replication" in note
        or "replication_lag_bytes" in metrics
        or "disk_utilization" in metrics
    ):
        primary: CauseClass = "saturation"
        candidates: list[CauseClass] = ["saturation", "configuration", "data_volume"]
        reasoning = (
            f"Alert '{alert_name}' indicates storage capacity saturation in pg_wal volume. "
            f"Note reports: '{note}'. Symptoms indicate write-ahead log retention, likely caused "
            "by an inactive replication slot holding restart_lsn or unconfigured max_slot_wal_keep_size."
        )
        queries = [
            "PostgreSQL Inactive Replication Slot WAL Accumulation",
            "pg_replication_slots active false restart_lsn retained WAL",
            "max_slot_wal_keep_size checkpoint",
        ]

    # Case 2: Connection Pool Saturation
    elif (
        "connection" in alert_name.lower()
        or "pool" in note
        or "active_connections" in metrics
        or "connection_count" in metrics
    ):
        primary = "saturation"
        candidates = ["saturation", "contention", "configuration"]
        reasoning = (
            f"Alert '{alert_name}' indicates backend worker saturation. "
            f"Active connections approaching max_connections. Suspected connection pool leak or idle in transaction backlog."
        )
        queries = [
            "PostgreSQL Connection Pool Saturation and Starvation",
            "idle in transaction pg_stat_activity terminate backend",
            "max_connections idle_in_transaction_session_timeout",
        ]

    # Case 3: Lock contention & deadlocks
    elif "deadlock" in alert_name.lower() or "lock" in note or "deadlocks_per_second" in metrics:
        primary = "contention"
        candidates = ["contention", "saturation"]
        reasoning = (
            f"Alert '{alert_name}' indicates concurrency lock contention. "
            f"Deadlock events or transaction serialization blocks detected."
        )
        queries = [
            "PostgreSQL Lock Contention and Serialization Deadlocks",
            "pg_locks blocked queries blocking_pid",
            "lock_timeout statement_timeout",
        ]

    else:
        primary = "configuration"
        candidates = ["configuration", "saturation", "dependency_failure"]
        reasoning = (
            f"Alert '{alert_name}' requires operational investigation into parameters and symptoms."
        )
        queries = [
            f"{alert_name} PostgreSQL",
            "PostgreSQL monitoring activity",
        ]

    return TriageHandOff(
        alert_name=alert_name,
        primary_cause_class=primary,
        candidate_cause_classes=candidates,
        extracted_entities=entities,
        reasoning_summary=reasoning,
        suggested_queries=queries,
        prompt_version=PROMPT_VERSION_TRIAGE,
    )


class TriageAgent:
    """Agent executing initial symptom triage and typed hand-off formulation."""

    def __init__(self, prompt_version: str = PROMPT_VERSION_TRIAGE):
        self.prompt_version = prompt_version
        self.gateway = get_llm_gateway()

    def run(self, alert: dict[str, Any]) -> TriageHandOff:
        """Run triage analysis on incoming alert."""
        prompt = (
            f"Alert Name: {alert.get('alert_name')}\n"
            f"Source: {alert.get('source')}\n"
            f"PostgreSQL Version: {alert.get('pg_version')}\n"
            f"Severity Hint: {alert.get('severity_hint')}\n"
            f"Metrics: {alert.get('metrics')}\n"
            f"On-Call Note: {alert.get('on_call_note')}\n"
            f"Tags: {alert.get('tags')}\n"
        )

        try:
            # If in mock/test mode or fallback, gateway handles or raises
            return self.gateway.call_structured(
                prompt=prompt,
                response_model=TriageHandOff,
                system_prompt=SYSTEM_PROMPT_TRIAGE,
                prompt_version=self.prompt_version,
            )
        except Exception as exc:  # noqa: BLE001 - Resilient fallback to deterministic triage on gateway failure
            logger.info("Using deterministic triage fallback analyzer (%s)", exc)
            return default_deterministic_triage(alert)
