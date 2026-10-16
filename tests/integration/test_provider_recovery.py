from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.model import MockModel, ModelFailure
from app.api.main import create_app
from app.config.settings import Settings
from app.models.schemas import Patch, Plan, Review, TaskRequest
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble


class TemporaryFailure(MockModel):
    """Controlled provider-failure double, not real LLM evidence."""

    def __init__(self, schema=Plan, *, always=False, retryable=True):
        self.schema, self.always, self.retryable = schema, always, retryable
        self.failures = 0

    def generate(self, schema, payload):
        if schema is self.schema and (self.always or not self.failures):
            self.failures += 1
            raise ModelFailure("Model request failed: ControlledTransportFailure", {
                "calls": 1, "input_tokens": 0, "output_tokens": 0,
                "usage_complete": False,
                "failure": {"kind": "rate_limit" if self.retryable else "credentials",
                            "retryable": self.retryable, "retry_after_seconds": 300},
            })
        return super().generate(schema, payload)


def settings_for(tmp_path, **kwargs):
    return Settings(repository_root=Path(__file__).parents[2] / "demo_repository",
                    data_dir=tmp_path / "data", **kwargs)


def create(service):
    return service.create(TaskRequest(
        repository_path=str(service.settings.repository_root),
        issue_description="expired token returns 500, expected 401",
    ))["task_id"]


def expire_cooldown(service, task_id):
    state = service.get(task_id)
    service.graph.update_state(service._config(state["thread_id"]),
                               {"failure": {**state["failure"], "retry_at": 0}})


@pytest.mark.parametrize("failed_schema", [Plan, Patch, Review])
def test_resume_persists_and_retries_only_failed_model_node(tmp_path, failed_schema):
    settings = settings_for(tmp_path)
    service = TaskService(settings, model=TemporaryFailure(failed_schema), runner=EvidenceDouble())
    task_id = create(service)
    failed = service.run(task_id)
    assert failed["execution_status"] == "retryable"
    assert not failed["token_usage_complete"]
    with TestClient(create_app(service=service)) as api:
        denied = api.post(f"/api/tasks/{task_id}/resume")
        assert denied.status_code == 409 and "cooldown" in denied.json()["detail"]
    expire_cooldown(service, task_id)
    service.close()
    restarted = TaskService(settings, model=MockModel(), runner=EvidenceDouble())
    try:
        result = restarted.run(task_id)
        assert result["execution_status"] == "awaiting_approval"
        assert result["attempts"] == 1
        assert len(result["patches"]) == len(result["test_results"]) == 1
        assert result["provider_retry_count"] == 1
        assert result["model_calls"] == 1  # One failed controlled call; MockModel reports zero.
        assert not result["token_usage_complete"]
        assert result["failure"] is None
    finally:
        restarted.close()


def test_repeated_failure_exhausts_manual_provider_budget(tmp_path):
    service = TaskService(settings_for(tmp_path, max_retries=1),
                          model=TemporaryFailure(always=True), runner=EvidenceDouble())
    try:
        task_id = create(service)
        service.run(task_id)
        expire_cooldown(service, task_id)
        state = service.run(task_id)
        assert state["execution_status"] == "failed"
        assert state["failure"]["budget_exhausted"]
        assert state["provider_retry_count"] == 1 and state["model_calls"] == 2
        with pytest.raises(ValueError, match="not resumable"):
            service.check_resume(task_id)
    finally:
        service.close()


def test_permanent_provider_error_is_terminal(tmp_path):
    service = TaskService(settings_for(tmp_path), model=TemporaryFailure(retryable=False),
                          runner=EvidenceDouble())
    try:
        task_id = create(service)
        state = service.run(task_id)
        assert state["execution_status"] == "failed"
        assert not state["failure"]["retryable"]
    finally:
        service.close()


def test_unrecorded_edit_before_first_checkpoint_blocks_resume(tmp_path):
    service = TaskService(settings_for(tmp_path), runner=EvidenceDouble())
    try:
        task_id = create(service)
        state = service.get(task_id)
        target = Path(state["workspace_path"]) / "auth.py"
        target.write_text(target.read_text(encoding="utf8") + "\n# unrecorded\n", encoding="utf8")
        with pytest.raises(ValueError, match="outside the recorded"):
            service.run(task_id)
        with TestClient(create_app(service=service)) as api:
            assert api.post(f"/api/tasks/{task_id}/resume").status_code == 409
        assert service.get(task_id)["attempts"] == 0
    finally:
        service.close()
