"""Evaluation Runner & Scientific Metrics Engine (L3, eval-integrity.md).

Evaluates the multi-agent reasoning layer across synthetic incident scenarios,
measuring cause-class accuracy, routing accuracy, escalation precision/recall,
and citation resolution rates.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent.graph import run_multi_agent_triage

logger = logging.getLogger(__name__)


@dataclass
class ScenarioEvalResult:
    """Individual scenario evaluation record."""

    scenario_id: str
    name: str
    category: str
    is_synthetic: bool
    expected_cause_class: str | None
    actual_cause_class: str
    cause_class_match: bool | None
    expected_route: str
    actual_route: str
    route_match: bool
    is_escalated_expected: bool
    is_escalated_actual: bool
    verified: bool
    citation_count: int
    citations_resolved: bool
    escalation_reason: str | None


@dataclass
class EvalSummaryMetrics:
    """Aggregated evaluation metrics for synthetic scenario test suite."""

    total_scenarios: int = 0
    synthetic_label: str = "ALL DATA SYNTHETIC"
    cause_class_eval_count: int = 0
    cause_class_correct: int = 0
    cause_class_accuracy: float = 0.0
    route_correct: int = 0
    route_accuracy: float = 0.0
    true_positives_escalation: int = 0
    false_positives_escalation: int = 0
    false_negatives_escalation: int = 0
    true_negatives_escalation: int = 0
    escalation_precision: float = 0.0
    escalation_recall: float = 0.0
    citation_runs_count: int = 0
    citation_runs_resolved: int = 0
    citation_resolves_rate: float = 0.0
    scenario_results: list[ScenarioEvalResult] = field(default_factory=list)


class ScenarioEvaluator:
    """Executes evaluation benchmarks over scenario datasets."""

    def __init__(self, scenarios_path: str = "data/eval/scenarios.jsonl"):
        self.scenarios_path = Path(scenarios_path)

    def load_scenarios(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Load scenarios from JSONL file."""
        if not self.scenarios_path.exists():
            raise FileNotFoundError(f"Scenario dataset not found at {self.scenarios_path}")

        scenarios: list[dict[str, Any]] = []
        with open(self.scenarios_path, encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str and not line_str.startswith("#"):
                    scenarios.append(json.loads(line_str))
                    if limit and len(scenarios) >= limit:
                        break
        return scenarios

    def evaluate_scenario(self, scenario: dict[str, Any]) -> ScenarioEvalResult:
        """Run a single scenario through multi-agent triage and evaluate outputs."""
        alert = scenario["alert"]
        expected_cause = scenario.get("expected_cause_class")
        expected_route = scenario["expected_route"]

        # Run multi-agent pipeline
        agent_result = run_multi_agent_triage(alert)
        output = agent_result.get("final_output")

        actual_cause = output.cause_class if output else "unknown"
        actual_route = output.route if output else "unknown"
        verified = output.verified if output else False
        escalation_reason = output.escalation_reason if output else None

        # Check cause-class match
        cause_match: bool | None = None
        if expected_cause is not None:
            cause_match = actual_cause.lower() == expected_cause.lower()

        # Check route match
        route_match = actual_route.lower() == expected_route.lower()

        # Escalation classification (positive = escalated to human)
        is_escalated_expected = expected_route.lower() in [
            "page-secondary",
            "incident-commander",
        ]
        is_escalated_actual = actual_route.lower() in [
            "page-secondary",
            "incident-commander",
        ]

        # Citation resolution check
        citation_count = len(output.citations) if output else 0
        vres = agent_result.get("verification_result")
        citations_resolved = (vres is None or len(vres.citation_errors) == 0) and (
            citation_count == 0 or verified
        )

        return ScenarioEvalResult(
            scenario_id=scenario.get("scenario_id", "unknown"),
            name=scenario.get("name", "unnamed"),
            category=scenario.get("category", "general"),
            is_synthetic=bool(scenario.get("is_synthetic", True)),
            expected_cause_class=expected_cause,
            actual_cause_class=actual_cause,
            cause_class_match=cause_match,
            expected_route=expected_route,
            actual_route=actual_route,
            route_match=route_match,
            is_escalated_expected=is_escalated_expected,
            is_escalated_actual=is_escalated_actual,
            verified=verified,
            citation_count=citation_count,
            citations_resolved=citations_resolved,
            escalation_reason=escalation_reason,
        )

    def run_suite(self, limit: int | None = None) -> EvalSummaryMetrics:
        """Execute full scenario evaluation suite and compute scientific metrics."""
        scenarios = self.load_scenarios(limit=limit)
        results: list[ScenarioEvalResult] = []

        for scen in scenarios:
            res = self.evaluate_scenario(scen)
            results.append(res)

        summary = EvalSummaryMetrics(
            total_scenarios=len(results),
            scenario_results=results,
        )

        # 1. Cause-class accuracy
        cause_evals = [r for r in results if r.cause_class_match is not None]
        summary.cause_class_eval_count = len(cause_evals)
        summary.cause_class_correct = sum(1 for r in cause_evals if r.cause_class_match is True)
        summary.cause_class_accuracy = (
            summary.cause_class_correct / summary.cause_class_eval_count
            if summary.cause_class_eval_count > 0
            else 0.0
        )

        # 2. Route accuracy
        summary.route_correct = sum(1 for r in results if r.route_match is True)
        summary.route_accuracy = (
            summary.route_correct / summary.total_scenarios if summary.total_scenarios > 0 else 0.0
        )

        # 3. Escalation Precision and Recall
        tp = sum(1 for r in results if r.is_escalated_expected and r.is_escalated_actual)
        fp = sum(1 for r in results if not r.is_escalated_expected and r.is_escalated_actual)
        fn = sum(1 for r in results if r.is_escalated_expected and not r.is_escalated_actual)
        tn = sum(1 for r in results if not r.is_escalated_expected and not r.is_escalated_actual)

        summary.true_positives_escalation = tp
        summary.false_positives_escalation = fp
        summary.false_negatives_escalation = fn
        summary.true_negatives_escalation = tn

        summary.escalation_precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        summary.escalation_recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0

        # 4. Citation-resolves rate
        citation_runs = [r for r in results if r.citation_count > 0]
        summary.citation_runs_count = len(citation_runs)
        summary.citation_runs_resolved = sum(1 for r in citation_runs if r.citations_resolved)
        summary.citation_resolves_rate = (
            summary.citation_runs_resolved / summary.citation_runs_count
            if summary.citation_runs_count > 0
            else 1.0
        )

        return summary
