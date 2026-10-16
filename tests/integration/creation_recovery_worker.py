"""Trusted creation process-loss fixture. No target code is run on the host."""
import os
import sys
from pathlib import Path

import app
import app.services.tasks as module
from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.services.tasks import TaskService


def main():
    data, source, point = sys.argv[1:]
    root = Path(data)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'worker-app.txt').write_text(str(Path(app.__file__).resolve()))
    original = TaskService._store_initial

    def store(self, state):
        if point == 'after-activation' and state['execution_status'] == 'queued':
            (root / 'prepared-id.txt').write_text(state['candidate_id'])
            os._exit(84)
        original(self, state)
        if point == 'after-intent' and state['execution_status'] == 'creating':
            os._exit(83)

    module.TaskService._store_initial = store
    service = TaskService(Settings(repository_root=Path(source), data_dir=root,
                                   model_mode='mock', retry_workspace_policy='isolated'))
    service.create(TaskRequest(repository_path=source, mode='single',
                               issue_description='expired returns 500 expected 401'))
    raise AssertionError('Expected deliberate process termination')


if __name__ == '__main__':
    main()
