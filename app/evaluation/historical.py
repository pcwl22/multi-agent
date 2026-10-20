"""Pinned upstream benchmark with evaluator-only reference/holdout controls.

Only Git data is read on the host. Every target test executes in Docker. No
approval, publication, model retry, or test mutation is performed by this tool.
"""
import argparse
import hashlib
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

from pydantic import Field

from app.config.settings import Settings
from app.evaluation.runner import MODES, holdout_workspace, run_evaluation
from app.models.budgets import BudgetLimits
from app.models.schemas import StrictModel, TestResult
from app.sandbox.runner import DockerRunner
from app.services.budgets import BudgetExceeded, TaskBudget, budget_scope
from app.tools.repository import Repository, is_test_file


class HistoricalCase(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    upstream: str = Field(pattern=r"^[a-z0-9-]+$", max_length=40)
    url: str = Field(pattern=r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    before_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    fix_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    repaired_files: list[str] = Field(min_length=1, max_length=8)
    issue: str = Field(min_length=10, max_length=10000)
    acceptance: str = Field(pattern=r"^test_[a-z0-9_]+\.py\.txt$")
    collection_entrypoint: str | None = None


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def save(path: Path, value: dict | list) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args], timeout=60)


def manifest(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("Linked corpus artifacts are forbidden")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return result


def safe_output(root: Path, relative: str) -> Path:
    parts = relative.replace("\\", "/").split("/")
    if any(p in {"", ".", ".."} or ":" in p for p in parts):
        raise ValueError("Corpus path escaped root")
    result = root.joinpath(*parts)
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Corpus path escaped root")
    for item in [result, *result.parents]:
        if item == root:
            break
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("Linked corpus path")
    return result


def export(repo: Path, revision: str, destination: Path) -> list[dict]:
    entries = git(repo, "ls-tree", "-rlz", "--full-tree", revision).split(b"\0")
    rows = []
    omitted_links = []
    total = 0
    for entry in entries:
        if not entry:
            continue
        header, path = entry.split(b"\t", 1)
        mode, kind, ident, size = header.decode().split()
        relative = path.decode("utf-8")
        if mode == "120000" and relative.startswith("docs/") and relative.endswith(".md"):
            omitted_links.append({"path": relative, "mode": mode, "git_blob_sha": ident})
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("Corpus contains a link, submodule or unsupported Git object")
        total += int(size)
        rows.append((path.decode("utf-8"), ident))
    if len(rows) > 5000 or total > 50000000:
        raise ValueError("Historical corpus export exceeds admission limits")
    destination.mkdir(parents=True)
    for relative, ident in rows:
        path = safe_output(destination, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(git(repo, "cat-file", "blob", ident))
    return omitted_links


def prepare(upstream_root: Path, output: Path, spec: Path | None = None) -> str:
    spec = spec or Path(__file__).parent / "historical_cases/spec.json"
    raw = spec.read_bytes()
    cases = [HistoricalCase.model_validate(x) for x in json.loads(raw)]
    if not 1 <= len(cases) <= 20 or len({x.id for x in cases}) != len(cases):
        raise ValueError("Use 1..20 unique historical cases")
    # Validate inputs before creating any output.
    for case in cases:
        repo = upstream_root / case.upstream
        if git(repo, "rev-parse", case.fix_commit + "^1").decode().strip() != case.before_commit:
            raise ValueError("Fix is not a direct child of the recorded baseline")
        for name in case.repaired_files:
            if not name.endswith(".py") or is_test_file(name):
                raise ValueError("Reference may only overlay non-test Python source")
            safe_output(output / "references" / case.id, name)
        if case.collection_entrypoint not in {None, "test.py", "tests.py"}:
            raise ValueError("Unsupported original test collection entrypoint")
    if output.exists():
        raise ValueError("Prepare requires a fresh output directory")
    output.mkdir(parents=True)
    (output / "acceptance").mkdir()
    (output / "case-spec.json").write_bytes(raw)
    records, dataset = [], []
    for case in cases:
        repo = upstream_root / case.upstream
        source = output / "sources" / case.id
        reference = output / "references" / case.id
        omitted_links = export(repo, case.before_commit, source)
        upstream_manifest = manifest(source)
        if case.collection_entrypoint:
            adapter = source / "tests/test_original_collection.py"
            if adapter.exists():
                raise ValueError("Collection adapter would replace an original test")
            adapter.parent.mkdir(exist_ok=True)
            adapter.write_text('import runpy\nimport unittest\nfrom pathlib import Path\n'
                f'_original = runpy.run_path(str(Path(__file__).resolve().parents[1] / {case.collection_entrypoint!r}))\n'
                'for _name, _value in _original.items():\n'
                '    if isinstance(_value, type) and issubclass(_value, unittest.TestCase):\n'
                '        globals()[_name] = _value\n', encoding="utf-8")
        # Do not silently drop original Python code or tests at the snapshot boundary.
        python_files = {p for p in manifest(source) if p.endswith(".py")}
        if not python_files <= set(Repository(source).list_files()):
            raise ValueError("Original Python files exceed the supported repository boundary")
        export(repo, case.before_commit, reference)
        if case.collection_entrypoint:
            target = reference / "tests/test_original_collection.py"
            target.parent.mkdir(exist_ok=True)
            target.write_bytes((source / "tests/test_original_collection.py").read_bytes())
        for name in case.repaired_files:
            safe_output(reference, name).write_bytes(git(repo, "show", case.fix_commit + ":" + name))
        oracle = output / "acceptance" / case.acceptance.removesuffix(".txt")
        oracle.write_bytes((spec.parent / "acceptance" / case.acceptance).read_bytes())
        records.append({"case": case.model_dump(), "upstream_manifest": upstream_manifest,
            "unmaterialized_documentation_links": omitted_links,
            "source_manifest": manifest(source), "reference_manifest": manifest(reference),
            "acceptance_sha256": sha(oracle.read_bytes()),
            "original_tests": {p: h for p, h in upstream_manifest.items() if is_test_file(p)},
            "omitted_non_python_files": sorted(set(upstream_manifest) - set(Repository(source).list_files()))})
        dataset.append({"id": case.id, "issue": case.issue,
                        "repository": "sources/" + case.id, "acceptance": oracle.name})
    save(output / "dataset.json", dataset)
    lock = {"version": 1, "spec_sha256": sha(raw),
            "dataset_sha256": sha((output / "dataset.json").read_bytes()), "cases": records}
    save(output / "lock.json", lock)
    return sha((output / "lock.json").read_bytes())


def verify(root: Path, expected_lock: str) -> dict:
    raw = (root / "lock.json").read_bytes()
    if sha(raw) != expected_lock:
        raise ValueError("Historical lock digest changed")
    lock = json.loads(raw)
    if sha((root / "case-spec.json").read_bytes()) != lock["spec_sha256"] or (
        sha((root / "dataset.json").read_bytes()) != lock["dataset_sha256"]):
        raise ValueError("Historical spec or dataset changed")
    for row in lock["cases"]:
        case = HistoricalCase.model_validate(row["case"])
        for folder, key in [("sources", "source_manifest"), ("references", "reference_manifest")]:
            if manifest(root / folder / case.id) != row[key]:
                raise ValueError("Historical source/reference changed")
        oracle = root / "acceptance" / case.acceptance.removesuffix(".txt")
        if sha(oracle.read_bytes()) != row["acceptance_sha256"]:
            raise ValueError("Hidden acceptance changed")
    return lock


class ProbeRunner:
    """Bounded Docker evidence for evaluator controls, outside repair-task quotas."""
    def __init__(self, settings: Settings, ledger_root: Path):
        self.settings, self.ledger_root = settings, ledger_root
        self.runner = DockerRunner(settings)
        self.records: list[dict] = []
        self.lock = threading.Lock()

    def run(self, workspace: Path) -> TestResult:
        root = self.ledger_root / uuid.uuid4().hex
        root.mkdir(parents=True)
        state = {"task_id": root.name, "task_path": str(root),
                 "budget_deadline": time.time() + self.settings.test_timeout + 20,
                 "budget_limits": BudgetLimits(sandbox_runs=1).model_dump()}
        budget = TaskBudget(state, create=True)
        reservation = budget.reserve("sandbox_runs")
        try:
            with budget_scope(budget):
                result = self.runner.run(workspace)
        except BudgetExceeded as exc:
            result = TestResult(status="timeout" if exc.resource == "wall_seconds" else "failed",
                                stderr=str(exc))
        finally:
            budget.complete(reservation)
        with self.lock:
            self.records.append({"workspace": str(workspace), "result": result.model_dump(),
                                 "budget": budget.view()})
        return result


def eligible(control: dict) -> bool:
    baseline, reference, suite, original = (control[k] for k in
        ["baseline_holdout", "reference_holdout", "reference_suite", "baseline_suite"])
    return (all(x.get("evidence") == "docker" and x.get("image_id") for x in
                [baseline, reference, suite, original])
        and baseline["status"] == "failed" and baseline["failed"] > 0 and not baseline["errors"]
        and reference["status"] == suite["status"] == "passed"
        and reference["passed"] > 0 and suite["passed"] > 0
        and not any(x["failed"] or x["errors"] for x in [reference, suite])
        and original["status"] in {"passed", "failed"} and not original["errors"])


def controls(root: Path, output: Path, lock_sha: str, settings: Settings) -> dict:
    if output.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(output.resolve()):
        raise ValueError("Corpus and evidence output must not overlap")
    lock = verify(root, lock_sha)
    if output.exists():
        raise ValueError("Controls require a fresh output directory")
    output.mkdir(parents=True)
    runner = ProbeRunner(settings, output / "probe-ledgers")
    rows = []
    for row in lock["cases"]:
        case = HistoricalCase.model_validate(row["case"])
        source, reference = root / "sources" / case.id, root / "references" / case.id
        oracle = root / "acceptance" / case.acceptance.removesuffix(".txt")
        before, after = output / case.id / "before", output / case.id / "reference"
        holdout_workspace(source, before, oracle)
        holdout_workspace(reference, after, oracle)
        result = {"id": case.id,
            "baseline_suite": runner.run(source).model_dump(),
            "baseline_holdout": runner.run(before).model_dump(),
            "reference_suite": runner.run(reference).model_dump(),
            "reference_holdout": runner.run(after).model_dump()}
        result["eligible"] = eligible(result)
        rows.append(result)
        save(output / "controls.json", {"lock_sha256": lock_sha, "cases": rows})
        print(json.dumps({"control": case.id, "eligible": result["eligible"]}), flush=True)
    verify(root, lock_sha)
    result = {"lock_sha256": lock_sha, "image": settings.sandbox_image, "cases": rows,
              "all_eligible": all(x["eligible"] for x in rows)}
    save(output / "controls.json", result)
    save(output / "probe-records.json", runner.records)
    return result


def summarize(records: list[dict]) -> dict:
    results = {}
    for mode in MODES:
        rows = [x for x in records if x["mode"] == mode]
        strict = [x for x in rows if x.get("strict_success")]
        results[mode] = {"planned_runs": len(rows), "ready_and_accepted": len(strict),
            "strict_success_rate": len(strict) / len(rows) if rows else None,
            "holdout_passed": sum(bool(x.get("acceptance") and x["acceptance"]["status"] == "passed") for x in rows),
            "budget_exhausted": sum(x["execution_status"] == "budget_exhausted" for x in rows),
            "unknown_usage": sum(x.get("tokens") is None for x in rows),
            "infrastructure_blocked": sum(x["execution_status"] in {"blocked", "invalid_case"} for x in rows),
            "provider_failures": sum(bool(x.get("provider_failure")) for x in rows),
            "observed_tokens": sum(x.get("tokens") or 0 for x in rows),
            "model_calls": sum(x["model_calls"] for x in rows),
            "duration_seconds": sum(x["duration_seconds"] for x in rows)}
    return results


def run(root: Path, output: Path, lock_sha: str, settings: Settings, *, repeats: int = 2,
        workers: int = 1, variants: dict[str, Settings] | None = None) -> dict:
    if settings.model_mode != "live" or not settings.task_budgets or not settings.patch_transactions:
        raise ValueError("Historical formal runs require live model, task budgets and patch transactions")
    if not settings.sandbox_image.startswith("sha256:"):
        raise ValueError("Pin the tested Docker image ID before the formal run")
    if not 1 <= repeats <= 10:
        raise ValueError("Historical repeats must be between 1 and 10")
    if settings.data_dir.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(settings.data_dir.resolve()):
        raise ValueError("Task storage must exclude all corpus/control inputs")
    for variant in (variants or {}).values():
        if variant.data_dir.resolve().is_relative_to(root.resolve()) or root.resolve().is_relative_to(variant.data_dir.resolve()):
            raise ValueError("Variant task storage must exclude the whole corpus")
    if settings.data_dir.exists() and any(settings.data_dir.iterdir()):
        raise ValueError("Use fresh task storage for the frozen formal run")
    lock = verify(root, lock_sha)
    if settings.repository_root.resolve() != (root / "sources").resolve():
        raise ValueError("Repair root must exclude references and hidden acceptance")
    control = json.loads((output / "controls/controls.json").read_text(encoding="utf-8"))
    if (control["lock_sha256"] != lock_sha or control["image"] != settings.sandbox_image or
        not control["all_eligible"] or len(control["cases"]) != len(lock["cases"]) or
        {x["id"] for x in control["cases"]} != {x["case"]["id"] for x in lock["cases"]} or
        not all(eligible(x) and all(x[k]["image_id"] == settings.sandbox_image for k in
            ["baseline_suite", "baseline_holdout", "reference_suite", "reference_holdout"])
            for x in control["cases"])):
        raise ValueError("All fixed-reference controls must pass before model evaluation")
    runner = ProbeRunner(settings, output / "formal-probe-ledgers")
    run_evaluation(settings, root / "sources", output / "formal", repeats,
                   dataset_file=root / "dataset.json", workers=workers, evaluation_runner=runner, variants=variants)
    records = [json.loads(x) for x in (output / "formal/runs.jsonl").read_text(encoding="utf-8").splitlines()]
    for record in records:
        if record["task_id"] is None:
            record.update(strict_success=False, original_tests_unchanged=None, budget=None,
                          budget_failure=None, provider_failure=None)
            continue
        state = json.loads((output / "formal/tasks" / record["task_id"] / "state.json").read_text(encoding="utf-8"))
        case = next(x for x in lock["cases"] if x["case"]["id"] == record["case_id"])
        actual = Repository(state["workspace_path"])
        try:
            unchanged = all(sha(actual.path(p).read_bytes()) == h
                            for p, h in case["source_manifest"].items() if p.endswith(".py") and is_test_file(p))
        except (ValueError, OSError):
            unchanged = False
        budget = TaskBudget(state).view()
        record.update(original_tests_unchanged=unchanged, budget=budget,
                      budget_failure=state.get("budget_failure"), provider_failure=state.get("failure"))
        record["strict_success"] = bool(unchanged and record["baseline_verified"] and
            record["execution_status"] == "awaiting_approval" and
            (record.get("test_result") or {}).get("status") == "passed" and
            record.get("acceptance") and record["acceptance"]["status"] == "passed")
    expected = len(lock["cases"]) * len(MODES) * repeats
    if len(records) != expected:
        raise ValueError("Formal result matrix is incomplete")
    verify(root, lock_sha)
    result = {"registry_lock_sha256": lock_sha, "cases": len(lock["cases"]), "runs": len(records),
        "repeats": repeats, "configuration": {"image": settings.sandbox_image,
            "budget_limits": settings.budget_limits.model_dump(), "retry_policy": settings.retry_workspace_policy,
            "patch_transactions": True, "workers": workers}, "modes": summarize(records),
        "limitations": "Small public historical sample; repeats are correlated, not independent bugs. "
            "Reference fixes are controls, never counted as model repairs. No human approvals or GitHub writes."}
    if variants:
        result["variants"] = {name: summarize([r for r in records if r["variant"] == name]) for name in variants}
        result["comparison_order"] = ("AB / BA" if repeats == 2 else "ABBA / BAAB") + f" by alternating case; rotate modes per block; {repeats // 2} repetitions per variant"
    save(output / "records.json", records)
    save(output / "report.json", result)
    save(output / "probe-records.json", runner.records)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "controls", "run"])
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--lock")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--workers", type=int, choices=[1, 2, 3], default=1)
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.upstream:
            parser.error("prepare requires --upstream")
        print(prepare(args.upstream, args.corpus))
    else:
        if not args.output or not args.lock:
            parser.error("controls/run require --output and --lock")
        settings = Settings()
        value = (controls(args.corpus, args.output / "controls", args.lock, settings)
                 if args.action == "controls" else run(args.corpus, args.output, args.lock, settings,
                                                      repeats=args.repeats, workers=args.workers))
        print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
