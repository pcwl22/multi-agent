import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import app
from app.config.settings import Settings
from app.services.tasks import TaskService


@pytest.mark.docker
@pytest.mark.skipif(os.environ.get('REPOPILOT_RUN_DOCKER_TESTS') != '1', reason='Docker opt-in')
@pytest.mark.parametrize('point,code', [('after-intent', 83), ('after-activation', 84)])
def test_real_process_loss_before_creation_commit_keeps_intent_and_identity(tmp_path, point, code):
    root = Path(__file__).parents[2]
    data = tmp_path / 'data'
    source = root / 'demo_repository'
    env = dict(os.environ)
    env.pop('OPENAI_API_KEY', None)
    env.pop('GITHUB_TOKEN', None)
    worker = root / 'tests/integration/creation_recovery_worker.py'
    result = subprocess.run([
        sys.executable, '-I', '-c', 'import app,runpy,sys; sys.argv=sys.argv[1:]; '
        'runpy.run_path(sys.argv[0],run_name="__main__")', str(worker), str(data), str(source), point,
    ], env=env, capture_output=True, timeout=45)
    assert result.returncode == code, result.stderr.decode(errors='replace')
    assert (data / 'worker-app.txt').read_text() == str(Path(app.__file__).resolve())
    with sqlite3.connect(data / 'tasks.sqlite3') as connection:
        state = json.loads(connection.execute('select initial from tasks').fetchone()[0])
    assert state['execution_status'] == 'creating' and state['creation_attempts'] == 1
    service = TaskService(Settings(repository_root=source, data_dir=data, model_mode='mock'))
    try:
        service.check_resume(state['task_id'])
        repaired = service.run(state['task_id'])
        assert repaired['execution_status'] == 'awaiting_approval'
        assert repaired['attempts'] == 1 and repaired['creation_attempts'] == 1
        assert repaired['test_results'][-1]['evidence'] == 'docker'
        if point == 'after-activation':
            assert repaired['candidate_id'] == (data / 'prepared-id.txt').read_text()
    finally:
        service.close()
