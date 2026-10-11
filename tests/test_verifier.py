"""Comprehensive unit and integration tests for Citation Verifier & Escalation Engine (A3, F5, F6, F7).

Covers:
(a) Section 4.1 scenario passes mandatory verification.
(b) Out-of-corpus alert triggers deterministic human escalation with stated reason.
(c) Forced bad citation is caught and triggers re-search or escalation.
(d) Multi-cause ambiguity (F7) triggers deterministic human escalation.
"""

from typing import Any

import pytest

from src.agent.graph import run_multi_agent_triage
from src.agent.state import AgentState, Citation, InvestigationOutput
from src.agent.verifier import CitationVerifier


@pytest.fixture
def section_4_1_alert() -> dict[str, Any]:
    """Authoritative Section 4.1 scenario: Replication slot WAL accumulation."""
    return {
        "alert_id": "alert-wal-sec41",
        "alert_name": "PostgresWalAccumulationWarning",
        "service": "postgres-primary",
        "source": "prometheus",
        "fired_at": "2026-10-10T22:30:00Z",
        "metrics": {
            "disk_utilization": 88.5,
            "replication_lag_bytes": 104857600.0,
            "active_connections": 42.0,
        },
        "pg_version": "18.0",
        "severity_hint": "CRITICAL",
        "on_call_note": "Disk usage on primary node rapidly climbing in /pg_wal. Standby replica standby_1 had network blip earlier.",
        "tags": {"cluster": "prod-db-primary"},
    }


@pytest.fixture
def out_of_corpus_alert() -> dict[str, Any]:
    """Alert from an external technology outside PostgreSQL documentation and runbooks."""
    return {
        "alert_id": "alert-kafka-consumer-lag",
        "alert_name": "KafkaConsumerGroupLagCritical",
        "service": "kafka-cluster-prod",
        "source": "datadog",
        "fired_at": "2026-10-10T22:30:00Z",
        "metrics": {
            "consumer_lag_records": 750000.0,
            "partitions_under_replicated": 12.0,
        },
        "pg_version": "18.0",
        "severity_hint": "WARNING",
        "on_call_note": "Kafka consumer group billing-events lag is growing uncontrollably across 12 partitions.",
        "tags": {"cluster": "prod-kafka"},
    }


# ==============================================================================
# (a) Section 4.1 passes verification
# ==============================================================================


def test_section_4_1_passes_verification(section_4_1_alert):
    """Test (a): Section 4.1 scenario passes mandatory verification.

    Verifies that every citation resolves to text actually retrieved in this run,
    and the cited text supports the diagnostic claims.
    """
    result = run_multi_agent_triage(section_4_1_alert)

    assert result["fallback_triggered"] is False
    output = result["final_output"]
    assert output is not None

    # 1. Output must be marked verified
    assert output.verified is True
    assert output.escalation_reason is None

    # 2. VerificationResult must be verified with no errors
    vres = result.get("verification_result")
    assert vres is not None
    assert vres.is_verified is True
    assert vres.citation_errors == []
    assert vres.support_errors == []
    assert vres.escalation_required is False

    # 3. Every citation must resolve to text actually present in retrieved_passages
    assert len(output.citations) >= 1
    retrieved_sections = {
        p.get("section_id", p.get("chunk_id", "")) for p in result["retrieved_passages"]
    }
    all_retrieved_content = " ".join(
        p.get("content", "") for p in result["retrieved_passages"]
    ).lower()

    for c in output.citations:
        assert c.section_id != ""
        assert c.quoted_span != ""
        assert any(c.section_id in s or s in c.section_id for s in retrieved_sections)
        # Check quoted text exists in retrieved content
        cleaned_quote = " ".join(c.quoted_span.split()).strip().lower()
        cleaned_quote = cleaned_quote.replace("'", "").replace('"', "").replace("`", "")
        cleaned_content = (
            " ".join(all_retrieved_content.split())
            .replace("'", "")
            .replace('"', "")
            .replace("`", "")
        )
        assert cleaned_quote in cleaned_content, (
            f"Citation quote '{c.quoted_span}' was not found in retrieved passages."
        )

    # 4. Route is not an unverified escalation
    assert output.route in ["self-serve runbook", "page-secondary", "incident-commander"]
    # Check trace includes mandatory verifier confirmation
    assert any("Mandatory Verifier: All citations resolved" in t for t in output.trace)


# ==============================================================================
# (b) Out-of-corpus alert escalates
# ==============================================================================


def test_out_of_corpus_alert_escalates(out_of_corpus_alert):
    """Test (b): An out-of-corpus alert escalates to human with stated reason.

    Never returns an unverified answer.
    """
    result = run_multi_agent_triage(out_of_corpus_alert)

    output = result["final_output"]
    assert output is not None

    # 1. Must never return an unverified advisory answer
    assert output.verified is False

    # 2. Must escalate to a human (page-secondary or incident-commander)
    assert output.route in ["page-secondary", "incident-commander"]

    # 3. Must contain an explicit stated reason
    assert output.escalation_reason is not None
    assert len(output.escalation_reason) > 10
    assert (
        "outside" in output.escalation_reason.lower()
        or "corpus" in output.escalation_reason.lower()
    )

    # 4. Verification result explicitly indicates out_of_corpus
    vres = result.get("verification_result")
    assert vres is not None
    assert vres.is_verified is False
    assert vres.out_of_corpus is True
    assert vres.escalation_required is True

    # 5. First response steps indicate human escalation
    assert any("escalated" in step.lower() for step in output.first_response_steps)


def test_out_of_corpus_critical_escalates_to_incident_commander():
    """Test that an out-of-corpus alert with CRITICAL severity escalates to incident-commander."""
    critical_ooc_alert = {
        "alert_id": "alert-redis-crit",
        "alert_name": "RedisClusterMemoryExhaustion",
        "service": "redis-cache",
        "source": "prometheus",
        "fired_at": "2026-10-10T22:30:00Z",
        "metrics": {"memory_utilization": 99.5},
        "pg_version": "18.0",
        "severity_hint": "CRITICAL",
        "on_call_note": "Redis cache node completely exhausted memory, rejecting all write commands.",
        "tags": {},
    }

    result = run_multi_agent_triage(critical_ooc_alert)
    output = result["final_output"]
    assert output is not None
    assert output.verified is False
    assert output.route == "incident-commander"
    assert output.severity == "SEV1"
    assert (
        "outside" in output.escalation_reason.lower()
        or "corpus" in output.escalation_reason.lower()
    )


# ==============================================================================
# (c) Forced bad citation is caught and triggers re-search or escalation
# ==============================================================================


def test_forced_bad_citation_caught_and_triggers_research_recovery(section_4_1_alert):
    """Test (c.1): A forced bad citation on initial run is caught and triggers re-search.

    Alternate strategy executes, discovers valid citations, and passes verification.
    """
    bad_citation_alert = dict(section_4_1_alert)
    # Hook triggers synthetic bad citation on initial run, then recovers on re-search
    bad_citation_alert["force_bad_citation"] = True
    bad_citation_alert["persist_bad_citation"] = False

    result = run_multi_agent_triage(bad_citation_alert)
    output = result["final_output"]
    assert output is not None

    # 1. Output passed verification after re-search retry
    assert output.verified is True
    assert result.get("verification_retry_count") == 1

    # 2. Trace confirms re-search with alternate strategy was executed
    trace_text = " ".join(output.trace)
    assert "alternate re-search strategy" in trace_text.lower()


def test_forced_bad_citation_persistent_triggers_escalation(section_4_1_alert):
    """Test (c.2): A forced bad citation that persists triggers re-search, then escalates to human.

    Never returns an unverified answer when citation cannot be resolved.
    """
    persistent_bad_alert = dict(section_4_1_alert)
    persistent_bad_alert["force_bad_citation"] = True
    persistent_bad_alert["persist_bad_citation"] = True  # Persists on re-search

    result = run_multi_agent_triage(persistent_bad_alert)
    output = result["final_output"]
    assert output is not None

    # 1. Must never return an unverified answer
    assert output.verified is False

    # 2. Must escalate to human with stated reason
    assert output.route in ["page-secondary", "incident-commander"]
    assert output.escalation_reason is not None
    assert (
        "verification failed" in output.escalation_reason.lower()
        or "citation" in output.escalation_reason.lower()
    )

    # 3. Retry count reflects that re-search was attempted once
    assert result.get("verification_retry_count") >= 1


# ==============================================================================
# (d) Multi-cause ambiguity (F7) triggers deterministic escalation
# ==============================================================================


def test_multi_cause_ambiguity_triggers_escalation(section_4_1_alert):
    """Test (d): Symptom mapping to several cause classes with similar support escalates to human."""
    ambiguous_alert = dict(section_4_1_alert)
    ambiguous_alert["tags"] = {"force_ambiguous_causes": "true"}

    result = run_multi_agent_triage(ambiguous_alert)
    output = result["final_output"]
    assert output is not None

    assert output.verified is False
    assert output.route in ["page-secondary", "incident-commander"]
    assert output.escalation_reason is not None
    assert (
        "multiple cause classes" in output.escalation_reason.lower()
        or "ambiguous" in output.escalation_reason.lower()
    )


# ==============================================================================
# Unit tests for CitationVerifier edge cases
# ==============================================================================


def test_citation_verifier_detects_nonexistent_section():
    """Unit test: Citation with fabricated section_id fails resolution."""
    verifier = CitationVerifier()
    mock_state: AgentState = {
        "alert": {"alert_name": "TestAlert", "pg_version": "18.0"},
        "triage_handoff": None,
        "tool_traces": [],
        "retrieved_passages": [
            {
                "section_id": "wal_slots#section_1",
                "chunk_id": "wal_slots#section_1",
                "content": "This is legitimate postgres documentation content.",
                "header_path": "Replication > Slots",
            }
        ],
        "step_count": 1,
        "tool_call_count": 1,
        "start_time": 0.0,
        "max_steps": 5,
        "max_tool_calls": 5,
        "wall_clock_timeout_seconds": 30.0,
        "final_output": InvestigationOutput(
            cause_class="saturation",
            first_response_steps=["Step 1"],
            citations=[
                Citation(
                    section_id="completely_fictitious_section_99",
                    quoted_span="legitimate postgres documentation",
                )
            ],
            severity="SEV2",
            severity_basis="test",
            route="self-serve runbook",
        ),
        "verification_result": None,
        "verification_retry_count": 0,
        "error": None,
        "fallback_triggered": False,
    }

    vres = verifier.verify(mock_state)
    assert vres.is_verified is False
    assert len(vres.citation_errors) >= 1
    assert "does not resolve" in vres.citation_errors[0]


def test_citation_verifier_detects_quote_mismatch():
    """Unit test: Citation pointing to valid section but citing fabricated text fails resolution."""
    verifier = CitationVerifier()
    mock_state: AgentState = {
        "alert": {"alert_name": "TestAlert", "pg_version": "18.0"},
        "triage_handoff": None,
        "tool_traces": [],
        "retrieved_passages": [
            {
                "section_id": "wal_slots#section_1",
                "chunk_id": "wal_slots#section_1",
                "content": "This is legitimate postgres documentation content.",
                "header_path": "Replication > Slots",
            }
        ],
        "step_count": 1,
        "tool_call_count": 1,
        "start_time": 0.0,
        "max_steps": 5,
        "max_tool_calls": 5,
        "wall_clock_timeout_seconds": 30.0,
        "final_output": InvestigationOutput(
            cause_class="saturation",
            first_response_steps=["Step 1"],
            citations=[
                Citation(
                    section_id="wal_slots#section_1",
                    quoted_span="Fabricated text never written in this section at all.",
                )
            ],
            severity="SEV2",
            severity_basis="test",
            route="self-serve runbook",
        ),
        "verification_result": None,
        "verification_retry_count": 0,
        "error": None,
        "fallback_triggered": False,
    }

    vres = verifier.verify(mock_state)
    assert vres.is_verified is False
    assert len(vres.citation_errors) >= 1
    assert "was not found" in vres.citation_errors[0]


def test_citation_verifier_rejects_empty_citations_for_active_steps():
    """Unit test: Output with active advice but 0 citations is rejected."""
    verifier = CitationVerifier()
    mock_state: AgentState = {
        "alert": {"alert_name": "TestAlert", "pg_version": "18.0"},
        "triage_handoff": None,
        "tool_traces": [],
        "retrieved_passages": [
            {
                "section_id": "wal_slots#section_1",
                "chunk_id": "wal_slots#section_1",
                "content": "This is legitimate postgres documentation content.",
                "header_path": "Replication > Slots",
            }
        ],
        "step_count": 1,
        "tool_call_count": 1,
        "start_time": 0.0,
        "max_steps": 5,
        "max_tool_calls": 5,
        "wall_clock_timeout_seconds": 30.0,
        "final_output": InvestigationOutput(
            cause_class="saturation",
            first_response_steps=["1. Drop the database right now."],
            citations=[],  # Empty!
            severity="SEV2",
            severity_basis="test",
            route="self-serve runbook",
        ),
        "verification_result": None,
        "verification_retry_count": 0,
        "error": None,
        "fallback_triggered": False,
    }

    vres = verifier.verify(mock_state)
    assert vres.is_verified is False
    assert any("without any supporting citations" in err for err in vres.citation_errors)
