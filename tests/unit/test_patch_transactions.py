"""Controlled filesystem faults; runner is an explicit non-executing double."""
import json
from pathlib import Path

import pytest

import app.services.transactions as journal
from app.agents.model import MockModel
from app.config.settings import Settings
from app.models.schemas import Patch, TaskRequest, TestResult
from app.services.tasks import TaskService
from app.tools.repository import Repository


class CountedFixture(MockModel):
    def __init__(self):
        self.patch_calls = 0

    def generate(self, schema, payload):
        self.patch_calls += int(schema is Patch)
        value, stats = super().generate(schema, payload)
        if schema is Patch:
            # Synthetic usage exercises exactly-once accounting, not live LLM claims.
            stats.update(calls=1, input_tokens=11, output_tokens=7, adapter="test_double")
        return value, stats


class RunnerDouble:
    """Only workflow routing; never execution evidence."""

    def run(self, workspace):
        return TestResult(status="passed", passed=1, evidence="test_double")


def make_task(tmp_path, policy):
    source = Path(__file__).parents[2] / "test_fixtures/repair_repository"
    settings = Settings(repository_root=source, data_dir=tmp_path / "data", patch_transactions=True,
                        retry_workspace_policy=policy, _env_file=None)
    model = CountedFixture()
    service = TaskService(settings, model=model, runner=RunnerDouble())
    task = service.create(TaskRequest(repository_path=str(source),
                                    issue_description="expired token returns 500 expected 401"))
    return service, task, model


@pytest.mark.parametrize("policy", ["preserve", "isolated"])
@pytest.mark.parametrize("point", ["prepared", "temporary-1", "file-1", "written"])
def test_partial_write_requires_exact_recovery_and_does_not_call_model_twice(tmp_path, monkeypatch, policy, point):
    service, task, model = make_task(tmp_path, policy)

    def fail(where, receipt):
        if where == point:
            raise OSError("Controlled transaction write interruption")

    monkeypatch.setattr(journal, "journal_checkpoint", fail)
    try:
        failed = service.run(task["task_id"])
        assert failed["execution_status"] == "failed" and model.patch_calls == 1
        pending = service.patch_recovery(task["task_id"])
        assert pending["required"] and pending["transactions"][0]["recoverable"]
        with pytest.raises(ValueError, match="Pending patch transaction"):
            service.check_resume(task["task_id"])
        with pytest.raises(ValueError, match="journal digest"):
            service.recover_patch(task["task_id"], "f" * 64)
        monkeypatch.setattr(journal, "journal_checkpoint", lambda *args: None)
        recovered = service.recover_patch(task["task_id"], pending["transactions"][0]["journal_digest"])
        assert recovered["attempts"] == 1 and len(recovered["patches"]) == 1
        assert recovered["model_calls"] == failed["model_calls"]
        final = service.run(task["task_id"])
        assert final["execution_status"] == "awaiting_approval" and model.patch_calls == 1
        assert len(final["patches"]) == 1 and final["attempts"] == 1
        assert (final["model_calls"], final["input_tokens"], final["output_tokens"]) == (1, 11, 7)
        assert not service.patch_recovery(task["task_id"])["required"]
        root = Path(task["task_path"])
        receipt = json.loads((root / "patch-journal/0001.json").read_text())
        assert receipt["status"] == "acknowledged"
        assert final["test_results"][-1]["evidence"] == "test_double"
    finally:
        service.close()


def test_conflicting_edit_is_preserved_and_recovery_performs_no_writes(tmp_path, monkeypatch):
    service, task, _ = make_task(tmp_path, "preserve")

    def fail(point, receipt):
        if point == "file-1":
            raise OSError("Controlled interruption")

    monkeypatch.setattr(journal, "journal_checkpoint", fail)
    try:
        state = service.run(task["task_id"])
        target = Path(state["workspace_path"]) / "auth.py"
        target.write_text("unexpected = True\n", encoding="utf-8")
        before = target.read_bytes()
        summary = service.patch_recovery(task["task_id"])
        assert not summary["transactions"][0]["recoverable"]
        with pytest.raises(ValueError, match="conflict"):
            service.recover_patch(task["task_id"], summary["transactions"][0]["journal_digest"])
        assert target.read_bytes() == before
        assert not (target.parent / "tests/test_expired_regression.py").exists()
    finally:
        service.close()


def test_journal_never_weakens_existing_test_validation(tmp_path):
    from app.models.schemas import Edit

    service, task, _ = make_task(tmp_path, "preserve")
    try:
        state = service.get(task["task_id"])
        path = "tests/test_auth.py"
        source = Repository(state["workspace_path"]).read_file(path)
        with pytest.raises(ValueError, match="Existing tests"):
            journal.apply_transaction(state, Patch(rationale="forbidden", edits=[
                Edit(path=path, old=source, new="pass\n")]), {}, "")
        assert not (Path(task["task_path"]) / "patch-journal").exists()
    finally:
        service.close()
