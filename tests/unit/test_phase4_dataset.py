import json
from pathlib import Path

from app.agents.demo_fixtures import select_fixture
from app.evaluation.runner import aggregate


def test_dataset_contains_distinct_bugs_and_holdouts():
    root = Path(__file__).parents[2]
    dataset = json.loads((root / "app/evaluation/dataset.json").read_text(encoding="utf-8"))
    modules = {select_fixture(case["issue"]).module for case in dataset}
    assert modules == {"auth.py", "pagination.py", "pricing.py"}
    assert len({case["id"] for case in dataset}) == 3
    for case in dataset:
        assert (root / "app/evaluation/acceptance" / case["acceptance"]).is_file()


def test_failed_repair_stays_in_success_rate_denominator():
    common = dict(
        duration_seconds=1, model_calls=1, tokens=20, retry_count=0, baseline_verified=True
    )
    records = [
        dict(
            common,
            execution_status="awaiting_approval",
            test_result=dict(status="passed", passed=2, failed=0, errors=0),
            acceptance=dict(status="passed"),
        ),
        dict(common, execution_status="failed", test_result=None, acceptance=None),
    ]
    result = aggregate(records)
    assert result["bug_fix_success_rate"] == 0.5
    assert result["repair_evaluated"] == 2
    assert result["acceptance_evaluated"] == 1


def test_no_model_usage_is_unknown_not_zero():
    records = [
        dict(
            execution_status="failed",
            duration_seconds=1,
            model_calls=1,
            tokens=None,
            retry_count=0,
            baseline_verified=True,
            test_result=None,
            acceptance=None,
        )
    ]
    result = aggregate(records)
    assert result["average_tokens"] is None
    assert result["token_observed_runs"] == 0
    assert result["bug_fix_success_rate"] == 0
