"""LangGraph multi-agent topology: Triage -> Investigator with deterministic fallback (F3, A1, A2)."""

import logging
import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agent.investigator import InvestigatorAgent
from src.agent.state import (
    AgentState,
    CauseClass,
    InvestigationOutput,
)
from src.agent.triage import TriageAgent

logger = logging.getLogger(__name__)


def triage_node(state: AgentState) -> dict[str, Any]:
    """Execute Triage Agent node to hypothesize cause class and extract entities."""
    try:
        agent = TriageAgent()
        handoff = agent.run(state["alert"])
        return {
            "triage_handoff": handoff,
            "fallback_triggered": False,
        }
    except Exception as exc:  # noqa: BLE001 - Graph fallback boundary catching all node errors to preserve pipeline resilience
        logger.error("Triage node failed: %s", exc)
        return {
            "error": f"Triage node failure: {exc}",
            "fallback_triggered": True,
        }


def investigator_node(state: AgentState) -> dict[str, Any]:
    """Execute Investigator Agent node to conduct bounded multi-hop tool searches and synthesize guidance."""
    try:
        agent = InvestigatorAgent()
        output = agent.run_investigation(state)
        return {
            "final_output": output,
            "fallback_triggered": False,
        }
    except Exception as exc:  # noqa: BLE001 - Graph fallback boundary catching all node errors to preserve pipeline resilience
        logger.error("Investigator node failed: %s", exc)
        return {
            "error": f"Investigator node failure: {exc}",
            "fallback_triggered": True,
        }


def fallback_node(state: AgentState) -> dict[str, Any]:
    """Fallback node triggered when any agent fails mid-run (timeouts, tool errors, circuit trips).

    Guarantees deterministic safe escalation: routes immediately to 'page-secondary' with SEV2.
    """
    logger.warning("Executing fallback escalation node due to: %s", state.get("error"))

    triage = state.get("triage_handoff")
    cause: CauseClass = triage.primary_cause_class if triage else "saturation"
    err_msg = state.get("error", "Unknown error mid-run")

    fallback_output = InvestigationOutput(
        cause_class=cause,
        first_response_steps=[
            "1. Automated agent reasoning aborted mid-run due to an error/timeout.",
            "2. Secondary database on-call engineer paged immediately for manual diagnostic review.",
            f"3. Root cause diagnostic error: {err_msg}",
        ],
        citations=[],
        severity="SEV2",
        severity_basis="Agent execution failure triggers deterministic safe escalation to secondary on-call.",
        route="page-secondary",
        trace=[
            f"Fallback triggered: {err_msg}",
            "Routed directly to page-secondary under failure safety invariant.",
        ],
        retrieved_passages=state.get("retrieved_passages", []),
        prompt_version="fallback-v1.0.0",
    )

    return {
        "final_output": fallback_output,
        "fallback_triggered": True,
    }


def route_after_triage(state: AgentState) -> str:
    """Conditional router after triage: proceed to investigator or abort to fallback."""
    if state.get("fallback_triggered") or state.get("error"):
        return "fallback"
    return "investigator"


def route_after_investigator(state: AgentState) -> str:
    """Conditional router after investigator: complete run or abort to fallback."""
    if state.get("fallback_triggered") or state.get("error"):
        return "fallback"
    return END


def build_incidentops_graph() -> Any:
    """Construct and compile the LangGraph multi-agent workflow."""
    workflow = StateGraph(AgentState)

    # 1. Add Nodes
    workflow.add_node("triage", triage_node)
    workflow.add_node("investigator", investigator_node)
    workflow.add_node("fallback", fallback_node)

    # 2. Add Edges
    workflow.add_edge(START, "triage")

    workflow.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "investigator": "investigator",
            "fallback": "fallback",
        },
    )

    workflow.add_conditional_edges(
        "investigator",
        route_after_investigator,
        {
            END: END,
            "fallback": "fallback",
        },
    )

    workflow.add_edge("fallback", END)

    return workflow.compile()


# Compiled singleton graph
_compiled_graph: Any | None = None


def get_agent_graph() -> Any:
    """Get compiled LangGraph executable."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_incidentops_graph()
    return _compiled_graph


def run_multi_agent_triage(
    alert: dict[str, Any],
    max_steps: int = 5,
    max_tool_calls: int = 8,
    wall_clock_timeout_seconds: float = 30.0,
) -> AgentState:
    """Entrypoint executing multi-agent reasoning over an alert."""
    initial_state: AgentState = {
        "alert": alert,
        "triage_handoff": None,
        "tool_traces": [],
        "retrieved_passages": [],
        "step_count": 0,
        "tool_call_count": 0,
        "start_time": time.time(),
        "max_steps": max_steps,
        "max_tool_calls": max_tool_calls,
        "wall_clock_timeout_seconds": wall_clock_timeout_seconds,
        "final_output": None,
        "error": None,
        "fallback_triggered": False,
    }

    graph = get_agent_graph()
    result = graph.invoke(initial_state)
    return result
