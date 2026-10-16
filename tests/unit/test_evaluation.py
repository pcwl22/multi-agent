from pathlib import Path

from app.evaluation.runner import aggregate, holdout_workspace


def test_empty_metrics_are_not_fabricated():
    assert aggregate([])["bug_fix_success_rate"] is None
    record = dict(
        execution_status="blocked",
        duration_seconds=2,
        model_calls=0,
        tokens=0,
        retry_count=0,
        test_result=None,
        acceptance=None,
    )
    report = aggregate([record])
    assert report["bug_fix_success_rate"] is None
    assert report["test_pass_rate"] is None
    assert report["task_completion_rate"] == 0
    assert report["blocked_runs"] == 1


def test_real_records_aggregate():
    result = dict(status="passed", passed=3, failed=1, errors=0)
    records = [
        dict(
            execution_status="awaiting_approval",
            duration_seconds=4,
            model_calls=3,
            tokens=100,
            retry_count=1,
            test_result=result,
            acceptance=result,
        )
    ]
    report = aggregate(records)
    assert report["bug_fix_success_rate"] == 1
    assert report["test_pass_rate"] == 0.75
    assert report["average_model_calls"] == 3


def test_holdout_excludes_model_tests(tmp_path):
    source = Path(__file__).parents[2] / "demo_repository"
    acceptance = Path(__file__).parents[2] / "app/evaluation/acceptance/test_auth_acceptance.py"
    holdout_workspace(source, tmp_path / "holdout", acceptance)
    assert list((tmp_path / "holdout/tests").iterdir()) == [
        tmp_path / "holdout/tests/test_acceptance.py"
    ]
