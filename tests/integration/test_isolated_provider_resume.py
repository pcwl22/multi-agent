from pathlib import Path

from app.agents.model import MockModel
from app.config.settings import Settings
from app.models.schemas import Patch, TaskRequest
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble
from tests.integration.test_provider_recovery import TemporaryFailure, expire_cooldown


def test_transient_coder_failure_resumes_same_candidate_after_reopen(tmp_path):
    settings = Settings(repository_root=Path(__file__).parents[2] / "test_fixtures" / "repair_repository",
                        data_dir=tmp_path / "data", retry_workspace_policy="isolated")
    service = TaskService(settings, model=TemporaryFailure(Patch), runner=EvidenceDouble())
    task = service.create(TaskRequest(repository_path=str(settings.repository_root),
                                      issue_description="expired token should return 401"))
    failed = service.run(task["task_id"])
    assert failed["execution_status"] == "retryable"
    expire_cooldown(service, task["task_id"])
    service.close()
    # The persisted policy wins over a changed server default.
    settings.retry_workspace_policy = "preserve"
    restarted = TaskService(settings, model=MockModel(), runner=EvidenceDouble())
    try:
        result = restarted.run(task["task_id"])
        assert result["execution_status"] == "awaiting_approval"
        assert result["retry_workspace_policy"] == "isolated"
        assert result["candidate_id"] == failed["candidate_id"]
        assert result["candidate_number"] == 1 and not result["attempt_history"]
        assert result["attempts"] == 1 and result["retry_count"] == 0
        assert result["provider_retry_count"] == 1 and not result["token_usage_complete"]
    finally:
        restarted.close()
