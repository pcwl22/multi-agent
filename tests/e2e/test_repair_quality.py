"""Explicit controlled model fixture plus actual Docker; never a live-model claim."""
import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.models.schemas import ContractCheck, Edit, Patch, Plan, Review, TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1", reason="Docker tests are opt-in")]


class QualityFixture:
    def __init__(self, first="duplicate", invalid_review=False):
        self.first, self.invalid_review = first, invalid_review
        self.payloads = []

    def generate(self, schema, payload):
        stats = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "adapter": "explicit-quality-fixture"}
        if schema is Plan:
            return Plan(issue_summary="Controlled VALUE fixture", suspected_modules=["repair_value.py"],
                search_strategy=["VALUE"], repair_steps=["Return 1"], validation_strategy=["Docker"]), stats
        if schema is Review:
            facts = payload["review_evidence"]["test_facts"]
            assert any(f["status"] == "passed" for f in facts)
            assert payload["regression_evidence"][-1]["status"] == "demonstrated"
            return Review(approved=True, summary="Controlled review", concerns=[],
                contract_checks=[ContractCheck(requirement="Value contract", satisfied=True,
                    evidence="T999" if self.invalid_review else facts[0]["id"])]), stats
        assert schema is Patch
        self.payloads.append(payload)
        assert payload["candidate_protocol"]["version"] == 1
        edits = [Edit(path="repair_value.py", old="VALUE = 0", new="VALUE = 1")]
        first = len(self.payloads) == 1
        if first and self.first == "duplicate":
            edits.append(Edit(path="repair_value.py", old="VALUE = 0", new="VALUE = 2"))
        if not (first and self.first == "missing"):
            assertion = "VALUE in (0, 1)" if first and self.first == "no_witness" else "VALUE == 1"
            edits.append(Edit(path="tests/test_new.py", old="", new=(
                "from repair_value import VALUE\ndef test_fixed():\n    assert " + assertion + "\n")))
        return Patch(rationale="Explicit fixture; not an LLM result", edits=edits,
                     contract_tests=["tests/test_new.py::test_fixed"]), stats


def setup(tmp_path, model, mode="single", retries=1):
    root = tmp_path / "repository"
    (root / "tests").mkdir(parents=True)
    (root / "repair_value.py").write_text("VALUE = 0\n", encoding="utf-8")
    (root / "tests/test_original.py").write_text("from repair_value import VALUE\ndef test_original():\n    assert VALUE in (0, 1)\n", encoding="utf-8")
    settings = Settings(_env_file=None, repository_root=root, data_dir=tmp_path / "data",
        sandbox_image="repopilot-sandbox:local", test_timeout=30, max_retries=retries,
        retry_workspace_policy="isolated", patch_transactions=True, repair_quality_checks=True, repair_quality_policy_version=1)
    service = TaskService(settings, model=model, runner=DockerRunner(settings))
    task = service.create(TaskRequest(repository_path=str(root), mode=mode,
        issue_description="Controlled fixture: code.VALUE must equal 1. Add NEW regression tests."))
    return service, settings, task


@pytest.mark.parametrize("mode", ["single", "multi_no_review", "multi_full"])
def test_duplicate_recovery_has_real_regression_witness_and_complete_candidate(tmp_path, mode):
    model = QualityFixture()
    service, _, task = setup(tmp_path, model, mode)
    try:
        state = service.run(task["task_id"])
        assert state["execution_status"] == "awaiting_approval"
        assert state["attempts"] == 2 and state["retry_count"] == 1
        assert state["patch_feedback"][0]["diagnostics"][0]["edit_indices"] == [1, 2]
        assert state["regression_results"][-1]["status"] == "demonstrated"
        assert state["regression_results"][-1]["baseline_result"]["evidence"] == "docker"
        assert state["regression_results"][-1]["baseline_result"]["failed"] == 1
        assert state["test_results"][-1]["passed"] == 2
        original = Path(state["task_path"]) / "baseline/tests/test_original.py"
        assert original.read_bytes() == (Path(state["workspace_path"]) / "tests/test_original.py").read_bytes()
        assert not (Path(state["task_path"]) / "attempts/0001/workspace/tests/test_new.py").exists()
        assert (Path(state["workspace_path"]) / "tests/test_new.py").exists()
    finally:
        service.close()


@pytest.mark.parametrize("first", ["missing", "no_witness"])
def test_missing_or_non_regression_tests_feedback_within_same_retry_budget(tmp_path, first):
    model = QualityFixture(first)
    service, _, task = setup(tmp_path, model)
    try:
        state = service.run(task["task_id"])
        assert state["execution_status"] == "awaiting_approval"
        assert state["attempts"] == 2 and state["retry_count"] == 1
        codes = {d["code"] for d in model.payloads[1]["patch_feedback"][-1]["diagnostics"]}
        assert ("missing_new_tests" if first == "missing" else "regression_not_demonstrated") in codes
        assert state["regression_results"][-1]["status"] == "demonstrated"
    finally:
        service.close()


def test_quality_policy_survives_restart_with_changed_settings(tmp_path):
    model = QualityFixture("missing")
    service, settings, task = setup(tmp_path, model)
    service.close()
    settings.repair_quality_checks = False
    settings.repair_quality_policy_version = 2
    service = TaskService(settings, model=model, runner=DockerRunner(settings))
    try:
        state = service.run(task["task_id"])
        assert state["repair_quality_version"] == 1
        assert state["execution_status"] == "awaiting_approval" and state["attempts"] == 2
        assert state["patch_feedback"][0]["diagnostics"][0]["code"] == "missing_new_tests"
    finally:
        service.close()


def test_unknown_review_citation_cannot_reach_human_approval(tmp_path):
    model = QualityFixture("valid", invalid_review=True)
    service, _, task = setup(tmp_path, model, mode="multi_full", retries=0)
    try:
        state = service.run(task["task_id"])
        assert state["execution_status"] == "failed"
        assert state["review_results"][-1]["approved"] is False
        assert "T999" in state["review_results"][-1]["concerns"][-1]
        assert state["approval_status"] == "pending"
    finally:
        service.close()
