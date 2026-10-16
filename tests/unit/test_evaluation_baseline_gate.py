import json
from pathlib import Path

from app.config.settings import Settings
from app.evaluation.runner import run_evaluation
from app.models.schemas import TestResult


def test_already_passing_baseline_is_not_counted_as_a_repair(tmp_path: Path, monkeypatch):
    class PassingBaselineDouble:
        def __init__(self, settings):
            pass

        def run(self, workspace):
            return TestResult(status="passed", passed=1, evidence="test_double")

    monkeypatch.setattr("app.evaluation.runner.DockerRunner", PassingBaselineDouble)
    source = Path(__file__).parents[2] / "demo_repository"
    report = run_evaluation(
        Settings(repository_root=source, data_dir=tmp_path / "data"), source, tmp_path / "report"
    )
    records = [
        json.loads(line)
        for line in (tmp_path / "report/runs.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 9
    assert all(record["execution_status"] == "invalid_case" for record in records)
    assert all(record["task_id"] is None for record in records)
    for mode in report["modes"].values():
        assert mode["bug_fix_success_rate"] is None
        assert mode["repair_evaluated"] == 0
        assert mode["invalid_case_runs"] == 3
