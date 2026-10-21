"""Transport doubles validate SSE handling; these are not live model tests."""
import json

import httpx
import langchain_openai
import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.agents.model import LiveModel
from app.config.settings import Settings
from app.models.schemas import Plan


@pytest.mark.parametrize("include_usage", [True, False])
def test_streamed_function_arguments_and_usage_are_observed(monkeypatch, include_usage):
    plan = {
        "issue_summary": "expired", "suspected_modules": ["auth.py"],
        "search_strategy": ["expired"], "repair_steps": ["401"],
        "validation_strategy": ["Docker"],
    }
    arguments = json.dumps(plan)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        base = {"id": "chatcmpl-sse-test", "object": "chat.completion.chunk",
                "created": 0, "model": "test"}
        chunks = [
            {**base, "choices": [{"index": 0, "finish_reason": None, "delta": {
                "role": "assistant", "tool_calls": [{"index": 0, "id": "call_1",
                "type": "function", "function": {"name": "Plan",
                                                "arguments": arguments[:40]}}]}}]},
            {**base, "choices": [{"index": 0, "finish_reason": None, "delta": {
                "tool_calls": [{"index": 0, "function": {"arguments": arguments[40:]}}]}}]},
            {**base, "choices": [{"index": 0, "finish_reason": "tool_calls", "delta": {}}]},
        ]
        if include_usage:
            chunks.append({**base, "choices": [], "usage": {
                "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
        body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
        return httpx.Response(200, text=body + "data: [DONE]\n\n",
                              headers={"content-type": "text/event-stream"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        def constructor(**kwargs):
            kwargs["max_retries"] = 0
            return ChatOpenAI(**kwargs, http_client=client)

        monkeypatch.setattr(langchain_openai, "ChatOpenAI", constructor)
        adapter = LiveModel(Settings(_env_file=None, model_name="test", model_streaming=True,
                                     openai_api_key=SecretStr("unit-test-only")))
        value, stats = adapter.generate(Plan, {"issue_description": "expired"})
    assert value.issue_summary == "expired"
    assert seen[0]["stream"] is True
    assert seen[0]["stream_options"]["include_usage"] is True
    assert stats["streaming"] is True and stats["calls"] == 1
    assert stats["usage_complete"] is include_usage
    if include_usage:
        assert stats["input_tokens"] == 10 and stats["output_tokens"] == 20
    else:
        assert stats["input_tokens"] == 0 and stats["output_tokens"] == 0


def test_nonstreaming_default_and_explicit_usage_opt_out(monkeypatch):
    seen = []

    def constructor(**kwargs):
        seen.append(kwargs)
        return object()

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", constructor)
    LiveModel(Settings(_env_file=None))
    LiveModel(Settings(_env_file=None, model_streaming=True, model_stream_usage=False))
    assert seen[0]["streaming"] is False and seen[0]["stream_usage"] is None
    assert seen[1]["streaming"] is True and seen[1]["stream_usage"] is False
