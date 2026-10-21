"""Trusted process-loss harness; fixture repository execution remains Docker-only."""

import os
import runpy
import sys
from pathlib import Path

import app
import app.graph.workflow as workflow
from app.config.settings import Settings
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService
from app.tools.repository import Repository


def main() -> None:
    data, source, task_id, point = sys.argv[1:]
    root = Path(data)
    (root / "worker-app.txt").write_text(str(Path(app.__file__).resolve()), encoding="utf8")
    fixtures = runpy.run_path(str(Path(__file__).parents[1] / "e2e/test_isolated_attempts.py"))
    model = fixtures["CandidateFixture"]("page-tail")
    settings = Settings(data_dir=root, repository_root=Path(source), model_mode="mock",
                        retry_workspace_policy="isolated", max_retries=1)
    original_prepare = workflow.prepare_candidate
    original_apply = Repository.apply

    def prepare(*args, **kwargs):
        candidate = original_prepare(*args, **kwargs)
        if candidate["candidate_number"] == 2 and point == "prepared-before-checkpoint":
            (root / "prepared-id.txt").write_text(candidate["candidate_id"], encoding="utf8")
            os._exit(79)
        return candidate

    def apply(repo, patch):
        result = original_apply(repo, patch)
        if repo.root.parent.name == "0002" and point == "after-write":
            os._exit(80)
        return result

    class Runner(DockerRunner):
        def run(self, workspace, *args, **kwargs):
            if workspace.parent.name == "0002" and point == "before-test":
                os._exit(81)
            return super().run(workspace, *args, **kwargs)

    workflow.prepare_candidate = prepare
    Repository.apply = apply
    service = TaskService(settings, model=model, runner=Runner(settings))
    try:
        service.run(task_id)
    finally:
        service.close()


if __name__ == "__main__":
    main()
