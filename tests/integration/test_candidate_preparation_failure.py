from pathlib import Path

import app.graph.workflow as workflow
from app.models.schemas import TestResult
from tests.e2e.test_isolated_attempts import CASES, make_service


class FailedRouteDouble:
    """No target code execution: exercises routing after a controlled preparation failure."""

    def run(self, workspace):
        return TestResult(status="failed", failed=1, evidence="test_double",
                          stdout="Controlled route-test failure, not pytest evidence")


def test_failed_preparation_never_calls_coder_again_in_archived_workspace(tmp_path, monkeypatch):
    service, task, _, model = make_service(tmp_path, "page-tail")
    service.close()

    def rejected(*args, **kwargs):
        raise ValueError("Controlled preparation failure")

    monkeypatch.setattr(workflow, "prepare_candidate", rejected)
    from app.services.tasks import TaskService

    restored = TaskService(service.settings, model=model, runner=FailedRouteDouble())
    try:
        state = restored.run(task["task_id"])
        assert state["execution_status"] == "failed"
        assert state["error"] == "Controlled preparation failure"
        assert state["candidate_number"] == model.calls == len(state["patches"]) == 1
        assert CASES["page-tail"][2] in (
            Path(state["workspace_path"]) / "tests/test_generated.py").read_text()
    finally:
        restored.close()
