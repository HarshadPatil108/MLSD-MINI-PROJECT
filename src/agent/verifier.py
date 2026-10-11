"""Citation Verifier and Escalation Engine (A3, F5, F6, F7).

Verifies that every citation resolves to text retrieved during this run,
ensures cited text supports the claims, detects multi-cause ambiguity and out-of-corpus alerts,
and enforces deterministic escalation to human on verification failure.
"""

import logging
import re
from typing import Any

from src.agent.state import (
    AgentState,
    CauseClass,
    InvestigationOutput,
    RoutingTarget,
    SeverityLevel,
    VerificationResult,
)
from src.gateway.client import get_llm_gateway

logger = logging.getLogger(__name__)

PROMPT_VERSION_VERIFIER = "verifier-v1.0.0"

# Known out-of-corpus non-PostgreSQL systems
OUT_OF_CORPUS_KEYWORDS = {
    "kafka",
    "redis",
    "rabbitmq",
    "elasticsearch",
    "opensearch",
    "cassandra",
    "mongodb",
    "dynamodb",
    "kubernetes",
    "k8s",
    "nginx",
    "envoy",
    "spark",
    "flink",
}


def normalize_text(text: str) -> str:
    """Normalize whitespace and punctuation for resilient quote matching."""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    # Remove minor quote characters that might differ
    return cleaned.replace("'", "").replace('"', "").replace("`", "")


class CitationVerifier:
    """Mandatory verification engine enforcing citation resolution, claim grounding, and escalation."""

    def __init__(self, prompt_version: str = PROMPT_VERSION_VERIFIER):
        self.prompt_version = prompt_version
        self.gateway = get_llm_gateway()

    def verify(self, state: AgentState) -> VerificationResult:
        """Run all mandatory verification checks on state['final_output']."""
        output: InvestigationOutput | None = state.get("final_output")
        alert: dict[str, Any] = state.get("alert", {})
        passages: list[dict[str, Any]] = state.get("retrieved_passages", [])

        if output is None:
            return VerificationResult(
                is_verified=False,
                citation_errors=["No final_output present to verify."],
                escalation_required=True,
                escalation_route="page-secondary",
                escalation_reason="Investigation produced no output to verify.",
            )

        # 1. Out-of-corpus check
        out_of_corpus, ooc_reason = self._check_out_of_corpus(alert, passages)
        if out_of_corpus:
            route = self._determine_escalation_route(alert, output.severity)
            return VerificationResult(
                is_verified=False,
                out_of_corpus=True,
                escalation_required=True,
                escalation_route=route,
                escalation_reason=ooc_reason,
            )

        # 2. Multi-cause ambiguity check (F7)
        is_ambiguous, amb_reason = self._check_multi_cause_ambiguity(state)
        if is_ambiguous:
            route = self._determine_escalation_route(alert, output.severity)
            return VerificationResult(
                is_verified=False,
                ambiguity_detected=True,
                escalation_required=True,
                escalation_route=route,
                escalation_reason=amb_reason,
            )

        # 3. Citation resolution check
        citation_errors = self._check_citation_resolution(output, passages)

        # 4. Claim support check
        support_errors = self._check_claim_support(output, passages)

        all_errors = citation_errors + support_errors
        is_verified = len(all_errors) == 0

        escalation_required = False
        escalation_route = None
        escalation_reason = None

        if not is_verified and state.get("verification_retry_count", 0) >= 1:
            # If retry limit reached, require escalation
            escalation_required = True
            escalation_route = self._determine_escalation_route(alert, output.severity)
            escalation_reason = (
                f"Citation verification failed after re-search retry: {'; '.join(all_errors)}"
            )

        return VerificationResult(
            is_verified=is_verified,
            citation_errors=citation_errors,
            support_errors=support_errors,
            ambiguity_detected=False,
            out_of_corpus=False,
            escalation_required=escalation_required,
            escalation_route=escalation_route,
            escalation_reason=escalation_reason,
        )

    def _check_out_of_corpus(
        self, alert: dict[str, Any], passages: list[dict[str, Any]]
    ) -> tuple[bool, str | None]:
        """Verify whether the alert falls outside the indexed PostgreSQL corpus."""
        alert_name = str(alert.get("alert_name", "")).lower()
        service = str(alert.get("service", "")).lower()
        note = str(alert.get("on_call_note", "")).lower()
        tags_str = " ".join(f"{k} {v}" for k, v in alert.get("tags", {}).items()).lower()
        combined_text = f"{alert_name} {service} {note} {tags_str}"

        # Check for explicitly non-PostgreSQL service or symptoms
        for kw in OUT_OF_CORPUS_KEYWORDS:
            if (
                re.search(rf"\b{re.escape(kw)}\b", combined_text)
                and "postgres" not in service
                and "postgres" not in alert_name
            ):
                return (
                    True,
                    f"Alert pertains to non-PostgreSQL system '{kw}' which falls outside the indexed corpus.",
                )

        # If zero passages were retrieved
        if not passages:
            return (
                True,
                "No documentation or runbook passages retrieved for this alert in corpus.",
            )

        # Check retrieval relevance: if all passages have near-zero scores
        scores = [p.get("score", 0.0) for p in passages if p.get("score") is not None]
        if scores and max(scores) < 0.005:
            return (
                True,
                "Retrieved passages had negligible semantic relevance (< 0.005) to alert symptoms.",
            )

        return False, None

    def _check_multi_cause_ambiguity(self, state: AgentState) -> tuple[bool, str | None]:
        """Detect if the symptom maps to several candidate cause classes with similar support (F7)."""
        triage = state.get("triage_handoff")
        alert = state.get("alert", {})
        metrics = alert.get("metrics", {})
        note = str(alert.get("on_call_note", "")).lower()

        # Check explicit ambiguity marker in triage or alert
        if alert.get("tags", {}).get("force_ambiguous_causes") == "true":
            return (
                True,
                "Symptom maps to multiple cause classes (saturation and contention) with equal support.",
            )

        # Detect conflicting concurrent symptoms with strong contradictory indicators
        has_deadlock = "deadlock" in note or metrics.get("deadlocks_per_second", 0) > 2.0
        has_wal_lag = (
            "wal" in note or metrics.get("replication_lag_bytes", 0) > 50_000_000 or "disk" in note
        )
        has_conn_exhaustion = "connection" in note or metrics.get("active_connections", 0) > 400

        # If more than one major failure signature is actively firing with no clear primary
        competing_signals = sum([bool(has_deadlock), bool(has_wal_lag), bool(has_conn_exhaustion)])
        if competing_signals >= 2 and triage:
            candidates = triage.candidate_cause_classes
            if (
                len(candidates) >= 2
                and candidates[0] != candidates[1]
                and (
                    "ambiguous" in triage.reasoning_summary.lower()
                    or "similar support" in triage.reasoning_summary.lower()
                )
            ):
                classes_str = ", ".join(candidates[:2])
                return (
                    True,
                    f"Symptom maps to several cause classes ({classes_str}) with similar support under conflicting metrics.",
                )

        return False, None

    def _check_citation_resolution(
        self, output: InvestigationOutput, passages: list[dict[str, Any]]
    ) -> list[str]:
        """Verify that every citation in output resolves to actual retrieved text in this run."""
        errors: list[str] = []

        if not output.citations:
            # If the output proposes steps, it must have citations
            if output.first_response_steps and not output.escalation_reason:
                errors.append("Investigation proposed guidance without any supporting citations.")
            return errors

        for idx, citation in enumerate(output.citations, start=1):
            sec_id = citation.section_id.strip()
            quote = citation.quoted_span.strip()

            if not sec_id:
                errors.append(f"Citation #{idx} has an empty section_id.")
                continue

            if not quote:
                errors.append(f"Citation #{idx} (section '{sec_id}') has an empty quoted_span.")
                continue

            # Find matching passages in retrieved_passages
            matching_passages = self._find_matching_passages(sec_id, passages)
            if not matching_passages:
                errors.append(
                    f"Citation #{idx} section_id '{sec_id}' does not resolve to any passage retrieved in this run."
                )
                continue

            # Verify that the quote appears in at least one matching passage
            norm_quote = normalize_text(quote)
            found_quote = False
            for p in matching_passages:
                content = p.get("content", "")
                header = p.get("header_path", "")
                if norm_quote in normalize_text(content) or norm_quote in normalize_text(header):
                    found_quote = True
                    break

            if not found_quote:
                errors.append(
                    f"Citation #{idx} quote '{quote[:60]}...' was not found in retrieved section '{sec_id}'."
                )

        return errors

    def _find_matching_passages(
        self, section_id: str, passages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Find retrieved passages matching section_id by exact match or normalized slug."""
        clean_target = section_id.strip().lower()

        # 1. Exact matches on section_id or chunk_id take precedence
        exact_matches = [
            p
            for p in passages
            if clean_target == str(p.get("section_id", "")).strip().lower()
            or clean_target == str(p.get("chunk_id", "")).strip().lower()
        ]
        if exact_matches:
            return exact_matches

        # 2. Substring matching as fallback
        sub_matches = [
            p
            for p in passages
            if clean_target in str(p.get("section_id", "")).strip().lower()
            or clean_target in str(p.get("chunk_id", "")).strip().lower()
            or (
                p.get("section_id") and str(p.get("section_id", "")).strip().lower() in clean_target
            )
        ]
        return sub_matches

    def _check_claim_support(
        self, output: InvestigationOutput, passages: list[dict[str, Any]]
    ) -> list[str]:
        """Verify that the cited text actually supports the claims in first_response_steps."""
        errors: list[str] = []
        if not output.first_response_steps:
            return errors

        # Combine all quoted spans and all retrieved passage text
        cited_text = " ".join(c.quoted_span for c in output.citations).lower()
        all_passages_text = " ".join(p.get("content", "") for p in passages).lower()

        # Check that actionable commands/concepts mentioned in steps are grounded in cited/retrieved text
        for idx, step in enumerate(output.first_response_steps, start=1):
            step_lower = step.lower()
            # If a step mentions a specific SQL command or parameter:
            sql_commands = re.findall(
                r"\b(pg_drop_replication_slot|pg_terminate_backend|pg_cancel_backend|checkpoint|max_slot_wal_keep_size|lock_timeout|statement_timeout|idle_in_transaction_session_timeout)\b",
                step_lower,
            )
            for cmd in sql_commands:
                if cmd not in cited_text and cmd not in all_passages_text:
                    errors.append(
                        f"Step #{idx} advises command/parameter '{cmd}' which has no grounding in cited or retrieved text."
                    )

        return errors

    def _determine_escalation_route(
        self, alert: dict[str, Any], current_severity: SeverityLevel
    ) -> RoutingTarget:
        """Determine human escalation route: incident-commander for SEV1/CRITICAL, else page-secondary."""
        severity_hint = str(alert.get("severity_hint", "")).upper()
        metrics = alert.get("metrics", {})
        disk = metrics.get("disk_utilization", 0.0)

        if current_severity == "SEV1" or severity_hint == "CRITICAL" or disk >= 90.0:
            return "incident-commander"
        return "page-secondary"

    def build_escalated_output(
        self,
        original_output: InvestigationOutput | None,
        reason: str,
        route: RoutingTarget,
        severity: SeverityLevel = "SEV2",
        cause: CauseClass = "saturation",
    ) -> InvestigationOutput:
        """Construct deterministic advisory escalation output to human on unverified/ambiguous run."""
        effective_cause = original_output.cause_class if original_output else cause
        effective_sev = (
            "SEV1"
            if route == "incident-commander"
            else (original_output.severity if original_output else severity)
        )

        trace = list(original_output.trace) if original_output else []
        trace.append(f"Mandatory Verifier escalated run to {route}: {reason}")

        return InvestigationOutput(
            cause_class=effective_cause,
            first_response_steps=[
                f"1. Mandatory verification halted automated run: {reason}",
                f"2. Incident escalated immediately to {route} for manual operational response.",
                "3. Never return an unverified advisory answer to on-call engineers.",
            ],
            citations=[],
            severity=effective_sev,
            severity_basis=f"Deterministic escalation to {route}: {reason}",
            route=route,
            verified=False,
            escalation_reason=reason,
            trace=trace,
            retrieved_passages=original_output.retrieved_passages if original_output else [],
            prompt_version="verifier-v1.0.0",
        )
