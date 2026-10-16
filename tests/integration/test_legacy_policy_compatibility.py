import json
from pathlib import Path

from app.agents.model import MockModel
from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble


def test_task_without_new_fields_keeps_legacy_workspace_after_default_changes(tmp_path):
    settings = Settings(repository_root=Path(__file__).parents[2] / "demo_repository",
                        data_dir=tmp_path / "data")
    service = TaskService(settings, model=MockModel(), runner=EvidenceDouble())
    task = service.create(TaskRequest(repository_path=str(settings.repository_root),
                                      issue_description="expired token should return 401"))
    legacy = {k: v for k, v in task.items() if k not in {
        "task_path", "retry_workspace_policy", "baseline_manifest", "candidate_id",
        "candidate_number", "approved_candidate_id", "previous_candidate_diff", "attempt_history",
    }}
    service.conn.execute("UPDATE tasks SET initial=? WHERE task_id=?",
                         (json.dumps(legacy), task["task_id"]))
    service.conn.commit()
    service.close()
    settings.retry_workspace_policy = "isolated"
    restored = TaskService(settings, model=MockModel(), runner=EvidenceDouble())
    try:
        state = restored.run(task["task_id"])
        assert state["execution_status"] == "awaiting_approval"
        assert state["workspace_path"] == task["workspace_path"]
        assert state.get("retry_workspace_policy", "preserve") == "preserve"
        assert not (Path(task["workspace_path"]).parent / "attempts").exists()
        assert restored.decide(task["task_id"], False, state["diff_digest"])["execution_status"] == "rejected"
    finally:
        restored.close()
