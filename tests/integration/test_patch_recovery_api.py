"""Local API recovery with an explicit non-executing runner double."""
from fastapi.testclient import TestClient

import app.services.transactions as journal
from app.api.main import create_app
from tests.unit.test_patch_transactions import make_task


def test_recovery_api_rejects_stale_digest_then_resumes_only_after_explicit_action(tmp_path, monkeypatch):
    service, task, model = make_task(tmp_path, "isolated")

    def interrupted(point, receipt):
        if point == "file-1":
            raise OSError("Controlled API recovery interruption")

    monkeypatch.setattr(journal, "journal_checkpoint", interrupted)
    try:
        failed = service.run(task["task_id"])
        base = f"/api/tasks/{task['task_id']}"
        with TestClient(create_app(service=service)) as api:
            assert api.post(base + "/resume").status_code == 409
            preview = api.get(base + "/recovery/patch")
            assert preview.status_code == 200 and preview.json()["required"]
            digest = preview.json()["transactions"][0]["journal_digest"]
            assert api.post(base + "/recovery/patch", json={"journal_digest": "f" * 64}).status_code == 409
            assert not service.get(task["task_id"])["test_results"]
            monkeypatch.setattr(journal, "journal_checkpoint", lambda *args: None)
            result = api.post(base + "/recovery/patch", json={"journal_digest": digest})
            assert result.status_code == 200 and result.json()["attempts"] == 1
            assert api.post(base + "/resume").status_code == 202
            state = service.get(task["task_id"])
            assert state["execution_status"] == "awaiting_approval" and model.patch_calls == 1
            assert state["candidate_id"] == failed["candidate_id"]
            assert not api.get(base + "/recovery/patch").json()["required"]
    finally:
        service.close()
