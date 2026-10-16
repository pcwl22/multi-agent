"""Optional GitHub writes: only called after explicit, digest-bound human approval."""

import base64
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from app.tools.repository import Repository


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

    def publish(self, state: dict) -> str:
        if state["approval_status"] != "approved" or state["execution_status"] != "approved":
            raise ValueError("Human approval required")
        if not re.fullmatch(r"[a-f0-9-]{36}", state["task_id"]):
            raise ValueError("Invalid task identity")
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
