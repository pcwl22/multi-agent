from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest


def test_ui_explains_backend_rejection_instead_of_only_http_status(monkeypatch):
    def rejected_request(method, url, **kwargs):
        return httpx.Response(
            409,
            json={"detail": "GITHUB_TOKEN is required for PR publication"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx, "request", rejected_request)
    app = AppTest.from_file(str(Path(__file__).parents[2] / "frontend/demo.py")).run()
    app.button[0].click().run()
    assert not app.exception
    assert "GITHUB_TOKEN is required for PR publication" in app.error[0].value
    assert "HTTP 409" in app.error[0].value
