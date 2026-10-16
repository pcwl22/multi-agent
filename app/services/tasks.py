import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from filelock import FileLock
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.agents.model import Model, create_model
from app.config.settings import Settings
from app.graph.workflow import build_graph
from app.models.schemas import TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.attempts import (
    file_manifest,
    prepare_candidate,
    save_candidate,
    validate_isolated,
)
from app.services.github import GitHubPublisher, read_issue
from app.tools.repository import Repository, diff_repositories, digest, snapshot


class TaskService:
    def __init__(self, settings: Settings, *, model: Model | None = None, runner=None):
        self.settings = settings
        self.data = settings.data_dir.resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.data / "tasks.sqlite3", check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks "
            "(task_id TEXT PRIMARY KEY, thread_id TEXT UNIQUE, initial TEXT)"
        )
        self.conn.commit()
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS publications (task_id TEXT PRIMARY KEY, result TEXT)"
        )
        self.conn.commit()
        self.lock = threading.RLock()
        self.checkpoint_conn = sqlite3.connect(
            self.data / "checkpoints.sqlite3", check_same_thread=False
        )
        self.saver = SqliteSaver(self.checkpoint_conn)
        self.graph = build_graph(
            settings, model or create_model(settings), runner or DockerRunner(settings), self.saver
        )

    def close(self):
        self.conn.close()
        self.checkpoint_conn.close()

    def _config(self, thread_id):
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}

    def _initial(self, task_id):
        try:
            uuid.UUID(task_id)
        except ValueError as exc:
            raise KeyError("Unknown task") from exc
        with self.lock:
            row = self.conn.execute(
                "SELECT initial FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Unknown task")
        return json.loads(row[0])

    def create(self, request: TaskRequest) -> dict:
        allowed = self.settings.repository_root.resolve(strict=True)
        source = Path(request.repository_path).resolve(strict=True)
        if not source.is_relative_to(allowed):
            raise ValueError("Repository is outside configured REPOPILOT_REPOSITORY_ROOT")
        if self.data.is_relative_to(source) or source.is_relative_to(self.data):
            raise ValueError("Repository and task storage must not overlap")
        repo = Repository(source)
        description = request.issue_description
        if request.github_issue_url:
            description = read_issue(
                request.github_issue_url,
                self.settings.github_repository,
                self.settings.github_token.get_secret_value() if self.settings.github_token else "",
            )
        task_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
        task_dir = self.data / "tasks" / task_id
        snapshot(repo, task_dir / "baseline")
        policy = request.retry_workspace_policy or self.settings.retry_workspace_policy
        manifest = file_manifest(task_dir / "baseline") if policy == "isolated" else {}
        if policy == "isolated":
            candidate = prepare_candidate(task_dir, 1, manifest)
        else:
            snapshot(Repository(task_dir / "baseline"), task_dir / "workspace")
            candidate = {"workspace_path": str(task_dir / "workspace"), "candidate_id": None,
                         "candidate_number": 0}
        state = dict(
            task_id=task_id,
            thread_id=thread_id,
            issue_description=description,
            repository_path=str(source),
            **candidate,
            task_path=str(task_dir), retry_workspace_policy=policy, baseline_manifest=manifest,
            attempt_history=[], previous_candidate_diff="", approved_candidate_id=None,
            mode=request.mode,
            execution_status="queued",
            plan=None,
            located_files=[],
            context="",
            patches=[],
            patch_feedback=[],
            test_results=[],
            review_results=[],
            retry_count=0,
            attempts=0,
            approval_status="pending",
            execution_history=[],
            retrieval_history=[],
            model_calls=0,
            input_tokens=0,
            output_tokens=0,
            token_usage_complete=True,
            error=None,
            failure=None,
            provider_retry_count=0,
            next_node="",
            diff="",
            diff_digest="",
        )
        with self.lock:
            self.conn.execute(
                "INSERT INTO tasks VALUES (?, ?, ?)", (task_id, thread_id, json.dumps(state))
            )
            self.conn.commit()
        return state

    def get(self, task_id: str) -> dict:
        initial = self._initial(task_id)
        values = self.graph.get_state(self._config(initial["thread_id"])).values
        return dict(values) if values else initial

    def _task_lock(self, task_id):
        self._initial(task_id)
        return FileLock(str(self.data / "tasks" / task_id / "execution.lock"), timeout=0)

    def run(self, task_id: str) -> dict:
        with self._task_lock(task_id):
            state = self.get(task_id)
            validate_isolated(state, self.data / "tasks" / task_id)
            config = self._config(state["thread_id"])
            if state["execution_status"] in {"approved", "rejected", "failed", "awaiting_approval"}:
                raise ValueError("Task cannot be resumed from this status")
            current_diff = diff_repositories(
                Path(state["workspace_path"]).parent / "baseline", Path(state["workspace_path"])
            )
            if digest(current_diff) != (state["diff_digest"] or digest("")):
                raise ValueError("Workspace changed outside the recorded repair")
            checkpoint = self.graph.get_state(config)
            if state["execution_status"] == "retryable":
                self.check_resume(task_id)
                failure = state["failure"]
                self.graph.update_state(
                    config,
                    {
                        "execution_status": "running", "error": None, "failure": None,
                        "provider_retry_count": state.get("provider_retry_count", 0) + 1,
                        "next_node": failure["node"],
                    },
                    as_node="supervisor",
                )
            if state["execution_status"] == "blocked":
                self.graph.update_state(
                    config,
                    {"execution_status": "running", "error": None, "next_node": "test"},
                    as_node="supervisor",
                )
            self.graph.invoke(state if not checkpoint.values else None, config, durability="sync")
            result = self.get(task_id)
            if result.get("retry_workspace_policy") == "isolated":
                save_candidate(result)
            return result

    def check_resume(self, task_id: str) -> None:
        state = self.get(task_id)
        validate_isolated(state, self.data / "tasks" / task_id)
        if state["execution_status"] not in {"queued", "running", "blocked", "retryable"}:
            raise ValueError("Task is not resumable; use approve/reject at human interrupt")
        if state["execution_status"] == "retryable":
            failure = state.get("failure") or {}
            if not failure.get("retryable") or (
                state.get("provider_retry_count", 0) >= self.settings.max_retries
            ):
                raise ValueError("Provider retry budget exhausted; create a new task")
            remaining = failure.get("retry_at", 0) - time.time()
            if remaining > 0:
                raise ValueError(f"Provider cooldown active; retry after {int(remaining) + 1}s")
        actual = self.diff(task_id)
        expected = state["diff_digest"] or digest("")
        if actual["diff_digest"] != expected:
            raise ValueError("Workspace changed outside the recorded repair; create a new task")

    def decide(self, task_id: str, approved: bool, expected_digest: str,
               *, candidate_id: str | None = None) -> dict:
        with self._task_lock(task_id):
            state = self.get(task_id)
            if state["execution_status"] != "awaiting_approval":
                raise ValueError("Task is not awaiting approval")
            validate_isolated(state, self.data / "tasks" / task_id)
            if state.get("retry_workspace_policy") == "isolated":
                if candidate_id != state["candidate_id"]:
                    raise ValueError("Approval does not match current candidate")
                if state["test_results"][-1].get("candidate_id") != candidate_id:
                    raise ValueError("Test evidence does not match current candidate")
            actual = diff_repositories(
                Path(state["workspace_path"]).parent / "baseline", Path(state["workspace_path"])
            )
            if expected_digest != state["diff_digest"] or digest(actual) != expected_digest:
                raise ValueError("Diff has changed; approval rejected")
            if approved and state["test_results"][-1]["evidence"] != "docker":
                raise ValueError("Approval requires real Docker test evidence")
            self.graph.invoke(
                Command(resume={"approved": approved, "diff_digest": expected_digest,
                                "candidate_id": candidate_id}),
                self._config(state["thread_id"]),
                durability="sync",
            )
            result = self.get(task_id)
            if result.get("retry_workspace_policy") == "isolated":
                save_candidate(result)
            return result

    def diff(self, task_id: str) -> dict:
        state = self.get(task_id)
        actual = diff_repositories(
            Path(state["workspace_path"]).parent / "baseline", Path(state["workspace_path"])
        )
        return {
            "diff": actual,
            "diff_digest": digest(actual),
            "matches_recorded": digest(actual) == state["diff_digest"],
            "candidate_id": state.get("candidate_id"),
        }

    def publish(self, task_id: str, expected_digest: str, *, publisher=None,
                candidate_id: str | None = None) -> dict:
        with self._task_lock(task_id):
            state = self.get(task_id)
            if state["execution_status"] != "approved" or state["approval_status"] != "approved":
                raise ValueError("Explicit human approval is required before publication")
            validate_isolated(state, self.data / "tasks" / task_id)
            if state.get("retry_workspace_policy") == "isolated" and (
                candidate_id != state["candidate_id"] or state.get("approved_candidate_id") != candidate_id
            ):
                raise ValueError("Publication does not match approved candidate")
            actual = self.diff(task_id)
            if (
                expected_digest != state["diff_digest"]
                or not actual["matches_recorded"]
                or state["test_results"][-1]["evidence"] != "docker"
            ):
                raise ValueError("Approved content or test evidence no longer matches")
            with self.lock:
                prior = self.conn.execute(
                    "SELECT result FROM publications WHERE task_id=?", (task_id,)
                ).fetchone()
            if prior:
                result = json.loads(prior[0])
                if result["status"] == "created":
                    return result
                raise ValueError("Prior publication has uncertain outcome; inspect GitHub manually")
            owns_publisher = publisher is None
            if publisher is None:
                if not self.settings.github_repository:
                    raise ValueError("Configure REPOPILOT_GITHUB_REPOSITORY before publication")
                publisher = GitHubPublisher(
                    self.settings.github_repository,
                    self.settings.github_token.get_secret_value()
                    if self.settings.github_token
                    else "",
                    subdirectory=self.settings.github_repository_subdirectory,
                    base_branch=self.settings.github_base_branch,
                )
            with self.lock:
                self.conn.execute(
                    "INSERT INTO publications VALUES (?, ?)",
                    (task_id, json.dumps({"status": "started"})),
                )
                self.conn.commit()
            try:
                url = publisher.publish(state)
                result = {"status": "created", "url": url}
            except Exception as exc:
                with self.lock:
                    self.conn.execute(
                        "UPDATE publications SET result=? WHERE task_id=?",
                        (json.dumps({"status": "uncertain", "error": type(exc).__name__}), task_id),
                    )
                    self.conn.commit()
                raise ValueError(
                    "PR publication interrupted; inspect GitHub before retrying"
                ) from exc
            finally:
                if owns_publisher:
                    publisher.close()
            with self.lock:
                self.conn.execute(
                    "UPDATE publications SET result=? WHERE task_id=?",
                    (json.dumps(result), task_id),
                )
                self.conn.commit()
            return result
