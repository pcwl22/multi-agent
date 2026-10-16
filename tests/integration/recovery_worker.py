"""Trusted test harness. Repository code is executed only by DockerRunner."""

import os
import sys
from pathlib import Path

from app.config.settings import Settings
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService
from app.tools.repository import Repository


def main():
    data, source, task_id, crash_point = sys.argv[1:]
    settings = Settings(data_dir=Path(data), repository_root=Path(source))

    class BeforeTestCrash(DockerRunner):
        def run(self, workspace, *args, **kwargs):
            (Path(data) / "crash-marker.txt").write_text("before-docker-test", encoding="utf8")
            os._exit(77)

    runner = BeforeTestCrash(settings) if crash_point == "before-test" else DockerRunner(settings)
    if crash_point == "after-write":
        original_apply = Repository.apply

        def crash_after_write(repo, patch):
            original_apply(repo, patch)
            (Path(data) / "crash-marker.txt").write_text("after-write", encoding="utf8")
            os._exit(78)

        Repository.apply = crash_after_write
    service = TaskService(settings, runner=runner)
    try:
        service.run(task_id)
    finally:
        service.close()


if __name__ == "__main__":
    main()
