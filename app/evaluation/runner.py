import argparse
import json
import shutil
import statistics
import time
import uuid
from pathlib import Path

from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService
from app.tools.repository import Repository

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
    total_tests = sum(
        r["test_result"][k]
        for r in records
        if r.get("test_result")
        for k in ["passed", "failed", "errors"]
    )
    passed = sum(r["test_result"]["passed"] for r in records if r.get("test_result"))
    return {
        "runs": len(records),
        "acceptance_evaluated": len(acceptance),
        "bug_fix_success_rate": (
            sum(r["acceptance"]["status"] == "passed" for r in acceptance) / len(acceptance)
        )
        if acceptance
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
    }


def holdout_workspace(workspace: Path, destination: Path, acceptance: Path) -> None:
    destination.mkdir(parents=True)
    repo = Repository(workspace)
    for relative in repo.list_files():
        parts = Path(relative).parts
        # Holdout runs only source files and evaluator-owned tests, not model-generated tests.
        if "tests" in parts or Path(relative).name.startswith(("test_", "conftest")):
            continue
        dst = destination / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo.path(relative), dst)
    (destination / "tests").mkdir()
    shutil.copyfile(acceptance, destination / "tests" / "test_acceptance.py")


def run_evaluation(settings: Settings, repository: Path, output: Path, repeats: int = 1) -> dict:
    dataset_root = Path(__file__).parent
    dataset = json.loads((dataset_root / "dataset.json").read_text(encoding="utf-8"))
    service = TaskService(settings)
    runner = DockerRunner(settings)
    records = []
    output.mkdir(parents=True, exist_ok=True)
    try:
        for case in dataset:
            acceptance_file = dataset_root / "acceptance" / case["acceptance"]
            for repeat in range(repeats):
                # Rotate order to reduce systematic warm-cache bias.
                for mode in MODES[repeat % 3 :] + MODES[: repeat % 3]:
                    started = time.monotonic()
                    task = service.create(
                        TaskRequest(
                            repository_path=str(repository),
                            issue_description=case["issue"],
                            mode=mode,
                        )
                    )
                    state = service.run(task["task_id"])
                    acceptance = None
                    if state["test_results"] and state["test_results"][-1]["status"] == "passed":
                        holdout = output / "holdouts" / task["task_id"]
                        holdout_workspace(Path(state["workspace_path"]), holdout, acceptance_file)
                        acceptance = runner.run(holdout).model_dump()
                    record = {
                        "case_id": case["id"],
                        "repeat": repeat,
                        "mode": mode,
                        "task_id": task["task_id"],
                        "thread_id": task["thread_id"],
                        "execution_status": state["execution_status"],
                        "error": state["error"],
                        "duration_seconds": time.monotonic() - started,
                        "model_calls": state["model_calls"],
                        "tokens": (state["input_tokens"] + state["output_tokens"])
                        if state.get("token_usage_complete", True)
                        else None,
                        "retry_count": state["retry_count"],
                        "test_result": state["test_results"][-1] if state["test_results"] else None,
                        "acceptance": acceptance,
                    }
                    records.append(record)
                    with (output / "runs.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    finally:
        service.close()
    report = {
        "model_mode": settings.model_mode,
        "model_name": settings.model_name,
        "dataset_cases": len(dataset),
        "repeats": repeats,
        "note": "null means no execution evidence. Mock results do not measure LLM capability.",
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
        "null 表示缺少实际测试证据，不代表测试通过。Mock 仅衡量流程。",
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
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error("repeats must be between 1 and 100")
    output = args.output or Path(".repopilot/evaluations") / uuid.uuid4().hex
    if output.exists() and any(output.iterdir()):
        parser.error("Use a fresh output directory to avoid mixing evaluation records")
    report = run_evaluation(Settings(), args.repo, output, args.repeats)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Reports: {output.resolve()}")


if __name__ == "__main__":
    main()
