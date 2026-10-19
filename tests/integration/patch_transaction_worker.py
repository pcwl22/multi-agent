"""Trusted hard-loss harness. Target repository execution remains Docker-only."""
import os
import sys
from pathlib import Path

from app.agents.model import MockModel
from app.config.settings import Settings
from app.models.schemas import Patch
from app.services import transactions
from app.services.tasks import TaskService


def main():
    data, source, task_id, point = sys.argv[1:]

    class CountedFixture(MockModel):
        def generate(self, schema, payload):
            if schema is Patch:
                with (Path(data) / "patch-calls.txt").open("a") as stream:
                    stream.write("Patch\n")
            return super().generate(schema, payload)

    def crash(where, journal):
        if where == point:
            os._exit(86)

    transactions.journal_checkpoint = crash
    service = TaskService(Settings(data_dir=Path(data), repository_root=Path(source), _env_file=None),
                          model=CountedFixture())
    try:
        service.run(task_id)
    finally:
        service.close()


if __name__ == "__main__":
    main()
