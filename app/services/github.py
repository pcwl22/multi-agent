"""Optional GitHub writes: only called after explicit, digest-bound human approval."""

import base64
import hashlib
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from app.services.attempts import file_manifest, manifest_digest, validate_isolated
from app.services.publication import PublicationEntry, PublicationPlan, PublicationTarget
from app.tools.repository import Repository, diff_repositories, digest


def read_issue(url: str, repository: str | None, token: str = "", *, client=None) -> str:
    match = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)", url
    )
    if match is None or not repository or match[1].casefold() != repository.casefold():
        raise ValueError("Issue URL must match configured REPOPILOT_GITHUB_REPOSITORY")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def fetch(session):
        response = session.get(
            f"https://api.github.com/repos/{repository}/issues/{match[2]}",
            headers=headers,
            timeout=20,
        )
        if response.is_error:
            raise ValueError(f"GitHub Issue read failed: HTTP {response.status_code}")
        value = response.json()
        if "pull_request" in value:
            raise ValueError("Provide an issue, not a pull request")
        return f"{value['title']}\n\n{value.get('body') or ''}"[:10000]

    if client is not None:
        return fetch(client)
    with httpx.Client() as session:
        return fetch(session)


class GitHubPublisher:
    def __init__(
        self,
        repository: str,
        token: str,
        *,
        subdirectory: str = "",
        base_branch: str | None = None,
        client: httpx.Client | None = None,
    ):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Configure a fixed owner/repository target")
        if not token:
            raise ValueError("GITHUB_TOKEN is required for PR publication")
        prefix = PurePosixPath(subdirectory)
        if subdirectory and (
            prefix.is_absolute()
            or "\\" in subdirectory
            or ":" in subdirectory
            or str(prefix) != subdirectory
            or any(p in {".", "..", ".git"} for p in prefix.parts)
        ):
            raise ValueError("GitHub subdirectory must be a normalized repository-relative path")
        self.repository = repository
        self.subdirectory = subdirectory
        if base_branch and (
            not re.fullmatch(r"[A-Za-z0-9._/-]+", base_branch)
            or ".." in base_branch
            or "//" in base_branch
            or base_branch.startswith("/")
            or base_branch.endswith(("/", ".", ".lock"))
        ):
            raise ValueError("Invalid GitHub base branch")
        self.base_branch = base_branch
        self.client = client or httpx.Client(timeout=20)
        self._owns_client = client is None
        self.prefix = f"https://api.github.com/repos/{repository}"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def request(self, method: str, endpoint: str, *, missing_ok=False, **kwargs):
        response = self.client.request(
            method, self.prefix + endpoint, headers=self.headers, **kwargs
        )
        if missing_ok and response.status_code == 404:
            return None
        if response.is_error:
            # Avoid persisting response bodies or credential-bearing request details.
            raise ValueError(f"GitHub API {method} {endpoint}: HTTP {response.status_code}")
        return response.json()

    def target(self) -> PublicationTarget:
        return PublicationTarget(repository=self.repository,
                                 configured_base_branch=self.base_branch,
                                 subdirectory=self.subdirectory)

    def _approved_content(self, state: dict) -> None:
        if state["approval_status"] != "approved" or state["execution_status"] != "approved":
            raise ValueError("Human repair approval required")
        if not re.fullmatch(r"[a-f0-9-]{36}", state["task_id"]):
            raise ValueError("Invalid task identity")
        validate_isolated(state)
        test = state["test_results"][-1]
        if test["status"] != "passed" or test["evidence"] != "docker":
            raise ValueError("Publication requires passed Docker evidence")
        if test.get("diff_digest") != state["diff_digest"]:
            raise ValueError("Test evidence differs from approved diff")
        if state.get("retry_workspace_policy") == "isolated" and (
            state.get("approved_candidate_id") != state["candidate_id"]
            or test.get("candidate_id") != state["candidate_id"]
        ):
            raise ValueError("Publication does not match approved candidate")
        if digest(diff_repositories(Path(state["workspace_path"]).parent / "baseline",
                                    Path(state["workspace_path"]))) != state["diff_digest"]:
            raise ValueError("Approved diff changed")

    def preview(self, state: dict, *, title: str | None = None,
                body: str | None = None) -> PublicationPlan:
        """GET-only preflight; no tree, commit, branch or PR is written here."""
        self._approved_content(state)
        workspace = Repository(state["workspace_path"])
        baseline = Repository(workspace.root.parent / "baseline")
        base = self.base_branch or self.request("GET", "")["default_branch"]
        head = self.request("GET", "/git/ref/heads/" + quote(base, safe=""))["object"]["sha"]
        tree = self.request("GET", f"/git/commits/{head}")["tree"]["sha"]
        entries = []
        for path in sorted(set(workspace.list_files()) | set(baseline.list_files())):
            before = baseline.path(path).read_bytes() if (baseline.root / path).exists() else None
            after = workspace.path(path).read_bytes() if (workspace.root / path).exists() else None
            if before == after:
                continue
            if after is None:
                raise ValueError("File deletion is not supported")
            remote_path = f"{self.subdirectory}/{path}" if self.subdirectory else path
            remote = self.request("GET", "/contents/" + quote(remote_path, safe="/"),
                                  params={"ref": head}, missing_ok=True)
            if remote is not None and (remote.get("type") != "file" or
                                       remote.get("encoding") != "base64"):
                raise ValueError("Unsupported remote file representation")
            remote_content = base64.b64decode(remote["content"]) if remote else None
            if remote_content != before:
                raise ValueError(f"Remote baseline differs for {path}; no writes performed")
            entries.append(PublicationEntry(path=remote_path, content=after.decode("utf-8"),
                before_sha256=hashlib.sha256(before).hexdigest() if before is not None else None))
        summary = next((line.strip() for line in state["issue_description"].splitlines()
                        if line.strip()), "Repair")
        return PublicationPlan(
            task_id=state["task_id"], candidate_id=state.get("candidate_id"),
            diff_digest=state["diff_digest"], baseline_digest=manifest_digest(file_manifest(baseline.root)),
            workspace_digest=manifest_digest(file_manifest(workspace.root)), target=self.target(),
            base_branch=base, base_sha=head, base_tree=tree, branch="repopilot/" + state["task_id"],
            title=title if title is not None else "fix: " + summary[:100],
            body=body if body is not None else (
                f"{state['issue_description']}\n\nHuman-approved diff SHA-256: `{state['diff_digest']}`\n\n"
                f"Docker tests passed; task `{state['task_id']}`. "
                "Review the patch and test evidence before merging."), entries=entries,
        )

    def validate_plan(self, state: dict, plan: PublicationPlan, approval_digest: str) -> None:
        if plan.digest() != approval_digest or plan.target != self.target():
            raise ValueError("Publication request or target differs from human approval")
        current = self.preview(state, title=plan.title, body=plan.body)
        if current.digest() != approval_digest:
            raise ValueError("Publication baseline, target or content changed; preview and approve again")

    def publish(self, state: dict, *, plan: PublicationPlan | None = None,
                approval_digest: str | None = None) -> str:
        # Trusted embedded v1 adapters keep their old interface. TaskService's real
        # publisher always supplies the separately approved canonical request.
        if plan is None:
            if state.get("publication_contract_version") == 1:
                raise ValueError("Separate human publication request approval required")
            return self._publish_legacy(state)
        self.validate_plan(state, plan, approval_digest or "")
        entries = [entry.model_dump(exclude={"before_sha256"}) for entry in plan.entries]
        tree = self.request("POST", "/git/trees", json={"base_tree": plan.base_tree, "tree": entries})
        commit = self.request("POST", "/git/commits", json={
            "message": plan.title, "tree": tree["sha"], "parents": [plan.base_sha]})
        if self.request("GET", "/git/ref/heads/" + quote(plan.base_branch, safe=""))["object"]["sha"] != plan.base_sha:
            raise ValueError("Base branch moved; inspect orphan commit before any retry")
        self.request("POST", "/git/refs", json={"ref": "refs/heads/" + plan.branch,
                                               "sha": commit["sha"]})
        return self.request("POST", "/pulls", json={
            "title": plan.title, "body": plan.body, "head": plan.branch,
            "base": plan.base_branch, "draft": plan.draft,
        })["html_url"]

    def _publish_legacy(self, state: dict) -> str:
        if state["approval_status"] != "approved" or state["execution_status"] != "approved":
            raise ValueError("Human approval required")
        if not re.fullmatch(r"[a-f0-9-]{36}", state["task_id"]):
            raise ValueError("Invalid task identity")
        if state.get("retry_workspace_policy") == "isolated":
            validate_isolated(state)
            if state.get("approved_candidate_id") != state["candidate_id"] or (
                state["test_results"][-1].get("candidate_id") != state["candidate_id"]
            ) or (
                state["test_results"][-1]["status"] != "passed"
                or state["test_results"][-1]["evidence"] != "docker"
            ):
                raise ValueError("Publication does not match approved candidate")
            if digest(diff_repositories(Path(state["workspace_path"]).parent / "baseline",
                                        Path(state["workspace_path"]))) != state["diff_digest"]:
                raise ValueError("Approved diff changed")
        workspace = Repository(state["workspace_path"])
        baseline = Repository(Path(state["workspace_path"]).parent / "baseline")
        metadata = self.request("GET", "")
        base = self.base_branch or metadata["default_branch"]
        ref_endpoint = "/git/ref/heads/" + quote(base, safe="")
        head = self.request("GET", ref_endpoint)["object"]["sha"]
        base_tree = self.request("GET", f"/git/commits/{head}")["tree"]["sha"]
        entries = []
        for path in sorted(set(workspace.list_files()) | set(baseline.list_files())):
            before = baseline.path(path).read_bytes() if (baseline.root / path).exists() else None
            after = workspace.path(path).read_bytes() if (workspace.root / path).exists() else None
            if before == after:
                continue
            if after is None:
                raise ValueError("File deletion is not supported")
            remote_path = f"{self.subdirectory}/{path}" if self.subdirectory else path
            remote = self.request(
                "GET",
                "/contents/" + quote(remote_path, safe="/"),
                params={"ref": head},
                missing_ok=True,
            )
            if remote is not None and (
                remote.get("type") != "file" or remote.get("encoding") != "base64"
            ):
                raise ValueError("Unsupported remote file representation")
            content = base64.b64decode(remote["content"]) if remote else None
            if content != before:
                raise ValueError(f"Remote baseline differs for {path}; no branch or PR created")
            entries.append(
                {
                    "path": remote_path,
                    "mode": "100644",
                    "type": "blob",
                    "content": after.decode("utf-8"),
                }
            )
        if not entries:
            raise ValueError("No approved changes to publish")
        # All remote preconditions checked before the first remote write.
        tree = self.request("POST", "/git/trees", json={"base_tree": base_tree, "tree": entries})
        commit = self.request(
            "POST",
            "/git/commits",
            json={
                "message": f"fix: {state['issue_description'][:100]}",
                "tree": tree["sha"],
                "parents": [head],
            },
        )
        if self.request("GET", ref_endpoint)["object"]["sha"] != head:
            raise ValueError("Base branch moved; inspect orphan commit and retry with a new task")
        branch = "repopilot/" + state["task_id"]
        self.request(
            "POST", "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]}
        )
        pr = self.request(
            "POST",
            "/pulls",
            json={
                "title": f"fix: {state['issue_description'][:100]}",
                "head": branch,
                "base": base,
                "draft": True,
                "body": f"{state['issue_description']}\n\n"
                f"Human-approved diff SHA-256: `{state['diff_digest']}`\n\n"
                f"Docker tests passed; task `{state['task_id']}`. "
                "Review the patch and test evidence before merging.",
            },
        )
        return pr["html_url"]
