from pathlib import Path

import pytest

from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble


@pytest.mark.parametrize("mode", ["single", "multi_full"])
def test_empty_repository_terminates_at_locator(tmp_path: Path, mode: str):
    source = tmp_path / "empty"
    source.mkdir()
    service = TaskService(
        Settings(repository_root=source, data_dir=tmp_path / "data"), runner=EvidenceDouble()
    )
    try:
        task = service.create(
            TaskRequest(
                repository_path=str(source),
                issue_description="expired token should return 401",
                mode=mode,
            )
        )
        state = service.run(task["task_id"])
        assert state["execution_status"] == "failed"
        assert "no readable supported" in state["error"]
        assert state["attempts"] == 0
        assert sum(e["node"] == "locator" for e in state["execution_history"]) == 1
    finally:
        service.close()
