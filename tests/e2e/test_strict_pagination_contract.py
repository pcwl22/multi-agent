import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.evaluation.runner import holdout_workspace
from app.models.schemas import Edit, Patch
from app.sandbox.runner import DockerRunner
from app.tools.repository import Repository


@pytest.mark.docker
@pytest.mark.skipif(os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1", reason="Docker opt-in")
def test_strict_reference_requires_range_contract_and_index_fix(tmp_path):
    root = Path(__file__).parents[2] / "app/evaluation/expanded"
    holdout = tmp_path / "holdout"
    holdout_workspace(
        root / "repos/one-based-page",
        holdout,
        root / "acceptance/test_pagination_sequence_acceptance.py",
    )
    repo = Repository(holdout)
    runner = DockerRunner(Settings())
    repo.apply(
        Patch(
            rationale="Index-only fix leaves stated range return contract broken",
            edits=[
                Edit(
                    path="pagination.py",
                    old="start = page * page_size",
                    new="start = (page - 1) * page_size",
                )
            ],
        )
    )
    failed = runner.run(holdout)
    assert failed.status == "failed" and failed.failed == 4 and failed.errors == 0
    repo.apply(
        Patch(
            rationale="Complete the range return contract",
            edits=[
                Edit(
                    path="pagination.py",
                    old="return items[start : start + page_size]",
                    new="return list(items[start : start + page_size])",
                )
            ],
        )
    )
    assert runner.run(holdout).status == "passed"
