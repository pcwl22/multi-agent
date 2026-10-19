"""Publication protocol doubles; no real GitHub writes or target execution."""
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config.settings import Settings
from app.models.schemas import TaskRequest, TestResult
from app.services.github import GitHubPublisher
from app.services.tasks import TaskService
from tests.unit.test_publication_plan import GitHubContract


class DockerMetadataDouble:
    """Supplies controlled approval metadata, not actual Docker evidence."""

    def run(self, workspace):
        return TestResult(status="passed", passed=1, evidence="docker",
                          stdout="Protocol test metadata double; target code never executed")


@pytest.fixture
def approved_service(tmp_path):
    source = Path(__file__).parents[2] / "test_fixtures/repair_repository"
    settings = Settings(repository_root=source, data_dir=tmp_path / "data", github_repository="owner/repo",
                        github_token="unit-contract-only", _env_file=None)
    service = TaskService(settings, runner=DockerMetadataDouble())
    task = service.create(TaskRequest(repository_path=str(source), issue_description="expired returns 401"))
    state = service.run(task["task_id"])
    service.decide(task["task_id"], True, state["diff_digest"])
    transport = GitHubContract(state)

    def publisher():
        return GitHubPublisher("owner/repo", "unit-contract-only", client=httpx.Client(
            transport=httpx.MockTransport(transport)))

    yield service, state, transport, publisher
    service.close()


def test_api_requires_separate_exact_publication_approval(approved_service, monkeypatch):
    service, state, remote, publisher = approved_service
    monkeypatch.setattr(service, "_publisher", publisher)
    path = f"/api/tasks/{state['task_id']}"
    payload = {"diff_digest": state["diff_digest"]}
    with TestClient(create_app(service=service)) as api:
        assert api.post(path + "/pr", json=payload).status_code == 409
        preview = api.post(path + "/publication/preview", json={}).json()
        assert not remote.writes
        assert api.post(path + "/pr", json=payload).status_code == 409
        assert api.post(path + "/publication/approve", json={"request_digest": "f" * 64}).status_code == 409
        digest = preview["request_digest"]
        assert api.post(path + "/publication/approve", json={"request_digest": digest}).status_code == 200
        assert api.post(path + "/pr", json=payload).status_code == 409
        assert not remote.writes
        payload["publication_digest"] = digest
        result = api.post(path + "/pr", json=payload)
        assert result.status_code == 200 and result.json()["status"] == "created"
        count = len(remote.writes)
        assert api.post(path + "/pr", json=payload).json() == result.json()
        assert len(remote.writes) == count


@pytest.mark.parametrize("field,value", [("github_repository", "other/repo"),
    ("github_base_branch", "release"), ("github_repository_subdirectory", "demo")])
def test_restart_configuration_change_invalidates_approval(approved_service, field, value):
    service, state, remote, publisher = approved_service
    request = service.preview_publication(state["task_id"], publisher=publisher())
    service.approve_publication(state["task_id"], request["request_digest"])
    changed = service.settings.model_copy(update={field: value})
    restored = TaskService(changed, runner=DockerMetadataDouble())
    try:
        with pytest.raises(ValueError, match="target configuration changed"):
            restored.publish(state["task_id"], state["diff_digest"], publisher=publisher(),
                             publication_digest=request["request_digest"])
        assert not remote.writes
    finally:
        restored.close()


def test_refresh_resets_approval_and_body_changes_digest(approved_service):
    service, state, remote, publisher = approved_service
    first = service.preview_publication(state["task_id"], publisher=publisher())
    service.approve_publication(state["task_id"], first["request_digest"])
    second = service.preview_publication(state["task_id"], body="Changed reviewed body", publisher=publisher())
    assert second["request_digest"] != first["request_digest"]
    assert second["approval_status"] == "pending"
    with pytest.raises(ValueError, match="publication approval"):
        service.publish(state["task_id"], state["diff_digest"], publisher=publisher(),
                        publication_digest=first["request_digest"])
    assert not remote.writes
