import httpx
import pytest
from openai import APIStatusError

from app.agents.failures import provider_failure


@pytest.mark.parametrize("status,kind,retryable", [
    (429, "rate_limit", True), (503, "provider_unavailable", True),
    (401, "credentials", False), (403, "credentials", False),
    (400, "request_error", False),
])
def test_status_classification_ignores_private_response_body(status, kind, retryable):
    response = httpx.Response(status, headers={"retry-after": "600"},
                              request=httpx.Request("POST", "https://provider.invalid/v1"))
    error = APIStatusError("private provider message", response=response, body={"secret": "private"})
    result = provider_failure(error)
    assert result["kind"] == kind and result["retryable"] is retryable
    assert "private" not in str(result)
    assert result["retry_after_seconds"] == (600 if retryable else 0)


def test_timeout_and_connection_failures_are_retryable():
    assert provider_failure(TimeoutError())["kind"] == "timeout"
    assert provider_failure(httpx.ConnectError("private"))["kind"] == "connection"
