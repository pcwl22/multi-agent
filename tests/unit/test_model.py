import json

import httpx
import pytest
from langchain_openai import ChatOpenAI

from app.agents.model import LiveModel, ModelFailure
from app.config.settings import Settings
from app.models.schemas import Plan


def test_real_langchain_structured_adapter_with_fake_transport(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    plan = dict(
        issue_summary="expired",
        suspected_modules=["auth.py"],
        search_strategy=["expired"],
        repair_steps=["401"],
        validation_strategy=["pytest"],
    )
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "Plan", "arguments": json.dumps(plan)},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            },
        )

    adapter = LiveModel(Settings())
    adapter.client = ChatOpenAI(
        model="test",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    value, stats = adapter.generate(Plan, {"issue_description": "expired"})
    assert value.issue_summary == "expired"
    assert stats["calls"] == 1 and stats["input_tokens"] == 10 and stats["output_tokens"] == 20
    assert seen[0]["tools"][0]["function"]["name"] == "Plan"


def test_parse_failure_has_bounded_retries_and_usage(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")

    class Raw:
        usage_metadata = {"input_tokens": 10, "output_tokens": 5}

    class InvalidClient:
        def with_structured_output(self, *args, **kwargs):
            return self

        def invoke(self, messages):
            return {"raw": Raw(), "parsed": None}

    adapter = LiveModel(Settings())
    adapter.client = InvalidClient()
    with pytest.raises(ModelFailure) as result:
        adapter.generate(Plan, {"issue_description": "expired"})
    assert result.value.stats["calls"] == 2
    assert result.value.stats["input_tokens"] == 20


def test_transport_failure_marks_unknown_usage(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")

    class BrokenClient:
        def with_structured_output(self, *args, **kwargs):
            return self

        def invoke(self, messages):
            raise TimeoutError("test transport timeout")

    adapter = LiveModel(Settings())
    adapter.client = BrokenClient()
    with pytest.raises(ModelFailure) as result:
        adapter.generate(Plan, {})
    assert result.value.stats["calls"] == 1
    assert result.value.stats["usage_complete"] is False
