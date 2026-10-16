import base64
import json

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.model import MockModel
from app.config.settings import Settings
from app.graph.workflow import build_graph
from app.services.github import GitHubPublisher, read_issue
from tests.integration.test_mvp import EvidenceDouble, initial


def approved_state(tmp_path):
    state = initial(tmp_path)
    graph = build_graph(Settings(), MockModel(), EvidenceDouble(), InMemorySaver())
    result = graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    result.update(approval_status="approved", execution_status="approved")
    return result


def transport(state, requests, *, mismatch=False):
    def handler(request):
        requests.append((request.method, request.url.path, request.content))
        path = request.url.path.split("/repos/owner/repo", 1)[-1]
        if request.method == "GET":
            if path == "":
                return httpx.Response(200, json={"default_branch": "main"})
            if path.startswith("/git/ref/"):
                return httpx.Response(200, json={"object": {"sha": "base-sha"}})
            if path == "/git/commits/base-sha":
                return httpx.Response(200, json={"tree": {"sha": "base-tree"}})
            if path == "/contents/auth.py":
                from pathlib import Path

                content = (Path(state["workspace_path"]).parent / "baseline/auth.py").read_bytes()
                return httpx.Response(
                    200,
                    json={
                        "type": "file",
                        "encoding": "base64",
                        "content": base64.b64encode(b"different" if mismatch else content).decode(),
                    },
                )
            return httpx.Response(404)
        if path == "/git/trees":
            return httpx.Response(201, json={"sha": "new-tree"})
        if path == "/git/commits":
            return httpx.Response(201, json={"sha": "new-commit"})
        if path == "/git/refs":
            return httpx.Response(201, json={"ref": "new-branch"})
        if path == "/pulls":
            assert json.loads(request.content)["draft"] is True
            return httpx.Response(201, json={"html_url": "https://github.com/owner/repo/pull/1"})
        raise AssertionError(path)

    return httpx.MockTransport(handler)


def test_pr_rest_contract(tmp_path):
    state, requests = approved_state(tmp_path), []
    publisher = GitHubPublisher(
        "owner/repo", "test-token", client=httpx.Client(transport=transport(state, requests))
    )
    assert publisher.publish(state).endswith("/pull/1")
    tree = json.loads(
        next(content for method, path, content in requests if path.endswith("/trees"))
    )
    assert tree["base_tree"] == "base-tree"
    assert {entry["path"] for entry in tree["tree"]} == {
        "auth.py",
        "tests/test_expired_regression.py",
    }


def test_remote_mismatch_stops_all_writes(tmp_path):
    state, requests = approved_state(tmp_path), []
    publisher = GitHubPublisher(
        "owner/repo",
        "test-token",
        client=httpx.Client(transport=transport(state, requests, mismatch=True)),
    )
    with pytest.raises(ValueError, match="baseline differs"):
        publisher.publish(state)
    assert all(method == "GET" for method, _, _ in requests)


def test_publisher_requires_approval(tmp_path):
    state = approved_state(tmp_path)
    state["approval_status"] = "pending"
    publisher = GitHubPublisher(
        "owner/repo",
        "test-token",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: pytest.fail("No request allowed"))
        ),
    )
    with pytest.raises(ValueError, match="approval"):
        publisher.publish(state)


def test_issue_import_is_scoped_to_configured_repository():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"title": "expired token", "body": "expected 401"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert "expected 401" in read_issue(
        "https://github.com/owner/repo/issues/12", "owner/repo", client=client
    )
    with pytest.raises(ValueError, match="configured"):
        read_issue("http://127.0.0.1/secrets", "owner/repo", client=client)
    with pytest.raises(ValueError, match="configured"):
        read_issue("https://github.com/other/repo/issues/1", "owner/repo", client=client)
    assert len(requests) == 1
