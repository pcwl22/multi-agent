import json
import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.evaluation.runner import run_evaluation


@pytest.mark.docker
@pytest.mark.skipif(os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1", reason="Docker opt-in")
def test_parallel_cases_keep_unique_tasks_and_complete_jsonl(tmp_path):
    source = Path(__file__).parents[2] / "test_fixtures" / "repair_repository"
    output = tmp_path / "report"
    report = run_evaluation(
        Settings(repository_root=source, data_dir=tmp_path / "data"),
        source,
        output,
        workers=3,
    )
    records = [json.loads(line) for line in (output / "runs.jsonl").read_text().splitlines()]
    assert len(records) == len({r["task_id"] for r in records}) == 9
    assert len({r["thread_id"] for r in records}) == 9
    assert all(r["acceptance"]["status"] == "passed" for r in records)
    assert all(mode["runs"] == 3 for mode in report["modes"].values())
    assert report["configuration"]["workers"] == 3
    assert len(report["corpus_sha256"]) == 64
