"""Explicit fault injection for live feedback demonstrations, separate from benchmarks."""

import argparse
import hashlib
import json
from pathlib import Path

from app.agents.model import Model, create_model
from app.config.settings import Settings
from app.evaluation.runner import holdout_workspace
from app.models.schemas import Edit, Patch, TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService


class FaultInjectionModel:
    """Call the underlying model every time; label deliberately replaced candidates."""

    def __init__(self, model: Model, policy: str):
        if policy not in {"first", "always"}:
            raise ValueError("Unknown fault-injection policy")
        self.model = model
        self.policy = policy
        self.workspace: Path | None = None
        self.patch_calls = 0
        self.audit: list[dict] = []

    def generate(self, schema, payload):
        value, stats = self.model.generate(schema, payload)
        evidence = {
            "schema": schema.__name__,
            "failed_test_feedback": [
                {
                    "attempt": test["attempt"],
                    "status": test["status"],
                    "failed": test["failed"],
                    "stdout_sha256": hashlib.sha256(test["stdout"].encode()).hexdigest(),
                }
                for test in payload.get("tests", [])
                if test["status"] == "failed"
            ],
            "payload_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
            "injected": False,
            "model_reported": stats.get("model_reported"),
            "provider_response_id": stats.get("provider_response_id"),
        }
        if schema is Patch:
            self.patch_calls += 1
            if self.policy == "always" or self.patch_calls == 1:
                assert self.workspace is not None
                original = (self.workspace / "cache.py").read_text(encoding="utf-8")
                evidence["model_candidate_sha256"] = hashlib.sha256(
                    value.model_dump_json().encode()
                ).hexdigest()
                # Replace the entire candidate, including generated tests. This creates
                # an actual failing container run, without altering existing tests.
                value = Patch(
                    rationale="EXPERIMENT: deliberately injected incorrect expiry threshold",
                    edits=[
                        Edit(
                            path="cache.py",
                            old=original,
                            new=(
                                "def is_expired(inserted_at, ttl, now):\n"
                                f"    return now >= inserted_at + ttl + {100 + self.patch_calls}\n"
                            ),
                        )
                    ],
                )
                evidence["injected"] = True
                stats = {
                    **stats,
                    "fault_injection": {
                        "policy": self.policy,
                        "patch_call": self.patch_calls,
                        "model_candidate_sha256": evidence["model_candidate_sha256"],
                    },
                }
        self.audit.append(evidence)
        return value, stats


def run_feedback_experiments(settings: Settings, output: Path) -> dict:
    if settings.model_mode != "live":
        raise ValueError("Feedback experiment requires an actual live model")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a fresh experiment output directory")
    root = Path(__file__).parent / "expanded"
    repository = (root / "repos/ttl-equality").resolve()
    acceptance_file = root / "acceptance/test_ttl_equality.py"
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for policy in ("first", "always"):
        config = settings.model_copy(
            update={
                "repository_root": repository,
                "data_dir": output / policy / "state",
                "max_retries": 1,
                # Hold workspace policy constant: injection reads the current edited file.
                "retry_workspace_policy": "preserve",
            }
        )
        adapter = FaultInjectionModel(create_model(config), policy)
        runner = DockerRunner(config)
        baseline_path = output / policy / "baseline"
        holdout_workspace(repository, baseline_path, acceptance_file)
        baseline = runner.run(baseline_path)
        if baseline.status != "failed" or baseline.failed == 0 or baseline.errors:
            raise ValueError("Baseline failed to establish the expiry bug")
        service = TaskService(config, model=adapter, runner=runner)
        try:
            task = service.create(
                TaskRequest(
                    repository_path=str(repository),
                    issue_description=(
                        "Fix is_expired in cache.py: expire at now >= inserted_at + ttl, "
                        "including zero TTL. Preserve earlier/later behavior. "
                        "Add regression tests in a NEW test file."
                    ),
                )
            )
            adapter.workspace = Path(task["workspace_path"])
            state = service.run(task["task_id"])
            holdout = output / policy / "holdout"
            holdout_workspace(adapter.workspace, holdout, acceptance_file)
            accepted = runner.run(holdout)
            target = output / policy
            (target / "state.json").write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (target / "repair.patch").write_text(state["diff"], encoding="utf-8")
            record = {
                "policy": policy,
                "task_id": task["task_id"],
                "execution_status": state["execution_status"],
                "error": state["error"],
                "attempts": state["attempts"],
                "retry_count": state["retry_count"],
                "model_calls": state["model_calls"],
                "tokens": state["input_tokens"] + state["output_tokens"]
                if state["token_usage_complete"]
                else None,
                "baseline": baseline.model_dump(),
                "tests": state["test_results"],
                "acceptance": accepted.model_dump(),
                "audit": adapter.audit,
                "expected_outcome_verified": (
                    state["execution_status"] == "awaiting_approval"
                    and accepted.status == "passed"
                    and any(a["failed_test_feedback"] and not a["injected"] for a in adapter.audit)
                )
                if policy == "first"
                else (
                    state["execution_status"] == "failed"
                    and state["error"] == "Test retry budget exhausted"
                    and state["attempts"] == 2
                    and len(state["test_results"]) == 2
                    and all(test["status"] == "failed" for test in state["test_results"])
                ),
            }
            (target / "evidence.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            records.append(record)
        finally:
            service.close()
    report = {
        "experiment_type": "controlled_fault_injection_with_live_llm",
        "retry_workspace_policy": "preserve",
        "configured_retry_workspace_policy": settings.retry_workspace_policy,
        "note": (
            "Workspace policy is fixed to preserve for this feedback-only experiment. "
            "These are deliberately corrupted candidates, not naturally failed model repairs. "
            "Every request uses the live provider; recovery candidates are unmodified. "
            "The always policy replaces every candidate to verify finite termination. "
            "Do not include these experiments in benchmark success rates."
        ),
        "records": records,
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_feedback_experiments(Settings(), args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
