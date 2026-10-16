import base64
import json
from pathlib import Path

import httpx
import pytest

from app.services.github import GitHubPublisher
from tests.unit.test_github import approved_state


def test_nested_repository_maps_remote_reads_and_writes(tmp_path: Path):
    state = approved_state(tmp_path)
    before = (Path(state["workspace_path"]).parent / "baseline/auth.py").read_bytes()
    writes = []
    reads = []

    def handler(request):
        path = request.url.path.split("/repos/owner/repo", 1)[-1]
        if request.method == "GET":
            reads.append(path)
            if path == "":
                return httpx.Response(200, json={"default_branch": "main"})
            if path.startswith("/git/ref/"):
                return httpx.Response(200, json={"object": {"sha": "head"}})
            if path == "/git/commits/head":
                return httpx.Response(200, json={"tree": {"sha": "tree"}})
            if path == "/contents/demo_repository/auth.py":
                return httpx.Response(
                    200,
                    json={
                        "type": "file",
                        "encoding": "base64",
                        "content": base64.b64encode(before).decode(),
                    },
                )
            return httpx.Response(404)
        body = json.loads(request.content)
        writes.append((path, body))
        if path == "/pulls":
            return httpx.Response(201, json={"html_url": "https://github.com/owner/repo/pull/1"})
        return httpx.Response(201, json={"sha": "created"})

    publisher = GitHubPublisher(
        "owner/repo",
        "unit-test-token",
        subdirectory="demo_repository",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert publisher.publish(state).endswith("/pull/1")
    assert "/contents/demo_repository/auth.py" in reads
    tree = next(body for path, body in writes if path == "/git/trees")
    assert {entry["path"] for entry in tree["tree"]} == {
        "demo_repository/auth.py",
        "demo_repository/tests/test_expired_regression.py",
    }


@pytest.mark.parametrize(
    "prefix", ["../other", "/absolute", "demo/../other", "C:\\repo", "demo//nested", ".git"]
)
def test_invalid_remote_prefix_is_rejected_before_any_request(prefix):
    with pytest.raises(ValueError, match="repository-relative"):
        GitHubPublisher("owner/repo", "unit-test-token", subdirectory=prefix)
