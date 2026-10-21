import argparse
import hashlib
import json
import platform
import shutil
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

from app.agents.model import LiveModel
from app.config.settings import Settings
from app.models.reliability import CircuitSnapshot
from app.models.schemas import TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.provider_circuit import ProviderCircuit
from app.services.tasks import TaskService
from app.tools.repository import Repository, is_test_file

MODES = ["single", "multi_no_review", "multi_full"]


def aggregate(records: list[dict]) -> dict:
    def mean(field):
        values = [r[field] for r in records if r[field] is not None]
        return statistics.mean(values) if values else None

    acceptance = [
        r
        for r in records
        if r.get("acceptance") and r["acceptance"]["status"] in {"passed", "failed"}
    ]
    evaluated = [
        r
        for r in records
        if r["execution_status"] not in {"blocked", "invalid_case", "not_run"}
        and not (r["execution_status"] == "batch_paused" and r.get("model_calls", 0) == 0)
        and (
            r.get("baseline_verified")
            or r in acceptance
            or (
                r.get("test_result")
                and r["test_result"]["status"] in {"passed", "failed", "timeout"}
            )
        )
    ]
    total_tests = sum(
        r["test_result"][k]
        for r in records
        if r.get("test_result")
        for k in ["passed", "failed", "errors"]
    )
    passed = sum(r["test_result"]["passed"] for r in records if r.get("test_result"))
    return {
        "runs": len(records),
        "not_run": sum(r["execution_status"] == "not_run" or (r["execution_status"] == "batch_paused" and r.get("model_calls", 0) == 0) for r in records),
        "planned_ready_and_accepted_rate": sum(r.get("baseline_verified", False) and r["execution_status"] == "awaiting_approval" and (r.get("test_result") or {}).get("status") == (r.get("acceptance") or {}).get("status") == "passed" for r in records) / len(records) if records else None,
        "acceptance_evaluated": len(acceptance),
        "repair_evaluated": len(evaluated),
        "bug_fix_success_rate": (
            sum(r["acceptance"]["status"] == "passed" for r in acceptance) / len(evaluated)
        )
        if evaluated
        else None,
        "test_pass_rate": passed / total_tests if total_tests else None,
        "task_completion_rate": (
            sum(r["execution_status"] in {"awaiting_approval", "approved"} for r in records)
            / len(records)
        )
        if records
        else None,
        "average_execution_seconds": mean("duration_seconds"),
        "average_model_calls": mean("model_calls"),
        "average_tokens": mean("tokens"),
        "average_retries": mean("retry_count"),
        "blocked_runs": sum(r["execution_status"] == "blocked" for r in records),
        "invalid_case_runs": sum(r["execution_status"] == "invalid_case" for r in records),
        "token_observed_runs": sum(r["tokens"] is not None for r in records),
        "provider_error_runs": sum(
            "Model request failed:" in (r.get("error") or "") for r in records
        ),
        "recovered_after_retry_runs": sum(
            r["retry_count"] > 0
            and bool(r.get("acceptance") and r["acceptance"]["status"] == "passed")
            for r in records
        ),
        "retry_exhausted_runs": sum(
            "retry budget exhausted" in (r.get("error") or "").lower() for r in records
        ),
    }


def holdout_workspace(workspace: Path, destination: Path, acceptance: Path) -> None:
    destination.mkdir(parents=True)
    repo = Repository(workspace)
    for relative in repo.list_files():
        # Holdout runs only source files and evaluator-owned tests, not model-generated tests.
        if is_test_file(relative):
            continue
        dst = destination / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo.path(relative), dst)
    (destination / "tests").mkdir()
    shutil.copyfile(acceptance, destination / "tests" / "test_acceptance.py")


def run_evaluation(
    settings: Settings,
    repository: Path,
    output: Path,
    repeats: int = 1,
    *,
    dataset_file: Path | None = None,
    workers: int = 1,
    evaluation_runner=None,
    variants: dict[str, Settings] | None = None,
) -> dict:
    dataset_file = (dataset_file or Path(__file__).parent / "dataset.json").resolve(strict=True)
    dataset_root = dataset_file.parent
    dataset = json.loads(dataset_file.read_text(encoding="utf-8"))
    if not 1 <= repeats <= 100:
        raise ValueError("repeats must be between 1 and 100")
    if not 1 <= workers <= 3:
        raise ValueError("workers must be between 1 and 3")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a fresh output directory to avoid mixing evaluation records")
    case_ids = [case["id"] for case in dataset]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Dataset case IDs must be unique")
    # Resolve every case before creating artifacts or sending source to a model.
    resolved_cases = []
    for case in dataset:
        if not case["id"] or any(
            c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in case["id"]
        ):
            raise ValueError("Dataset case IDs must be lowercase path-safe identifiers")
        source = (
            (dataset_root / case["repository"]).resolve(strict=True)
            if case.get("repository")
            else repository.resolve(strict=True)
        )
        acceptance = (dataset_root / "acceptance" / case["acceptance"]).resolve(strict=True)
        if not source.is_relative_to(settings.repository_root.resolve(strict=True)):
            raise ValueError("Dataset repository is outside configured root")
        if not acceptance.is_relative_to(dataset_root) or not acceptance.is_file():
            raise ValueError("Dataset acceptance must be a file inside the dataset directory")
        resolved_cases.append((case, source, acceptance))
    if variants is not None:
        if set(variants) != {"legacy", "quality"} or repeats not in {2, 4}:
            raise ValueError("Comparison requires legacy/quality variants and two or four balanced blocks")
        common = settings.model_dump(exclude={"data_dir", "repair_quality_checks"})
        roots = []
        for name, variant in variants.items():
            if variant.model_dump(exclude={"data_dir", "repair_quality_checks"}) != common:
                raise ValueError("Comparison variants differ outside quality policy and task storage")
            root = variant.data_dir.resolve()
            if root.exists() and any(root.iterdir()):
                raise ValueError("Comparison requires fresh variant task storage")
            if any(root.is_relative_to(r) or r.is_relative_to(root) for r in roots):
                raise ValueError("Comparison task roots overlap")
            if root.is_relative_to(settings.repository_root.resolve()) or settings.repository_root.resolve().is_relative_to(root):
                raise ValueError("Comparison task root overlaps the model repository")
            roots.append(root)
        if variants["legacy"].repair_quality_checks or not variants["quality"].repair_quality_checks:
            raise ValueError("Comparison policies must be off/on respectively")
    runner = evaluation_runner or DockerRunner(settings)
    records = []
    output.mkdir(parents=True, exist_ok=True)
    record_lock = threading.Lock()
    def save_circuit(snapshot):
        temporary = output / "provider-circuit.tmp"
        temporary.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output / "provider-circuit.json")
    circuit = ProviderCircuit(settings.evaluation_provider_failure_threshold, on_change=save_circuit) if (
        settings.model_mode == "live" and settings.evaluation_provider_failure_threshold > 0) else None
    save_circuit(circuit.snapshot() if circuit else CircuitSnapshot(enabled=False, threshold=0).model_dump())
    services = {name: TaskService(value, **({"model": LiveModel(value, dispatch_gate=circuit)} if circuit else {}))
                for name, value in (variants or {"default": settings}).items()}

    def record_result(record):
        with record_lock:
            records.append(record)
            with (output / "runs.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def evaluate_case(item):
        case, case_repository, acceptance_file = item
        baseline = None
        if not circuit or not circuit.snapshot()['opened']:
            baseline_path = output / "baselines" / case["id"]
            holdout_workspace(case_repository, baseline_path, acceptance_file)
            baseline = runner.run(baseline_path).model_dump()
        baseline_verified = bool(baseline and baseline["status"] == "failed" and baseline["failed"] > 0 and baseline["errors"] == 0)
        for repeat in range(repeats):
            variant_tags = {}
            if variants:
                order = (["legacy", "quality", "quality", "legacy"] if case_ids.index(case["id"]) % 2 == 0
                         else ["quality", "legacy", "legacy", "quality"])
                if repeats == 2:
                    order = ["legacy", "quality"] if case_ids.index(case["id"]) % 2 == 0 else ["quality", "legacy"]
                name = order[repeat]
                service = services[name]
                variant_tags = {"variant": name, "variant_repeat": order[:repeat].count(name)}
            else:
                service = services["default"]
            # Rotate order to reduce systematic warm-cache bias.
            for mode in MODES[repeat % 3 :] + MODES[: repeat % 3]:
                started = time.monotonic()
                paused = circuit is not None and circuit.snapshot()["opened"]
                if paused or not baseline_verified:
                    record = {
                        **variant_tags,
                        "case_id": case["id"],
                        "repeat": repeat,
                        "mode": mode,
                        "task_id": None,
                        "thread_id": None,
                        "baseline": baseline,
                        "baseline_verified": baseline_verified,
                        "execution_status": "not_run" if paused else ("blocked" if baseline["status"] in {"unavailable", "timeout"} else "invalid_case"),
                        "not_run_reason": "provider_circuit_open" if paused else None,
                        "circuit_failure": circuit.snapshot() if paused else None,
                        "model_attempted": False,
                        "error": "Batch circuit open; task not dispatched" if paused else "Baseline did not establish a failing bug; repair was not run",
                        "duration_seconds": 0,
                        "model_calls": 0,
                        "tokens": 0,
                        "retry_count": 0,
                        "test_result": None,
                        "acceptance": None,
                    }
                    record_result(record)
                    continue
                task = service.create(
                    TaskRequest(
                        repository_path=str(case_repository),
                        issue_description=case["issue"],
                        mode=mode,
                    )
                )
                state = service.run(task["task_id"])
                acceptance = None
                current_test = state["test_results"][-1] if state["test_results"] else None
                if state.get("retry_workspace_policy") == "isolated" and current_test and (
                    current_test.get("candidate_id") != state["candidate_id"]
                ):
                    current_test = None
                if current_test and current_test["status"] == "passed":
                    holdout = output / "holdouts" / task["task_id"]
                    holdout_workspace(Path(state["workspace_path"]), holdout, acceptance_file)
                    acceptance = runner.run(holdout).model_dump()
                record = {
                    **variant_tags,
                    "case_id": case["id"],
                    "repeat": repeat,
                    "mode": mode,
                    "task_id": task["task_id"],
                    "thread_id": task["thread_id"],
                    "baseline": baseline,
                    "baseline_verified": baseline_verified,
                    "execution_status": state["execution_status"],
                    "error": state["error"],
                    "provider_failure": state.get("failure"),
                    "budget_failure": state.get("budget_failure"),
                    "circuit_failure": state.get("circuit_failure"),
                    "model_attempted": state["model_calls"] > 0,
                    "not_run_reason": "provider_circuit_open" if state["execution_status"] == "batch_paused" else None,
                    "duration_seconds": time.monotonic() - started,
                    "model_calls": state["model_calls"],
                    "tokens": (state["input_tokens"] + state["output_tokens"])
                    if state.get("token_usage_complete", True)
                    else None,
                    "retry_count": state["retry_count"],
                    "attempts": state["attempts"],
                    "retry_workspace_policy": state.get("retry_workspace_policy", "preserve"),
                    "candidate_id": state.get("candidate_id"),
                    "candidate_number": state.get("candidate_number", 0),
                    "attempt_history": state.get("attempt_history", []),
                    "attempt_evidence": [
                        {
                            k: test[k]
                            for k in (
                                "attempt",
                                "status",
                                "passed",
                                "failed",
                                "errors",
                                "evidence",
                            )
                        }
                        for test in state["test_results"]
                    ],
                    "patch_rejections": state.get("patch_feedback", []),
                    "repair_feedback": state.get("repair_feedback", []),
                    "regression_results": state.get("regression_results", []),
                    "creation_attempts": state.get("creation_attempts", 0),
                    "creation_failures": state.get("creation_failures", []),
                    "review_decisions": [
                        {"attempt": review["attempt"], "approved": review["approved"]}
                        for review in state["review_results"]
                    ],
                    "test_result": current_test,
                    "acceptance": acceptance,
                    "diff_digest": state["diff_digest"],
                    "context_chars": len(state["context"]),
                    "retrieved_files": len(state["located_files"]),
                    "model_observations": [
                        {
                            key: event.get(key)
                            for key in [
                                "model_requested",
                                "model_reported",
                                "provider_response_id",
                                "transport_attempts",
                                "sdk_versions",
                                "calls",
                                    "rate_limit_wait_seconds",
                            ]
                        }
                        for event in state["execution_history"]
                        if event["node"] == "model"
                    ],
                }
                artifacts = output / "tasks" / task["task_id"]
                artifacts.mkdir(parents=True)
                (artifacts / "state.json").write_text(
                    json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                (artifacts / "repair.patch").write_text(state["diff"], encoding="utf-8")
                if state.get("retry_workspace_policy") == "isolated":
                    for number in range(1, state["candidate_number"] + 1):
                        source = Path(state["task_path"]) / "attempts" / f"{number:04}"
                        destination = artifacts / "attempts" / f"{number:04}"
                        destination.mkdir(parents=True)
                        for filename in ["candidate.json", "evidence.json"]:
                            shutil.copyfile(source / filename, destination / filename)
                        evidence = json.loads((source / "evidence.json").read_text(encoding="utf8"))
                        (destination / "repair.patch").write_text(evidence["diff"], encoding="utf8")
                record_result(record)

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(evaluate_case, resolved_cases))
    finally:
        for service in services.values():
            service.close()
    report = {
        "model_mode": settings.model_mode,
        "model_name": settings.model_name if settings.model_mode == "live" else None,
        "model_endpoint_host": urlsplit(settings.model_base_url).hostname
        if settings.model_base_url
        else None,
        "dataset_cases": len(dataset),
        "provider_circuit": circuit.snapshot() if circuit else CircuitSnapshot(enabled=False, threshold=0).model_dump(),
        "repeats": repeats,
        "dataset_sha256": hashlib.sha256(dataset_file.read_bytes()).hexdigest(),
        "corpus_sha256": hashlib.sha256(
            json.dumps(
                [
                    {
                        "id": case["id"],
                        "source": {
                            p: hashlib.sha256(Repository(source).path(p).read_bytes()).hexdigest()
                            for p in Repository(source).list_files()
                        },
                        "acceptance": hashlib.sha256(acceptance.read_bytes()).hexdigest(),
                    }
                    for case, source, acceptance in resolved_cases
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "python_version": platform.python_version(),
        "dependencies": {
            name: version(name)
            for name in ["langgraph", "langchain-openai", "mcp", "pydantic", "fastapi"]
        },
        "configuration": {
            "workers": workers,
            "evaluation_provider_failure_threshold": settings.evaluation_provider_failure_threshold,
            "context_chars": settings.context_chars,
            "max_retries": settings.max_retries,
            "retry_workspace_policy": settings.retry_workspace_policy,
            "temperature": 0,
            "sandbox_image": settings.sandbox_image,
            "model_timeout": settings.model_timeout,
            "model_min_interval": settings.model_min_interval,
            "test_timeout": settings.test_timeout,
        },
        "note": (
            "null means no execution evidence. Mock results do not measure LLM capability. "
            "Synthetic cases and repeated calls do not establish real-project generalization. "
            "Concurrent durations include shared resources, provider load and request pacing. "
            "not_run cells retain the planned denominator; they are not model or repair failures. "
            "The circuit latches for this batch; resuming or replaying this output is unsupported."
        ),
        "modes": {mode: aggregate([r for r in records if r["mode"] == mode]) for mode in MODES},
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# RepoPilot 真实执行评测",
        "",
        f"模型模式：{settings.model_mode}；样本数：{len(dataset)}。",
        "",
        "每个案例先确认独立验收在修复前失败。null 表示缺少执行证据。Mock 仅衡量流程。",
        "修复成功率的分母包含已验证基线下的失败修复，不只计算成功进入独立验收的任务。",
        "",
        "| 模式 | 次数 | 修复成功率 | 测试通过率 | 完成率 | 平均秒数 | 平均调用 | 平均 Token | 平均重试 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, values in report["modes"].items():
        keys = [
            "runs",
            "bug_fix_success_rate",
            "test_pass_rate",
            "task_completion_rate",
            "average_execution_seconds",
            "average_model_calls",
            "average_tokens",
            "average_retries",
        ]
        formatted = [
            str(round(values[k], 4)) if isinstance(values[k], float) else str(values[k])
            for k in keys
        ]
        lines.append("| " + " | ".join([mode, *formatted]) + " |")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Compare repair graph modes on identical cases")
    parser.add_argument("--repo", type=Path, default=Path("demo_repository"))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--provider-failure-threshold", type=int, choices=range(21), help="Consecutive matching failures before batch pause; 0 disables")
    parser.add_argument("--dataset", type=Path, help="Optional dataset with per-case repositories")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("repeats must be between 1 and 100")
    output = args.output or Path(".repopilot/evaluations") / uuid.uuid4().hex
    if output.exists() and any(output.iterdir()):
        parser.error("Use a fresh output directory to avoid mixing evaluation records")
    settings = Settings()
    if args.provider_failure_threshold is not None:
        settings.evaluation_provider_failure_threshold = args.provider_failure_threshold
    report = run_evaluation(
        settings, args.repo, output, args.repeats, dataset_file=args.dataset, workers=args.workers
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Reports: {output.resolve()}")


if __name__ == "__main__":
    main()
