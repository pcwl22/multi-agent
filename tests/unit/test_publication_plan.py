"""HTTP contract fixtures only; metadata is not actual Docker execution."""
import base64
import json
from pathlib import Path

import httpx
import pytest

from app.services.github import GitHubPublisher
from app.services.publication import PublicationPlan
from tests.unit.test_github import approved_state


class GitHubContract:
    def __init__(self, state):
        self.state = state
        self.head = "a" * 40
        self.default = "main"
        self.requests = []
        self.move_after_commit = False

    def __call__(self, request):
        path = request.url.path.split("/repos/owner/repo", 1)[-1]
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, body))
        if request.method == "GET":
            if not path:
                return httpx.Response(200, json={"default_branch": self.default})
            if path.startswith("/git/ref/heads/"):
                return httpx.Response(200, json={"object": {"sha": self.head}})
            if path.startswith("/git/commits/"):
                return httpx.Response(200, json={"tree": {"sha": "b" * 40}})
            if path.startswith("/contents/"):
                relative = path.removeprefix("/contents/").removeprefix("demo/")
                original = Path(self.state["workspace_path"]).parent / "baseline" / relative
                if original.is_file():
                    return httpx.Response(200, json={"type": "file", "encoding": "base64",
                        "content": base64.b64encode(original.read_bytes()).decode()})
                return httpx.Response(404)
        if path == "/git/commits" and self.move_after_commit:
            self.head = "e" * 40
        if path == "/pulls":
            return httpx.Response(201, json={"html_url": "https://github.com/owner/repo/pull/9"})
        return httpx.Response(201, json={"sha": "c" * 40})

    @property
    def writes(self):
        return [(path, body) for method, path, body in self.requests if method != "GET"]


@pytest.fixture
def publication(tmp_path):
    state = approved_state(tmp_path)
    state["test_results"][-1]["evidence"] = "docker"  # Contract metadata; never execution proof.
    transport = GitHubContract(state)
    client = GitHubPublisher("owner/repo", "contract-only-token", subdirectory="demo",
        client=httpx.Client(transport=httpx.MockTransport(transport)))
    yield state, transport, client
    client.close()


def test_preview_is_read_only_and_binds_target_parent_bytes_and_metadata(publication):
    state, api, client = publication
    plan = client.preview(state, title="fix: exact title", body="exact reviewed body")
    assert not api.writes
    assert plan.target.repository == "owner/repo" and plan.target.subdirectory == "demo"
    assert plan.base_sha == "a" * 40 and plan.base_tree == "b" * 40
    assert plan.body == "exact reviewed body" and plan.draft
    assert all(e.path.startswith("demo/") for e in plan.entries)
    assert "contract-only-token" not in plan.model_dump_json()
    assert PublicationPlan.model_validate_json(plan.model_dump_json()).digest() == plan.digest()
    assert client.preview(state, title=plan.title, body=plan.body).digest() == plan.digest()


@pytest.mark.parametrize("field", ["title", "body", "base_sha", "base_branch", "repository",
                                   "subdirectory", "content", "candidate_id"])
def test_changed_request_never_reuses_old_approval(publication, field):
    state, api, client = publication
    plan = client.preview(state)
    data = plan.model_dump()
    if field in {"repository", "subdirectory"}:
        data["target"][field] = "other/repo" if field == "repository" else "other"
    elif field == "content":
        data["entries"][0]["content"] += "\n# changed\n"
    else:
        data[field] = "f" * 40 if field == "base_sha" else "changed"
    changed = PublicationPlan.model_validate(data)
    with pytest.raises(ValueError, match="approval"):
        client.publish(state, plan=changed, approval_digest=plan.digest())
    assert not api.writes


@pytest.mark.parametrize("change", ["head", "default"])
def test_remote_baseline_or_default_branch_movement_stops_before_writes(publication, change):
    state, api, client = publication
    plan = client.preview(state)
    setattr(api, change, "e" * 40 if change == "head" else "release")
    with pytest.raises(ValueError, match="changed"):
        client.publish(state, plan=plan, approval_digest=plan.digest())
    assert not api.writes


def test_exact_request_is_the_only_content_written(publication):
    state, api, client = publication
    plan = client.preview(state, title="fix: reviewed", body="Reviewed exact body")
    assert client.publish(state, plan=plan, approval_digest=plan.digest()).endswith("/pull/9")
    writes = dict(api.writes)
    assert set(writes) == {"/git/trees", "/git/commits", "/git/refs", "/pulls"}
    assert writes["/git/commits"]["parents"] == [plan.base_sha]
    assert writes["/pulls"] == dict(title=plan.title, body=plan.body, head=plan.branch,
                                   base=plan.base_branch, draft=True)
    assert writes["/git/trees"]["tree"] == [e.model_dump(exclude={"before_sha256"}) for e in plan.entries]


def test_late_base_movement_leaves_no_branch_or_pull_request(publication):
    state, api, client = publication
    plan = client.preview(state)
    api.move_after_commit = True
    with pytest.raises(ValueError, match="orphan"):
        client.publish(state, plan=plan, approval_digest=plan.digest())
    assert {p for p, _ in api.writes} == {"/git/trees", "/git/commits"}


def test_custom_title_cannot_contain_newlines(publication):
    state, api, client = publication
    with pytest.raises(ValueError, match="one nonempty line"):
        client.preview(state, title="fix: first\nsecond")
    assert not api.writes


def test_new_task_contract_cannot_fall_back_to_diff_only_library_publish(publication):
    state, api, client = publication
    state["publication_contract_version"] = 1
    with pytest.raises(ValueError, match="publication request approval"):
        client.publish(state)
    assert not api.requests
