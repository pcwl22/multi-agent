import os
import subprocess
import sys
from pathlib import Path

import pytest

import app
from app.config.settings import Settings
from app.services.tasks import TaskService
from tests.e2e.test_isolated_attempts import CandidateFixture, make_service

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1", reason="Docker tests are opt-in"
)]


@pytest.mark.parametrize("point,code", [
    ("prepared-before-checkpoint", 79), ("after-write", 80), ("before-test", 81),
])
def test_process_loss_keeps_candidate_identity_and_never_replays_unrecorded_edits(tmp_path, point, code):
    service, task, source, _ = make_service(tmp_path, "page-tail")
    data = service.settings.data_dir
    service.close()
    worker = Path(__file__).parents[1] / "integration/isolated_recovery_worker.py"
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("GITHUB_TOKEN", None)
    result = subprocess.run([
        sys.executable, "-I", "-c",
        "import app, runpy, sys; sys.argv = sys.argv[1:]; "
        "runpy.run_path(sys.argv[0], run_name='__main__')",
        str(worker), str(data), str(source), task["task_id"], point,
    ], env=env, capture_output=True, timeout=45)
    assert result.returncode == code, result.stderr.decode(errors="replace")
    assert (data / "worker-app.txt").read_text() == str(Path(app.__file__).resolve())
    model = CandidateFixture("page-tail")
    model.calls = 1  # The next fixture response is the complete correct candidate.
    settings = Settings(repository_root=source, data_dir=data, max_retries=1)
    restarted = TaskService(settings, model=model)
    try:
        before = restarted.get(task["task_id"])
        if point == "after-write":
            assert before["candidate_number"] == 2 and before["attempts"] == 1
            with pytest.raises(ValueError, match="outside the recorded"):
                restarted.run(task["task_id"])
        else:
            state = restarted.run(task["task_id"])
            assert state["execution_status"] == "awaiting_approval"
            assert state["candidate_number"] == state["attempts"] == 2
            assert state["retry_count"] == 1 and len(state["attempt_history"]) == 1
            if point == "prepared-before-checkpoint":
                assert state["candidate_id"] == (data / "prepared-id.txt").read_text()
                assert model.calls == 2
            else:
                assert state["candidate_id"] == before["candidate_id"] and model.calls == 1
            assert state["test_results"][-1]["evidence"] == "docker"
        assert (Path(before["task_path"]) / "attempts/0001/workspace/tests/test_generated.py").is_file()
    finally:
        restarted.close()
