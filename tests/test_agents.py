"""Comprehensive unit and acceptance tests for LangGraph multi-agent reasoning layer (F3, A1, A2)."""

import time
from typing import Any

import pytest

from src.agent.graph import run_multi_agent_triage
from src.agent.state import AgentState, TriageHandOff
from src.agent.tools import AgentToolExecutor, ToolExecutionError
from src.agent.triage import TriageAgent
from src.gateway.client import GatewayResponseCache


@pytest.fixture
def section_4_1_alert() -> dict[str, Any]:
    """Authoritative Section 4.1 scenario: Replication slot WAL accumulation."""
    return {
        "alert_id": "alert-wal-sec41",
        "alert_name": "PostgresWalAccumulationWarning",
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


def test_triage_agent_cause_classification_and_entities(section_4_1_alert):
    """Test Triage Agent classifies cause class and extracts entities into typed TriageHandOff."""
    agent = TriageAgent()
    handoff: TriageHandOff = agent.run(section_4_1_alert)

    assert isinstance(handoff, TriageHandOff)
    assert handoff.alert_name == "PostgresWalAccumulationWarning"
    assert handoff.primary_cause_class == "saturation"
    assert "configuration" in handoff.candidate_cause_classes
    assert handoff.extracted_entities["metrics"]["disk_utilization"] == 88.5
    assert len(handoff.suggested_queries) > 0
    assert handoff.prompt_version == "triage-v1.0.0"


def test_investigator_tools_and_bounds(section_4_1_alert):
    """Test tools and verify bounded execution prevents runaway tool loops."""
    executor = AgentToolExecutor()
    state: AgentState = {
        "alert": section_4_1_alert,
        "triage_handoff": None,
        "tool_traces": [],
        "retrieved_passages": [],
        "step_count": 0,
        "tool_call_count": 0,
        "start_time": time.time(),
        "max_steps": 5,
        "max_tool_calls": 3,  # Strict limit for testing
        "wall_clock_timeout_seconds": 30.0,
        "final_output": None,
        "error": None,
        "fallback_triggered": False,
    }

    # 1. get_alert_field
    field_res = executor.get_alert_field(state, "metrics")
    assert field_res["value"]["disk_utilization"] == 88.5
    assert state["tool_call_count"] == 1

    # 2. corpus_search
    hits = executor.corpus_search(state, query="replication slot WAL accumulation")
    assert len(hits) > 0
    assert state["tool_call_count"] == 2

    # 3. get_section
    sec_id = hits[0]["section_id"]
    sec_data = executor.get_section(state, section_id=sec_id)
    assert "content" in sec_data
    assert state["tool_call_count"] == 3

    # 4. Next tool call must trip max_tool_calls limit
    with pytest.raises(ToolExecutionError) as exc:
        executor.get_alert_field(state, "source")
    assert "Maximum tool calls exceeded" in str(exc.value)


def test_investigator_wall_clock_timeout(section_4_1_alert):
    """Test wall-clock timeout bounds."""
    executor = AgentToolExecutor()
    state: AgentState = {
        "alert": section_4_1_alert,
        "triage_handoff": None,
        "tool_traces": [],
        "retrieved_passages": [],
        "step_count": 0,
        "tool_call_count": 0,
        "start_time": time.time() - 35.0,  # Elapsed 35s
        "max_steps": 5,
        "max_tool_calls": 8,
        "wall_clock_timeout_seconds": 30.0,
        "final_output": None,
        "error": None,
        "fallback_triggered": False,
    }

    with pytest.raises(ToolExecutionError) as exc:
        executor.corpus_search(state, query="test timeout")
    assert "Wall-clock timeout exceeded" in str(exc.value)


def test_fallback_node_triggered_on_midrun_failure():
    """Test that a mid-run error transitions to the fallback node and pages secondary."""
    broken_alert = {
        "alert_name": "BrokenAlert",
        "metrics": {},
    }
    # Pass 0.0s timeout to force immediate timeout bound trip
    result = run_multi_agent_triage(
        broken_alert,
        max_steps=1,
        max_tool_calls=1,
        wall_clock_timeout_seconds=0.0001,
    )

    assert result["fallback_triggered"] is True
    output = result["final_output"]
    assert output is not None
    assert output.route == "page-secondary"
    assert output.severity == "SEV2"
    assert "aborted mid-run" in output.first_response_steps[0]


def test_gateway_cache_and_prompt_version(tmp_path):
    """Test LiteLLM gateway caching and prompt version tracking."""
    cache_path = str(tmp_path / "test_cache.db")
    cache = GatewayResponseCache(db_path=cache_path)

    cache.set(
        cache_key="key1",
        prompt_version="triage-v1.0.0",
        model="test-model",
        response_json='{"status": "ok"}',
    )
    assert cache.get("key1") == '{"status": "ok"}'
    assert cache.get("key_missing") is None


def test_section_4_1_acceptance_replication_slot_scenario(section_4_1_alert, capsys):
    """Acceptance Test: Section 4.1 scenario reaches replication-slot cause with citations to replication slot docs."""
    result = run_multi_agent_triage(section_4_1_alert)

    assert result["fallback_triggered"] is False
    output = result["final_output"]
    assert output is not None

    # 1. Verify cause class is saturation
    assert output.cause_class == "saturation"

    # 2. Verify first-response steps address the replication slot
    steps_text = " ".join(output.first_response_steps)
    assert "pg_replication_slots" in steps_text or "pg_drop_replication_slot" in steps_text

    # 3. Verify citations ground in replication slot documentation/runbook
    assert len(output.citations) >= 1
    has_replication_citation = any(
        "slot" in c.section_id.lower()
        or "wal" in c.section_id.lower()
        or "slot" in c.quoted_span.lower()
        or "checkpoint" in c.quoted_span.lower()
        for c in output.citations
    )
    assert has_replication_citation, (
        f"Citations did not reference replication slot docs: {output.citations}"
    )

    # 4. Verify severity and route
    assert output.severity in ["SEV1", "SEV2"]
    assert output.route in ["self-serve runbook", "page-secondary", "incident-commander"]

    # 5. Print retrieved passages and trace for demonstration
    with capsys.disabled():
        print("\n" + "=" * 70)
        print("SECTION 4.1 ACCEPTANCE RUN TRACE & RETRIEVED PASSAGES")
        print("=" * 70)
        print(f"Cause Class: {output.cause_class}")
        print(f"Severity:    {output.severity} ({output.severity_basis})")
        print(f"Route:       {output.route}")
        print("\n--- FIRST RESPONSE STEPS ---")
        for s in output.first_response_steps:
            print(f"  {s}")

        print("\n--- VERIFIED CITATIONS ---")
        for c in output.citations:
            print(f'  [Section: {c.section_id}] Quote: "{c.quoted_span}"')

        print("\n--- EXECUTION TRACE ---")
        for t in output.trace:
            print(f"  {t}")

        print("\n--- RETRIEVED PASSAGES ---")
        for idx, p in enumerate(output.retrieved_passages[:3], start=1):
            print(f"  [Passage {idx}: {p.get('header_path', 'No Header')}]")
            print(f"  {p.get('content', '')[:200]}...")
        print("=" * 70 + "\n")
