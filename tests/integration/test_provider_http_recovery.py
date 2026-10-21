"""Actual SDK over controlled HTTP transport; no real provider calls in these tests."""

import json
from pathlib import Path

import httpx
import pytest
from langchain_openai import ChatOpenAI

from app.agents.model import LiveModel, MockModel
from app.config.settings import Settings
from app.models.schemas import Patch, Plan, Review, TaskRequest
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble


@pytest.mark.parametrize("fault,kind,retryable", [
    (429, "rate_limit", True), (503, "provider_unavailable", True),
    (401, "credentials", False), ("timeout", "timeout", True),
])
def test_actual_sdk_error_reaches_persistent_recovery_state(tmp_path, monkeypatch,
                                                          fault, kind, retryable):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    requests = []
    fixture = MockModel()

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            if fault == "timeout":
                raise httpx.ReadTimeout("controlled timeout", request=request)
            return httpx.Response(fault, json={"error": {"message": "private-provider-detail"}},
                                  headers={"retry-after": "0"})
        schema_name = body["tools"][0]["function"]["name"]
        schema = {"Plan": Plan, "Patch": Patch, "Review": Review}[schema_name]
        payload = json.loads(body["messages"][1]["content"])
        value, _ = fixture.generate(schema, payload)
        return httpx.Response(200, json={
            "id": "controlled-response", "model": "controlled-model", "created": 0,
            "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": "controlled-call", "type": "function", "function": {
                        "name": schema_name, "arguments": value.model_dump_json(),
                    },
                }],
            }}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
        })

    settings = Settings(repository_root=Path(__file__).parents[2] / "test_fixtures" / "repair_repository",
                        data_dir=tmp_path / "data")
    model = LiveModel(settings)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    model.client = ChatOpenAI(model="controlled-model", http_client=client, max_retries=0)
    service = TaskService(settings, model=model, runner=EvidenceDouble())
    try:
        task = service.create(TaskRequest(repository_path=str(settings.repository_root),
                                          issue_description="expired token should return 401"))
        state = service.run(task["task_id"])
        assert state["failure"]["kind"] == kind
        assert state["execution_status"] == ("retryable" if retryable else "failed")
        assert state["model_calls"] == 1 and not state["token_usage_complete"]
        assert "private-provider-detail" not in json.dumps(state)
        if retryable:
            service.graph.update_state(service._config(state["thread_id"]), {
                "failure": {**state["failure"], "retry_at": 0},
            })
            recovered = service.run(task["task_id"])
            assert recovered["execution_status"] == "awaiting_approval"
            assert recovered["model_calls"] == 4
            assert recovered["input_tokens"] + recovered["output_tokens"] == 33
            assert not recovered["token_usage_complete"]
    finally:
        service.close()
        client.close()
