"""LangGraph multi-agent topology: Triage -> Investigator -> Verifier with deterministic fallback (F3, A1, A2, A3, F7)."""

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
from src.agent.verifier import CitationVerifier
from src.guardrails.injection import get_injection_guardrail

logger = logging.getLogger(__name__)


def triage_node(state: AgentState) -> dict[str, Any]:
    """Execute Triage Agent node to hypothesize cause class and extract entities."""
    try:
        guardrail = get_injection_guardrail()
        scan = guardrail.scan_alert(state["alert"])
        if scan.is_injection:
            logger.warning("Prompt injection detected in triage node: %s", scan.quarantine_reason)
            escalated_output = InvestigationOutput(
                cause_class="configuration",
                first_response_steps=[
                    "1. Security guardrail intercepted untrusted input.",
                    f"2. {scan.quarantine_reason}",
                    "3. Incident routed immediately to page-secondary for manual security and operational review.",
                ],
                citations=[],
                severity="SEV2",
                severity_basis="Security guardrail violation: prompt injection detected.",
                route="page-secondary",
                verified=False,
                escalation_reason=scan.quarantine_reason,
                trace=["Guardrail: Prompt injection detected; automated reasoning suppressed."],
                retrieved_passages=[],
                prompt_version="guardrail-v1.0.0",
            )
            return {
                "final_output": escalated_output,
                "error": None,
                "fallback_triggered": False,
            }

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


def verifier_node(state: AgentState) -> dict[str, Any]:
    """Execute Mandatory Verifier (A3, F7) checking citations, claims, and corpus boundaries."""
    try:
        verifier = CitationVerifier()
        result = verifier.verify(state)
        output = state.get("final_output")

        if result.is_verified and output:
            output.verified = True
            output.trace.append(
                "Mandatory Verifier: All citations resolved to retrieved text and claims supported."
            )
            return {
                "verification_result": result,
                "final_output": output,
                "fallback_triggered": False,
            }

        return {
            "verification_result": result,
            "fallback_triggered": False,
        }
    except Exception as exc:  # noqa: BLE001 - Resilient boundary
        logger.error("Verifier node failed: %s", exc)
        return {
            "error": f"Verifier node failure: {exc}",
            "fallback_triggered": True,
        }


def research_node(state: AgentState) -> dict[str, Any]:
    """Execute alternate retrieval strategy upon verification failure (A3)."""
    try:
        agent = InvestigatorAgent()
        current_retries = state.get("verification_retry_count", 0)
        state["verification_retry_count"] = current_retries + 1
        new_output = agent.re_search_with_alternate_strategy(state)
        return {
            "final_output": new_output,
            "verification_retry_count": state["verification_retry_count"],
            "fallback_triggered": False,
        }
    except Exception as exc:  # noqa: BLE001 - Resilient boundary
        logger.error("Research node failed: %s", exc)
        return {
            "error": f"Research node failure: {exc}",
            "fallback_triggered": True,
        }


def escalate_node(state: AgentState) -> dict[str, Any]:
    """Deterministic human escalation node (F7) when run is ambiguous, out-of-corpus, or ungrounded."""
    try:
        verifier = CitationVerifier()
        vres = state.get("verification_result")
        reason = (
            vres.escalation_reason
            if vres and vres.escalation_reason
            else "Mandatory verification failure: citations or claims could not be grounded."
        )
        route = vres.escalation_route if vres and vres.escalation_route else "page-secondary"
        escalated_output = verifier.build_escalated_output(
            original_output=state.get("final_output"),
            reason=reason,
            route=route,
        )
        return {
            "final_output": escalated_output,
            "fallback_triggered": False,
        }
    except Exception as exc:  # noqa: BLE001 - Resilient boundary
        logger.error("Escalate node failed: %s", exc)
        return {
            "error": f"Escalate node failure: {exc}",
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
        verified=False,
        escalation_reason=f"Pipeline exception mid-run: {err_msg}",
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
    if state.get("final_output") is not None:
        return END
    return "investigator"


def route_after_investigator(state: AgentState) -> str:
    """Conditional router after investigator: proceed to verifier or abort to fallback."""
    if state.get("fallback_triggered") or state.get("error"):
        return "fallback"
    return "verifier"


def route_after_verifier(state: AgentState) -> str:
    """Conditional router after verifier: END on success, research on retry, escalate on failure."""
    if state.get("fallback_triggered") or state.get("error"):
        return "fallback"

    vres = state.get("verification_result")
    if vres and vres.is_verified:
        return END

    if vres and vres.escalation_required:
        return "escalate"

    # If verification failed and we haven't retried yet:
    if state.get("verification_retry_count", 0) < 1:
        return "research"

    return "escalate"


def build_incidentops_graph() -> Any:
    """Construct and compile the LangGraph multi-agent workflow."""
    workflow = StateGraph(AgentState)

    # 1. Add Nodes
    workflow.add_node("triage", triage_node)
    workflow.add_node("investigator", investigator_node)
    workflow.add_node("verifier", verifier_node)
    workflow.add_node("research", research_node)
    workflow.add_node("escalate", escalate_node)
    workflow.add_node("fallback", fallback_node)

    # 2. Add Edges
    workflow.add_edge(START, "triage")

    workflow.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "investigator": "investigator",
            "fallback": "fallback",
            END: END,
        },
    )

    workflow.add_conditional_edges(
        "investigator",
        route_after_investigator,
        {
            "verifier": "verifier",
            "fallback": "fallback",
        },
    )

    workflow.add_conditional_edges(
        "verifier",
        route_after_verifier,
        {
            END: END,
            "research": "research",
            "escalate": "escalate",
            "fallback": "fallback",
        },
    )

    # After research (alternate search), feed back into verifier
    workflow.add_edge("research", "verifier")

    workflow.add_edge("escalate", END)
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
        "verification_result": None,
        "verification_retry_count": 0,
        "error": None,
        "fallback_triggered": False,
    }

    graph = get_agent_graph()
    result = graph.invoke(initial_state)
    return result
