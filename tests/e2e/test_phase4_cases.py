import json
import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.evaluation.runner import holdout_workspace
from app.models.schemas import TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService

DATASET = json.loads(
    (Path(__file__).parents[2] / "app/evaluation/dataset.json").read_text(encoding="utf-8")
)
pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1",
        reason="Docker dataset tests are opt-in",
    ),
]


@pytest.mark.parametrize("case", DATASET, ids=lambda case: case["id"])
def test_each_distinct_bug_fails_before_and_passes_after(case, tmp_path: Path):
    root = Path(__file__).parents[2]
    settings = Settings(repository_root=root / "test_fixtures" / "repair_repository", data_dir=tmp_path / "data")
    acceptance = root / "app/evaluation/acceptance" / case["acceptance"]
    holdout_workspace(settings.repository_root, tmp_path / "before", acceptance)
    runner = DockerRunner(settings)
    before = runner.run(tmp_path / "before")
    assert before.status == "failed" and before.failed > 0 and before.errors == 0
    service = TaskService(settings)
    try:
        task = service.create(
            TaskRequest(
                repository_path=str(settings.repository_root), issue_description=case["issue"]
            )
        )
        state = service.run(task["task_id"])
        assert state["execution_status"] == "awaiting_approval"
        holdout_workspace(Path(state["workspace_path"]), tmp_path / "after", acceptance)
        after = runner.run(tmp_path / "after")
        assert after.status == "passed" and after.failed == 0 and after.errors == 0
        assert after.image_id and after.image_id.startswith("sha256:")
        assert len(state["context"]) <= settings.context_chars
        assert not any("acceptance" in path for path in state["located_files"])
        assert all(
            "test_acceptance" not in path.name for path in Path(state["workspace_path"]).rglob("*.py")
        )
    finally:
        service.close()
