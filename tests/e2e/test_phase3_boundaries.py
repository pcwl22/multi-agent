import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1",
        reason="Docker boundary tests are opt-in",
    ),
]


class PublicationDouble:
    """Remote writes are replaced; approval still requires real Docker test evidence."""

    def __init__(self, fail: bool = False):
        self.calls = 0
        self.fail = fail

    def publish(self, state: dict) -> str:
        self.calls += 1
        assert state["approval_status"] == "approved"
        if self.fail:
            raise TimeoutError("Simulated uncertain remote write")
        return "https://github.com/example/fixture/pull/1"


@pytest.fixture
def approved_task(tmp_path: Path):
    root = Path(__file__).parents[2] / "test_fixtures" / "repair_repository"
    settings = Settings(repository_root=root, data_dir=tmp_path / "data")
    service = TaskService(settings)
    task = service.create(
        TaskRequest(repository_path=str(root), issue_description="expired token should return 401")
    )
    state = service.run(task["task_id"])
    assert state["execution_status"] == "awaiting_approval"
    yield service, settings, state
    service.close()


def test_publication_gate_and_repeated_success(approved_task):
    service, settings, state = approved_task
    publisher = PublicationDouble()
    with pytest.raises(ValueError, match="Explicit human approval"):
        service.publish(state["task_id"], state["diff_digest"], publisher=publisher)
    assert publisher.calls == 0
    service.decide(state["task_id"], True, state["diff_digest"])
    first = service.publish(state["task_id"], state["diff_digest"], publisher=publisher)
    assert service.publish(state["task_id"], state["diff_digest"], publisher=publisher) == first
    assert publisher.calls == 1
    restored = TaskService(settings)
    try:
        assert (
            restored.publish(state["task_id"], state["diff_digest"], publisher=publisher) == first
        )
        assert publisher.calls == 1
    finally:
        restored.close()


def test_uncertain_publication_is_not_replayed(approved_task):
    service, _, state = approved_task
    service.decide(state["task_id"], True, state["diff_digest"])
    publisher = PublicationDouble(fail=True)
    with pytest.raises(ValueError, match="interrupted"):
        service.publish(state["task_id"], state["diff_digest"], publisher=publisher)
    with pytest.raises(ValueError, match="uncertain"):
        service.publish(state["task_id"], state["diff_digest"], publisher=publisher)
    assert publisher.calls == 1


def test_real_container_output_is_truncated(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_noisy.py").write_text(
        'def test_noisy():\n    assert False, "x" * 250000\n', encoding="utf-8"
    )
    result = DockerRunner(Settings()).run(tmp_path)
    assert result.status == "failed" and result.failed == 1
    assert result.output_truncated
    assert len(result.stdout) <= 20000 and len(result.stderr) <= 20000
