import time
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize("cooldown", [0, 300])
def test_ui_explains_cooldown_and_enables_only_ready_retries(monkeypatch, cooldown):
    state = {
        "execution_status": "retryable", "execution_history": [], "model_calls": 1,
        "input_tokens": 0, "output_tokens": 0, "token_usage_complete": False,
        "retry_count": 0, "provider_retry_count": 0, "error": "Model request failed: Timeout",
        "plan": None, "test_results": [], "review_results": [],
        "failure": {"kind": "timeout", "retry_at": time.time() + cooldown - 1},
    }

    def request(method, url, **kwargs):
        if url.endswith("/diff"):
            value = {"diff": "", "diff_digest": "", "matches_recorded": True}
        elif url.endswith("/events"):
            value = {"events": [], "retrieval": []}
        else:
            value = state
        return httpx.Response(200, json=value, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", request)
    app = AppTest.from_file(str(Path(__file__).parents[2] / "frontend/demo.py")).run()
    app.text_input[2].set_value("historical-task").run()
    assert not app.exception
    retry = next(button for button in app.button if button.label == "冷却后重试模型请求")
    assert retry.disabled is (cooldown > 0)
    assert any("此前补丁和测试记录会保留" in warning.value for warning in app.warning)
