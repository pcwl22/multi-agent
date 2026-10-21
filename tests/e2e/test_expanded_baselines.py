"""Evaluator-owned contracts: never imported or sent to repair models."""

import json
import os
import shutil
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.evaluation.runner import holdout_workspace
from app.models.schemas import Edit, Patch
from app.sandbox.runner import DockerRunner
from app.tools.repository import Repository

ROOT = Path(__file__).parents[2] / "app/evaluation/expanded"
CASES = json.loads((ROOT / "dataset.json").read_text(encoding="utf-8"))
REFERENCES = json.loads((ROOT / "references.json").read_text(encoding="utf-8"))
pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1", reason="Docker tests are opt-in"
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_expanded_case_has_failing_holdout_and_valid_reference(case, tmp_path):
    source = ROOT / case["repository"]
    runner = DockerRunner(Settings())
    existing = runner.run(source)
    assert existing.status == "passed" and existing.passed > 0
    acceptance = ROOT / "acceptance" / case["acceptance"]
    before = tmp_path / "before"
    holdout_workspace(source, before, acceptance)
    failed = runner.run(before)
    assert failed.status == "failed" and failed.failed > 0 and failed.errors == 0
    repaired = tmp_path / "repaired"
    shutil.copytree(source, repaired)
    Repository(repaired).apply(
        Patch(
            rationale="Evaluator reference, never a model result",
            edits=[Edit(path=path, **edit) for path, edit in REFERENCES[case["id"]].items()],
        )
    )
    assert runner.run(repaired).status == "passed"
    after = tmp_path / "after"
    holdout_workspace(repaired, after, acceptance)
    accepted = runner.run(after)
    assert accepted.status == "passed" and accepted.passed > 0
    assert accepted.image_id == failed.image_id == existing.image_id
