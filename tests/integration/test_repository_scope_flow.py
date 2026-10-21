from pathlib import Path

import pytest

from app.agents.model import MockModel
from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble


@pytest.mark.parametrize("enabled", [True, False])
def test_scope_reaches_all_model_roles_without_rewriting_edits(tmp_path, enabled):
    seen = []

    class RecordingDemoModel(MockModel):
        def generate(self, schema, payload):
            scope = payload.get("repository_path_scope")
            seen.append(schema.__name__)
            if enabled:
                assert scope["remote_subdirectory"] == "packages/service"
                assert {"remote_path": "packages/service/auth.py",
                        "workspace_edit_path": "auth.py"} in scope["path_mapping"]
            else:
                assert scope is None
            return super().generate(schema, payload)

    source = Path(__file__).parents[2] / "test_fixtures" / "repair_repository"
    service = TaskService(Settings(repository_root=source, data_dir=tmp_path / "data",
                                  github_repository_subdirectory="packages/service",
                                  model_path_scope=enabled),
                          model=RecordingDemoModel(), runner=EvidenceDouble())
    try:
        task = service.create(TaskRequest(repository_path=str(source),
                                          issue_description="expired token returns 500 expected 401"))
        state = service.run(task["task_id"])
        assert state["execution_status"] == "awaiting_approval"
        assert seen == ["Plan", "Patch", "Review"]
        assert state["patches"][0]["edits"][0]["path"] == "auth.py"
    finally:
        service.close()
