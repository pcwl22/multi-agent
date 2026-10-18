import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.evaluation.runner import holdout_workspace
from app.models.schemas import TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService


@pytest.mark.docker
@pytest.mark.skipif(
    os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1",
    reason="Set REPOPILOT_RUN_DOCKER_TESTS=1 with Docker daemon and image ready",
)
def test_real_container_repair_and_holdout(tmp_path):
    root = Path(__file__).parents[2]
    settings = Settings(repository_root=root / "test_fixtures" / "repair_repository", data_dir=tmp_path / "data")
    runner = DockerRunner(settings)
    baseline = tmp_path / "baseline_holdout"
    acceptance = root / "app/evaluation/acceptance/test_auth_acceptance.py"
    holdout_workspace(settings.repository_root, baseline, acceptance)
    before = runner.run(baseline)
    assert before.status == "failed" and before.failed == 1 and before.passed == 2
    service = TaskService(settings)
    try:
        task = service.create(
            TaskRequest(
                repository_path=str(settings.repository_root),
                issue_description="expired returns 500 expected 401",
            )
        )
        repaired = service.run(task["task_id"])
        assert repaired["execution_status"] == "awaiting_approval"
        holdout_workspace(Path(repaired["workspace_path"]), tmp_path / "holdout", acceptance)
        after = runner.run(tmp_path / "holdout")
        assert after.status == "passed" and after.passed == 3
        assert (
            service.decide(task["task_id"], True, repaired["diff_digest"])["execution_status"]
            == "approved"
        )
    finally:
        service.close()


@pytest.mark.docker
@pytest.mark.skipif(
    os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1",
    reason="Docker UI integration is explicitly opt-in",
)
def test_streamlit_api_docker_roundtrip(tmp_path, monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from streamlit.testing.v1 import AppTest

    from app.api.main import create_app

    root = Path(__file__).parents[2]
    settings = Settings(repository_root=root / "test_fixtures" / "repair_repository", data_dir=tmp_path / "data")
    service = TaskService(settings)
    try:
        with TestClient(create_app(service=service)) as api:
            monkeypatch.setattr(
                httpx, "request", lambda method, url, **kwargs: api.request(method, url, **kwargs)
            )
            demo = AppTest.from_file(str(root / "frontend/demo.py")).run(timeout=15)
            demo.text_input[1].set_value(str(settings.repository_root)).run(timeout=15)
            demo.button[0].click().run(timeout=30)
            assert not demo.exception
            task_id = demo.session_state["task_id"]
            assert service.get(task_id)["execution_status"] == "awaiting_approval"
            assert "status_code=401" in demo.code[0].value
            next(button for button in demo.button if button.label == "拒绝当前 Diff").click().run(
                timeout=15
            )
            assert service.get(task_id)["execution_status"] == "rejected"
    finally:
        service.close()
