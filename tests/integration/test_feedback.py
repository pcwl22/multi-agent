from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.model import MockModel
from app.config.settings import Settings
from app.graph.workflow import build_graph
from app.models.schemas import Edit, Patch, Review, TaskRequest, TestResult
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble, initial


class RetryModel(MockModel):
    def __init__(self):
        self.attempt = 0

    def generate(self, schema, payload):
        if schema is Patch:
            self.attempt += 1
            if self.attempt == 1:
                patch, stats = super().generate(schema, payload)
                patch.edits[0].new = 'status_code=402, detail="Token expired"'
                return patch, stats
            return Patch(
                rationale="Use test feedback",
                edits=[Edit(path="auth.py", old="status_code=402", new="status_code=401")],
            ), {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        return super().generate(schema, payload)


class SequenceRunner:
    def __init__(self, statuses):
        self.statuses = iter(statuses)

    def run(self, workspace):
        status = next(self.statuses)
        return TestResult(
            status=status,
            exit_code=0 if status == "passed" else 1,
            passed=int(status == "passed"),
            failed=int(status == "failed"),
            evidence="test_double",
            stderr="explicit runner double",
        )


def test_test_feedback_retries_once(tmp_path):
    state = initial(tmp_path)
    graph = build_graph(
        Settings(), RetryModel(), SequenceRunner(["failed", "passed"]), InMemorySaver()
    )
    result = graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    assert result["execution_status"] == "awaiting_approval"
    assert result["retry_count"] == 1
    assert result["attempts"] == 2


def test_budget_terminates(tmp_path):
    state = initial(tmp_path)
    graph = build_graph(
        Settings(max_retries=1), RetryModel(), SequenceRunner(["failed", "failed"]), InMemorySaver()
    )
    result = graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    assert result["execution_status"] == "failed"
    assert result["attempts"] == 2
    assert "budget exhausted" in result["error"]


def test_review_feedback_routes_to_coder(tmp_path):
    class ReviewRetry(RetryModel):
        def generate(self, schema, payload):
            if schema is Review:
                return Review(approved=self.attempt == 2, summary="fixture review", concerns=[]), {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            return super().generate(schema, payload)

    state = initial(tmp_path)
    graph = build_graph(
        Settings(), ReviewRetry(), SequenceRunner(["passed", "passed"]), InMemorySaver()
    )
    result = graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    assert result["retry_count"] == 1
    assert len(result["review_results"]) == 2


def test_human_reject(tmp_path):
    state = initial(tmp_path)
    graph = build_graph(Settings(), MockModel(), EvidenceDouble(), InMemorySaver())
    config = {"configurable": {"thread_id": state["thread_id"]}}
    result = graph.invoke(state, config)
    result = graph.invoke(
        Command(resume={"approved": False, "diff_digest": result["diff_digest"]}), config
    )
    assert result["execution_status"] == "rejected"


def settings(tmp_path):
    return Settings(
        repository_root=Path(__file__).parents[2] / "test_fixtures" / "repair_repository", data_dir=tmp_path / "data"
    )


def test_sqlite_restart_and_blocked_resume(tmp_path):
    config = settings(tmp_path)
    service = TaskService(config, runner=SequenceRunner(["unavailable"]))
    task = service.create(
        TaskRequest(
            repository_path=str(config.repository_root),
            issue_description="expired token returns 500",
        )
    )
    first = service.run(task["task_id"])
    assert first["execution_status"] == "blocked"
    service.close()
    service = TaskService(config, runner=EvidenceDouble())
    try:
        second = service.run(task["task_id"])
        assert second["execution_status"] == "awaiting_approval"
        assert second["attempts"] == 1
        assert second["thread_id"] != second["task_id"]
        assert len(second["test_results"]) == 2
        # A test double cannot authorize an external operation.
        import pytest

        with pytest.raises(ValueError, match="real Docker"):
            service.decide(task["task_id"], True, second["diff_digest"])
        rejected = service.decide(task["task_id"], False, second["diff_digest"])
        assert rejected["execution_status"] == "rejected"
    finally:
        service.close()


def test_resume_failure_still_tests_each_new_attempt(tmp_path):
    config = settings(tmp_path)
    service = TaskService(
        config, model=RetryModel(), runner=SequenceRunner(["unavailable", "failed", "passed"])
    )
    try:
        task = service.create(
            TaskRequest(
                repository_path=str(config.repository_root),
                issue_description="expired returns 500 expected 401",
            )
        )
        assert service.run(task["task_id"])["execution_status"] == "blocked"
        result = service.run(task["task_id"])
        assert result["execution_status"] == "awaiting_approval"
        assert result["attempts"] == 2 and len(result["test_results"]) == 3
        assert [t["attempt"] for t in result["test_results"]] == [1, 1, 2]
    finally:
        service.close()
