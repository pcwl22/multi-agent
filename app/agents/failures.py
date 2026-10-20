"""Safe provider error categories; never persist provider response bodies."""

import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from openai import APIConnectionError, APITimeoutError

from app.agents.transport import transport_diagnostics


def provider_failure(exc: Exception, *, streaming: bool | None = None) -> dict:
    status = getattr(exc, "status_code", None)
    if status == 429:
        kind, retryable, delay = "rate_limit", True, 300.0
    elif isinstance(exc, (TimeoutError, httpx.TimeoutException, APITimeoutError)):
        kind, retryable, delay = "timeout", True, 5.0
    elif isinstance(exc, (httpx.NetworkError, httpx.ProxyError, httpx.ProtocolError, APIConnectionError)):
        kind, retryable, delay = "connection", True, 10.0
    elif isinstance(status, int) and 500 <= status < 600:
        kind, retryable, delay = "provider_unavailable", True, 30.0
    elif status in {401, 403}:
        kind, retryable, delay = "credentials", False, 0.0
    else:
        kind, retryable, delay = "request_error", False, 0.0
    response = getattr(exc, "response", None)
    header = response.headers.get("retry-after") if response is not None else None
    if retryable and header:
        try:
            seconds = float(header)
            if math.isfinite(seconds):
                delay = max(delay, seconds)
        except (ValueError, TypeError):
            try:
                when = parsedate_to_datetime(header)
                delay = max(delay, (when - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return {
        "diagnostics": transport_diagnostics(exc, streaming=streaming),
        "kind": kind,
        "retryable": retryable,
        "retry_after_seconds": min(max(delay, 0.0), 86400.0),
    }
