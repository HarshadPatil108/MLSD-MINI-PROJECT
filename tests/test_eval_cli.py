"""Unit and integration tests for Scenario Evaluation Suite & CLI (L3, eval-integrity.md)."""

from app.eval.run import main
from src.eval.runner import ScenarioEvaluator


def test_scenarios_dataset_exists_and_valid():
    """Verify data/eval/scenarios.jsonl exists and contains required scenario distribution."""
    evaluator = ScenarioEvaluator("data/eval/scenarios.jsonl")
    scenarios = evaluator.load_scenarios()

    # 1. Total count is 10
    assert len(scenarios) == 10

    # 2. All scenarios labeled synthetic
    for s in scenarios:
        assert s.get("is_synthetic") is True, (
            f"Scenario {s.get('scenario_id')} is not labeled synthetic"
        )
        assert "alert" in s
        assert "expected_route" in s

    # 3. Must include Section 4.1 scenario
    sec_41 = [s for s in scenarios if s.get("category") == "section_4.1"]
    assert len(sec_41) == 1
    assert sec_41[0]["alert"]["alert_name"] == "PostgresWalAccumulationWarning"
    assert sec_41[0]["expected_cause_class"] == "saturation"
    assert sec_41[0]["expected_route"] == "self-serve runbook"

    # 4. Must include at least 2 out-of-corpus scenarios
    ooc = [s for s in scenarios if s.get("category") == "out_of_corpus"]
    assert len(ooc) >= 2

    # 5. Must include 1 ambiguous multi-cause scenario
    ambig = [s for s in scenarios if s.get("category") == "ambiguous_multi_cause"]
    assert len(ambig) == 1
    assert ambig[0]["expected_route"] == "page-secondary"

    # 6. Must include 2 prompt-injection scenarios
    inject = [s for s in scenarios if s.get("category") == "prompt_injection"]
    assert len(inject) == 2
    for inj in inject:
        assert inj["expected_route"] == "page-secondary"


def test_evaluator_metrics_computation(tmp_path):
    """Test scientific metric calculations on a subset of scenarios."""
    evaluator = ScenarioEvaluator("data/eval/scenarios.jsonl")
    # Run with limit=3 for fast isolated testing
    metrics = evaluator.run_suite(limit=3)

    assert metrics.total_scenarios == 3
    assert metrics.cause_class_eval_count == 3
    assert metrics.cause_class_accuracy >= 0.0
    assert metrics.route_accuracy >= 0.0
    assert 0.0 <= metrics.escalation_precision <= 1.0
    assert 0.0 <= metrics.escalation_recall <= 1.0
    assert 0.0 <= metrics.citation_resolves_rate <= 1.0
    assert len(metrics.scenario_results) == 3


def test_eval_cli_main_execution(monkeypatch, capsys):
    """Test CLI entrypoint execution via main()."""
    monkeypatch.setattr("sys.argv", ["run.py", "--limit", "2"])
    exit_code = main()
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "INCIDENTOPS SRE ASSISTANT" in captured.out
    assert "SYNTHETIC DATA" in captured.out
    assert "Cause-Class Accuracy" in captured.out
    assert "Route Accuracy" in captured.out
    assert "Escalation Precision" in captured.out
    assert "Escalation Recall" in captured.out
    assert "Citation-Resolves Rate" in captured.out
