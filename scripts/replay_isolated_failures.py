"""Controlled replay of prior wrong-test proposals; no live model or GitHub writes."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import Settings
from app.evaluation.runner import holdout_workspace
from app.models.schemas import Patch, TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService
from app.tools.repository import Repository, is_test_file


class ReplayCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    repository: str
    issue: str
    original_task_id: str
    acceptance: str
    image: str
    bad_patch: Patch
    corrected_patch: Patch


class ReplayModel:
    def __init__(self, case: ReplayCase):
        self.case = case
        self.calls = 0

    def generate(self, schema: type[BaseModel], payload: dict) -> tuple[Patch, dict]:
        if schema is not Patch or payload["retry_workspace_policy"] != "isolated":
            raise ValueError("Replay requires isolated single mode")
        self.calls += 1
        if self.calls > 2:
            raise ValueError("Replay fixture exhausted")
        return (self.case.bad_patch if self.calls == 1 else self.case.corrected_patch), {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "adapter": "controlled-replay",
        }


def replay(output: Path) -> dict:
    root = Path(__file__).resolve().parents[1]
    if output.exists():
        raise ValueError("Use a fresh output directory")
    cases = [ReplayCase.model_validate(item) for item in json.loads(
        (root / "docs/iteration3/replay-fixtures.json").read_text(encoding="utf8"))]
    output.mkdir(parents=True)
    records = []
    for case in cases:
        source = (root / case.repository).resolve(strict=True)
        acceptance = (root / case.acceptance).resolve(strict=True)
        if not source.is_relative_to(root) or not acceptance.is_relative_to(root):
            raise ValueError("Replay fixture escaped project root")
        settings = Settings(repository_root=source, data_dir=output / "services" / case.id,
                            retry_workspace_policy="isolated", max_retries=1,
                            sandbox_image=case.image, test_timeout=120, model_mode="mock")
        service = TaskService(settings, model=ReplayModel(case))
        try:
            task = service.create(TaskRequest(repository_path=str(source), mode="single",
                                              issue_description=case.issue))
            state = service.run(task["task_id"])
            tests = state["test_results"]
            assert state["execution_status"] == "awaiting_approval", state["error"]
            assert state["attempts"] == 2 and state["retry_count"] == 1
            assert [t["status"] for t in tests] == ["failed", "passed"]
            first = Path(state["attempt_history"][0]["workspace_path"])
            for edit in case.bad_patch.edits:
                if is_test_file(edit.path):
                    assert Repository(first).path(edit.path).read_text(encoding="utf8") == edit.new
            holdout = output / "holdouts" / case.id
            holdout_workspace(Path(state["workspace_path"]), holdout, acceptance)
            accepted = DockerRunner(settings).run(holdout).model_dump()
            assert accepted["status"] == "passed"
            record = {
                "case_id": case.id, "original_task_id": case.original_task_id,
                "task_id": state["task_id"], "execution_status": state["execution_status"],
                "attempts": 2, "retry_count": 1, "model_calls": 0,
                "model_adapter": "controlled-replay", "benchmark_run": False,
                "test_attempts": tests, "acceptance": accepted,
                "oracle_sha256": hashlib.sha256(acceptance.read_bytes()).hexdigest(),
                "original_tests_unchanged": True, "prior_generated_test_unchanged": True,
                "candidate_ids": [state["attempt_history"][0]["candidate_id"], state["candidate_id"]],
            }
            artifacts = output / "artifacts" / case.id
            artifacts.mkdir(parents=True)
            for number in [1, 2]:
                directory = Path(state["task_path"]) / "attempts" / f"{number:04}"
                shutil.copyfile(directory / "evidence.json", artifacts / f"attempt-{number}.json")
            records.append(record)
            (output / "report.json").write_text(json.dumps({
                "note": "Controlled fixture replay with real Docker. Corrected tests are evaluator-authored. No real LLM calls; excluded from live benchmark results.",
                "records": records,
            }, ensure_ascii=False, indent=2), encoding="utf8")
            print(f"{case.id}: failed -> passed; preserved prior test; independent acceptance passed",
                  flush=True)
        finally:
            service.close()
    return {"records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    replay(args.output)


if __name__ == "__main__":
    main()
