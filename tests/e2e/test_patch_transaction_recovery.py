"""Real process exit and Docker evidence with explicitly fixture-only model."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.agents.model import MockModel
from app.config.settings import Settings
from app.models.schemas import Patch, TaskRequest
from app.services.tasks import TaskService

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1", reason="Docker opt-in")]


@pytest.mark.parametrize("policy", ["preserve", "isolated"])
@pytest.mark.parametrize("point", ["prepared", "temporary-1", "file-1", "written"])
def test_hard_loss_recovers_journal_once_then_obtains_real_docker_evidence(tmp_path, policy, point):
    root = Path(__file__).parents[2]
    source = root / "test_fixtures/repair_repository"
    settings = Settings(repository_root=source, data_dir=tmp_path / "data", patch_transactions=True,
                        retry_workspace_policy=policy, _env_file=None)
    service = TaskService(settings)
    task = service.create(TaskRequest(repository_path=str(source),
                                    issue_description="expired returns 500 expected 401"))
    service.close()
    env = dict(os.environ)
    for secret in ["OPENAI_API_KEY", "GITHUB_TOKEN", "LANGSMITH_API_KEY"]:
        env.pop(secret, None)
    worker = root / "tests/integration/patch_transaction_worker.py"
    lost = subprocess.run([sys.executable, "-I", str(worker), str(settings.data_dir), str(source),
                           task["task_id"], point], env=env, capture_output=True, timeout=45)
    assert lost.returncode == 86, lost.stderr.decode(errors="replace")
    assert (settings.data_dir / "patch-calls.txt").read_text().splitlines() == ["Patch"]

    class NoPatchReplay(MockModel):
        def generate(self, schema, payload):
            assert schema is not Patch, "Recovery must use the durable response, not regenerate"
            return super().generate(schema, payload)

    # Persisted task policy survives a changed process default.
    settings.patch_transactions = False
    restarted = TaskService(settings, model=NoPatchReplay())
    try:
        before = restarted.get(task["task_id"])
        assert before["attempts"] == 0 and not before["test_results"]
        with pytest.raises(ValueError, match="Pending patch transaction"):
            restarted.run(task["task_id"])
        recovery = restarted.patch_recovery(task["task_id"])
        item = recovery["transactions"][0]
        assert item["recoverable"] and item["candidate_id"] == before.get("candidate_id")
        recovered = restarted.recover_patch(task["task_id"], item["journal_digest"])
        assert recovered["attempts"] == 1 and recovered["candidate_id"] == before["candidate_id"]
        final = restarted.run(task["task_id"])
        assert final["execution_status"] == "awaiting_approval"
        assert final["attempts"] == len(final["patches"]) == 1
        assert final["test_results"][-1]["status"] == "passed"
        assert final["test_results"][-1]["evidence"] == "docker"
        assert final["regression_results"][-1]["status"] == "demonstrated"
        assert not restarted.patch_recovery(task["task_id"])["required"]
        baseline = Path(before["workspace_path"]).parent / "baseline"
        assert "status_code=500" in (baseline / "auth.py").read_text()
    finally:
        restarted.close()


@pytest.mark.parametrize("policy", ["preserve", "isolated"])
def test_loss_after_durable_checkpoint_only_acknowledges_without_replaying(tmp_path, policy):
    root = Path(__file__).parents[2]
    source = root / "test_fixtures/repair_repository"
    settings = Settings(repository_root=source, data_dir=tmp_path / "data", patch_transactions=True,
                        retry_workspace_policy=policy, _env_file=None)
    service = TaskService(settings)
    task = service.create(TaskRequest(repository_path=str(source), issue_description="expired should return 401"))
    service.close()
    env = dict(os.environ)
    for secret in ["OPENAI_API_KEY", "GITHUB_TOKEN", "LANGSMITH_API_KEY"]:
        env.pop(secret, None)
    worker = root / "tests/integration/patch_transaction_worker.py"
    lost = subprocess.run([sys.executable, "-I", str(worker), str(settings.data_dir), str(source),
                           task["task_id"], "checkpointed"], env=env, capture_output=True, timeout=45)
    assert lost.returncode == 86, lost.stderr.decode(errors="replace")
    restarted = TaskService(settings)
    try:
        before = restarted.get(task["task_id"])
        assert before["execution_status"] == "awaiting_approval"
        assert before["test_results"][-1]["evidence"] == "docker"
        patch = restarted.diff(task["task_id"])
        assert not restarted.patch_recovery(task["task_id"])["required"]
        assert restarted.get(task["task_id"])["patches"] == before["patches"]
        assert restarted.diff(task["task_id"]) == patch
        assert (settings.data_dir / "patch-calls.txt").read_text().splitlines() == ["Patch"]
    finally:
        restarted.close()
