"""Real process loss + real Docker; model remains the explicit demo fixture adapter."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.services.tasks import TaskService

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1", reason="Docker tests are opt-in"
)]
ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("point,exit_code", [("before-test", 77), ("after-write", 78)])
def test_process_loss_resumes_recorded_patch_or_refuses_unrecorded_write(tmp_path, point, exit_code):
    settings = Settings(repository_root=ROOT / "demo_repository", data_dir=tmp_path / "data")
    service = TaskService(settings)
    task = service.create(TaskRequest(
        repository_path=str(settings.repository_root),
        issue_description="expired token returns 500, expected 401",
    ))
    service.close()
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("GITHUB_TOKEN", None)
    env["REPOPILOT_MODEL_MODE"] = "mock"
    result = subprocess.run([
        sys.executable, "-m", "tests.integration.recovery_worker", str(settings.data_dir),
        str(settings.repository_root), task["task_id"], point,
    ], cwd=ROOT, env=env, capture_output=True, timeout=45)
    assert result.returncode == exit_code, result.stderr.decode(errors="replace")
    assert (settings.data_dir / "crash-marker.txt").exists()
    restarted = TaskService(settings)
    try:
        state = restarted.get(task["task_id"])
        if point == "after-write":
            assert state["attempts"] == 0
            with pytest.raises(ValueError, match="outside the recorded repair"):
                restarted.run(task["task_id"])
            assert restarted.diff(task["task_id"])["diff"]
            assert not restarted.get(task["task_id"])["test_results"]
        else:
            assert state["attempts"] == 1 and len(state["patches"]) == 1
            state = restarted.run(task["task_id"])
            assert state["execution_status"] == "awaiting_approval"
            assert state["attempts"] == 1 and len(state["patches"]) == 1
            assert state["test_results"][-1]["status"] == "passed"
            assert state["test_results"][-1]["evidence"] == "docker"
            assert state["test_results"][-1]["image_id"]
    finally:
        restarted.close()
