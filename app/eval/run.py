"""CLI Scenario Evaluation Runner (L3, eval-integrity.md).

Executes the multi-agent incident triage and investigation suite across
benchmarked operational scenarios and prints scientific accuracy and grounding metrics.

Usage:
    python -m app.eval.run [--scenarios data/eval/scenarios.jsonl] [--limit 10]
"""

import argparse
import sys
from pathlib import Path

from src.eval.runner import EvalSummaryMetrics, ScenarioEvaluator


def print_evaluation_report(metrics: EvalSummaryMetrics) -> None:
    """Print structured, scientific benchmark report to terminal."""
    banner = "=" * 80
    print("\n" + banner)
    print("INCIDENTOPS SRE ASSISTANT — EVALUATION BENCHMARK SUITE")
    print("[NOTICE: ALL DATASETS, SCENARIOS, AND TELEMETRY ARE EXPLICITLY SYNTHETIC DATA]")
    print(banner)

    print("\nPER-SCENARIO RESULTS:")
    print("-" * 80)
    fmt = "{:<28} {:<18} {:<14} {:<14} {:<6}"
    print(fmt.format("Scenario ID", "Expected Route", "Actual Route", "Cause Match", "Status"))
    print("-" * 80)

    for r in metrics.scenario_results:
        cause_status = (
            "N/A"
            if r.cause_class_match is None
            else ("MATCH" if r.cause_class_match else "MISMATCH")
        )
        overall_status = (
            "PASS"
            if (r.route_match and (r.cause_class_match is None or r.cause_class_match))
            else "FAIL"
        )
        print(
            fmt.format(
                r.scenario_id[:27],
                r.expected_route[:17],
                r.actual_route[:17],
                cause_status,
                overall_status,
            )
        )

    print("-" * 80)
    print("\nAGGREGATE BENCHMARK METRICS:")
    print("=" * 50)
    print(f"Total Scenarios Evaluated:     {metrics.total_scenarios} (ALL DATA SYNTHETIC)")
    print(
        f"Cause-Class Accuracy:          {metrics.cause_class_accuracy * 100:.1f}% "
        f"({metrics.cause_class_correct}/{metrics.cause_class_eval_count})"
    )
    print(
        f"Route Accuracy:                {metrics.route_accuracy * 100:.1f}% "
        f"({metrics.route_correct}/{metrics.total_scenarios})"
    )
    print(
        f"Escalation Precision:          {metrics.escalation_precision * 100:.1f}% "
        f"(TP={metrics.true_positives_escalation}, FP={metrics.false_positives_escalation})"
    )
    print(
        f"Escalation Recall:             {metrics.escalation_recall * 100:.1f}% "
        f"(TP={metrics.true_positives_escalation}, FN={metrics.false_negatives_escalation})"
    )
    print(
        f"Citation-Resolves Rate:        {metrics.citation_resolves_rate * 100:.1f}% "
        f"({metrics.citation_runs_resolved}/{metrics.citation_runs_count} runs grounded)"
    )
    print("=" * 50 + "\n")


def main() -> int:
    """CLI Entrypoint for running scenario benchmarks."""
    parser = argparse.ArgumentParser(
        description="Run multi-agent incident triage scenario evaluation benchmarks."
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default="data/eval/scenarios.jsonl",
        help="Path to scenarios JSONL file (default: data/eval/scenarios.jsonl)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of scenarios to evaluate (default: all)",
    )

    args = parser.parse_args()

    scenarios_file = Path(args.scenarios)
    if not scenarios_file.exists():
        print(f"Error: Scenarios file '{scenarios_file}' does not exist.", file=sys.stderr)
        return 1

    evaluator = ScenarioEvaluator(scenarios_path=str(scenarios_file))
    metrics = evaluator.run_suite(limit=args.limit)

    print_evaluation_report(metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())
