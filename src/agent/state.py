"""Typed states, hand-off contracts, and diagnostic output models for LangGraph reasoning (F3, A1, A2)."""

from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

CauseClass = Literal[
    "saturation",
    "contention",
    "configuration",
    "dependency_failure",
    "data_volume",
]

SeverityLevel = Literal["SEV1", "SEV2", "SEV3", "SEV4"]

RoutingTarget = Literal["self-serve runbook", "page-secondary", "incident-commander"]


class Citation(BaseModel):
    """Grounding citation linking advisory claims to retrieved documentation or runbooks."""

    section_id: str = Field(
        ..., description="Corpus section identifier (e.g. wal_slots#remediation)."
    )
    quoted_span: str = Field(..., description="Exact quoted text fragment from the cited section.")


class TriageHandOff(BaseModel):
    """Explicit typed hand-off contract passed from Triage Agent to Investigator Agent."""

    alert_name: str = Field(..., description="Canonical alert name.")
    primary_cause_class: CauseClass = Field(
        ...,
        description="Initial primary hypothesis cause classification.",
    )
    candidate_cause_classes: list[CauseClass] = Field(
        default_factory=list,
        description="Ranked candidate cause categories considered during symptom triage.",
    )
    extracted_entities: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted metrics, systems, failure hints, and operational variables.",
    )
    reasoning_summary: str = Field(
        ...,
        description="Synthesized symptom reasoning explaining the hypothesis.",
    )
    suggested_queries: list[str] = Field(
        default_factory=list,
        description="Targeted search queries for the Investigator agent.",
    )
    prompt_version: str = Field(
        default="triage-v1.0.0",
        description="Version identifier of the prompt used for triage.",
    )


class ToolExecutionTrace(BaseModel):
    """Audit trace entry recording an active tool call executed by the agent."""

    tool_name: str
    arguments: dict[str, Any]
    result_summary: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class VerificationResult(BaseModel):
    """Result of citation resolution, claim support, and corpus boundary verification."""

    is_verified: bool = Field(..., description="Whether the output passed all verification checks.")
    citation_errors: list[str] = Field(
        default_factory=list,
        description="Errors for citations failing to resolve to retrieved text.",
    )
    support_errors: list[str] = Field(
        default_factory=list, description="Errors where cited text does not support the claim."
    )
    ambiguity_detected: bool = Field(
        default=False,
        description="Whether symptom matches multiple cause classes with similar support.",
    )
    out_of_corpus: bool = Field(
        default=False, description="Whether alert symptoms fall outside the indexed corpus."
    )
    escalation_required: bool = Field(
        default=False, description="Whether human escalation is required."
    )
    escalation_route: RoutingTarget | None = Field(
        default=None, description="Target human route for escalation."
    )
    escalation_reason: str | None = Field(
        default=None, description="Explicit stated rationale for human escalation."
    )


class InvestigationOutput(BaseModel):
    """Structured advisory output produced by the multi-agent reasoning layer."""

    cause_class: CauseClass = Field(
        ...,
        description="Categorical root cause classification.",
    )
    first_response_steps: list[str] = Field(
        ...,
        description="Ordered, non-destructive diagnostic and first-response instructions.",
    )
    citations: list[Citation] = Field(
        ...,
        description="List of verified citations linking proposed steps to source text.",
    )
    severity: SeverityLevel = Field(
        ...,
        description="Determined operational severity (SEV1-SEV4).",
    )
    severity_basis: str = Field(
        ...,
        description="Rationale justifying the assigned severity level under escalation policy.",
    )
    route: RoutingTarget = Field(
        ...,
        description="Operational routing destination (self-serve runbook | page-secondary | incident-commander).",
    )
    verified: bool = Field(
        default=False,
        description="Whether every citation and claim passed mandatory verifier checks.",
    )
    escalation_reason: str | None = Field(
        default=None,
        description="Stated operational reason when escalation to a human is required.",
    )
    trace: list[str] = Field(
        default_factory=list,
        description="Chronological reasoning and tool call trace.",
    )
    retrieved_passages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Retrieved documentation excerpts used to synthesize guidance.",
    )
    prompt_version: str = Field(
        default="investigator-v1.0.0",
        description="Version identifier of the prompt used for investigation.",
    )


class AgentState(TypedDict):
    """LangGraph shared state dictionary passing through graph execution."""

    alert: dict[str, Any]
    triage_handoff: TriageHandOff | None
    tool_traces: list[ToolExecutionTrace]
    retrieved_passages: list[dict[str, Any]]
    step_count: int
    tool_call_count: int
    start_time: float
    max_steps: int
    max_tool_calls: int
    wall_clock_timeout_seconds: float
    final_output: InvestigationOutput | None
    verification_result: VerificationResult | None
    verification_retry_count: int
    error: str | None
    fallback_triggered: bool
