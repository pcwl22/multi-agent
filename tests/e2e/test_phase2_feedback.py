import os
from pathlib import Path

import pytest

from app.agents.model import MockModel
from app.config.settings import Settings
from app.models.schemas import Patch, TaskRequest
from app.services.tasks import TaskService
from app.tools.repository import Repository, snapshot
from tests.integration.test_feedback import RetryModel

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1",
        reason="Docker feedback tests are opt-in",
    ),
]


class FeedbackModel(RetryModel):
    """Scripted patch generation with real Docker failures as its input."""

    def __init__(self):
        super().__init__()
        self.saw_pytest_failure = False

    def generate(self, schema, payload):
        if schema is Patch and self.attempt:
            test = payload["tests"][-1]
            assert test["evidence"] == "docker" and test["status"] == "failed"
            assert test["failed"] > 0 and "401" in test["stdout"]
            self.saw_pytest_failure = True
        return super().generate(schema, payload)


def test_real_failed_test_feedback_and_approval_restart(tmp_path: Path):
    root = Path(__file__).parents[2] / "demo_repository"
    settings = Settings(repository_root=root, data_dir=tmp_path / "data")
    model = FeedbackModel()
    service = TaskService(settings, model=model)
    try:
        task = service.create(
            TaskRequest(
                repository_path=str(root),
                issue_description="expired token returns 500, should return 401",
            )
        )
        state = service.run(task["task_id"])
        assert state["execution_status"] == "awaiting_approval"
        assert model.saw_pytest_failure
        assert [t["status"] for t in state["test_results"]] == ["failed", "passed"]
        assert state["retry_count"] == 1 and state["attempts"] == 2
        assert state["review_results"][-1]["approved"]
    finally:
        service.close()
    restored = TaskService(settings, model=MockModel())
    try:
        assert restored.get(task["task_id"])["thread_id"] == state["thread_id"]
        result = restored.decide(task["task_id"], False, state["diff_digest"])
        assert result["execution_status"] == "rejected"
        assert result["attempts"] == 2
    finally:
        restored.close()


def test_real_persistent_test_failure_exhausts_budget(tmp_path: Path):
    source = tmp_path / "source"
    snapshot(Repository(Path(__file__).parents[2] / "demo_repository"), source)
    (source / "tests/test_unsatisfied_contract.py").write_text(
        'def test_unsatisfied_contract():\n    assert False, "Unrelated contract needs repair"\n',
        encoding="utf-8",
    )
    service = TaskService(
        Settings(repository_root=source, data_dir=tmp_path / "data", max_retries=1),
        model=FeedbackModel(),
    )
    try:
        task = service.create(
            TaskRequest(
                repository_path=str(source), issue_description="expired token should return 401"
            )
        )
        state = service.run(task["task_id"])
        assert state["execution_status"] == "failed"
        assert state["retry_count"] == 1 and state["attempts"] == 2
        assert [t["status"] for t in state["test_results"]] == ["failed", "failed"]
        assert "budget exhausted" in state["error"]
        assert state["approval_status"] == "pending"
    finally:
        service.close()
