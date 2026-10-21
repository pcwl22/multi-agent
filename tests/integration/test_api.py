from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config.settings import Settings
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        repository_root=Path(__file__).parents[2] / "test_fixtures" / "repair_repository", data_dir=tmp_path / "data"
    )
    service = TaskService(settings, runner=EvidenceDouble())
    with TestClient(create_app(service=service)) as client:
        yield client, settings, service
    service.close()


def create(client, settings):
    response = client.post(
        "/api/tasks",
        json={
            "issue_description": "expired returns 500",
            "repository_path": str(settings.repository_root),
        },
    )
    assert response.status_code == 202
    return response.json()["task_id"]


def test_api_create_logs_diff_reject(client):
    api, settings, _ = client
    task_id = create(api, settings)
    state = api.get(f"/api/tasks/{task_id}").json()
    assert state["execution_status"] == "awaiting_approval"
    assert api.get(f"/api/tasks/{task_id}/events").json()["events"]
    diff = api.get(f"/api/tasks/{task_id}/diff").json()
    assert diff["matches_recorded"]
    assert (
        api.post(
            f"/api/tasks/{task_id}/approve", json={"diff_digest": diff["diff_digest"]}
        ).status_code
        == 409
    )
    assert (
        api.post(f"/api/tasks/{task_id}/reject", json={"diff_digest": diff["diff_digest"]}).json()[
            "execution_status"
        ]
        == "rejected"
    )
    assert api.post(f"/api/tasks/{task_id}/resume").status_code == 409


def test_approval_detects_tamper(client):
    api, settings, service = client
    task_id = create(api, settings)
    state = service.get(task_id)
    path = Path(state["workspace_path"]) / "auth.py"
    path.write_text(path.read_text() + "\n# changed after review\n")
    assert (
        api.post(
            f"/api/tasks/{task_id}/reject", json={"diff_digest": state["diff_digest"]}
        ).status_code
        == 409
    )


def test_invalid_paths_and_browser_origin(client):
    api, settings, _ = client
    assert api.get("/api/tasks/no-such-task").status_code == 404
    assert (
        api.post(
            "/api/tasks",
            json={
                "issue_description": "bad repository",
                "repository_path": str(settings.repository_root.parent),
            },
        ).status_code
        == 400
    )
    assert (
        api.post(
            "/api/tasks",
            headers={"Origin": "https://evil.example"},
            json={
                "issue_description": "expired returns 500",
                "repository_path": str(settings.repository_root),
            },
        ).status_code
        == 403
    )
    assert api.get("/api/tasks/no-such-task", headers={"Host": "evil.example"}).status_code == 403
