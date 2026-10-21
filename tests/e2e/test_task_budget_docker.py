"""Real Docker quota/time evidence; the model is an explicitly fixture-only adapter."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.budgets import BudgetExceeded, BudgetLimits, TaskBudget, budget_scope
from app.services.tasks import TaskService

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get('REPOPILOT_RUN_DOCKER_TESTS') != '1', reason='Docker opt-in')]


def budget_for(tmp_path, seconds=30):
    return TaskBudget({'task_path': str(tmp_path), 'task_id': tmp_path.name,
        'budget_deadline': time.time() + seconds,
        'budget_limits': BudgetLimits(result_bytes=1048576).model_dump()}, create=True)


def workspace(tmp_path, code):
    root = tmp_path / 'workspace'
    (root / 'tests').mkdir(parents=True)
    (root / 'tests/test_budget_probe.py').write_text(code, encoding='utf-8')
    return root


def test_results_tmpfs_has_real_kernel_capacity_limit(tmp_path):
    root = workspace(tmp_path, """import errno
from pathlib import Path

def test_quota():
    path = Path('/results/fill.bin')
    exhausted = False
    try:
        with path.open('wb') as stream:
            for _ in range(4):
                stream.write(b'x' * 1048576)
                stream.flush()
    except OSError as exc:
        exhausted = exc.errno == errno.ENOSPC
    finally:
        path.unlink(missing_ok=True)
    assert exhausted
""")
    with budget_scope(budget_for(tmp_path)):
        result = DockerRunner(Settings(_env_file=None)).run(root)
    assert result.status == 'passed' and result.passed == 1 and result.evidence == 'docker'
    assert result.cases[0].name == 'test_quota'


def test_total_deadline_kills_hanging_test_and_removes_container(tmp_path):
    root = workspace(tmp_path, 'import time\n\ndef test_hang():\n    time.sleep(60)\n')
    started = time.monotonic()
    with budget_scope(budget_for(tmp_path, seconds=3)):
        with pytest.raises(BudgetExceeded) as exc:
            DockerRunner(Settings(_env_file=None, test_timeout=60)).run(root)
    assert exc.value.resource == 'wall_seconds'
    assert time.monotonic() - started < 18
    containers = subprocess.check_output(['docker', 'ps', '-aq', '--filter',
                                         f'label=repopilot.task={tmp_path.name}'], timeout=10)
    assert not containers.strip()


@pytest.mark.parametrize('policy', ['preserve', 'isolated'])
def test_fixture_repair_has_real_docker_and_budget_evidence(tmp_path, policy):
    source = Path(__file__).parents[2] / 'test_fixtures/repair_repository'
    settings = Settings(_env_file=None, repository_root=source, data_dir=tmp_path / 'data',
        task_budgets=True, patch_transactions=True, retry_workspace_policy=policy)
    service = TaskService(settings)
    try:
        task = service.create(TaskRequest(repository_path=str(source),
            issue_description='expired returns 500 expected 401'))
        result = service.run(task['task_id'])
        assert result['execution_status'] == 'awaiting_approval'
        assert result['test_results'][-1]['evidence'] == 'docker'
        assert result['regression_results'][-1]['status'] == 'demonstrated'
        view = service.budget(task['task_id'])
        assert view['model_requests'] == 3 and view['sandbox_runs'] == 2
        assert view['pending_reservations'] == 0
    finally:
        service.close()


def test_noisy_test_cannot_displace_bounded_report(tmp_path):
    root = workspace(tmp_path, "import os\n\ndef test_noise():\n    os.write(1, b'x' * 4000000)\n")
    with budget_scope(budget_for(tmp_path)):
        result = DockerRunner(Settings(_env_file=None)).run(root)
    assert result.status == 'passed' and result.passed == 1
    # pytest captures successful test output; the fixed report envelope is bounded too.
    assert len(result.stdout.encode()) <= 20000


def test_host_loss_preserves_charge_and_container_self_watchdog(tmp_path):
    root = workspace(tmp_path, 'import time\n\ndef test_hang():\n    time.sleep(60)\n')
    state = {'task_path': str(tmp_path), 'task_id': tmp_path.name, 'workspace_path': str(root),
             'budget_deadline': time.time() + 60, 'budget_limits': BudgetLimits().model_dump()}
    TaskBudget(state, create=True)
    path = tmp_path / 'worker.json'
    path.write_text(json.dumps(state), encoding='utf-8')
    worker = Path(__file__).parents[1] / 'integration/budget_docker_worker.py'
    env = dict(os.environ)
    for secret in ['OPENAI_API_KEY', 'GITHUB_TOKEN', 'LANGSMITH_API_KEY']:
        env.pop(secret, None)
    process = subprocess.Popen([sys.executable, '-I', str(worker), str(path)], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def containers():
        return subprocess.check_output(['docker', 'ps', '-aq', '--filter',
            f'label=repopilot.task={tmp_path.name}'], timeout=10).strip()
    try:
        deadline = time.monotonic() + 20
        while not containers() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.1)
        assert containers(), 'Worker did not start a real container'
        process.kill()
        process.wait(timeout=5)
        with pytest.raises(BudgetExceeded) as exc:
            TaskBudget(state).check()
        assert exc.value.resource == 'uncertain_dispatch'
        deadline = time.monotonic() + 12
        while containers() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not containers(), 'Container-local watchdog did not terminate the orphaned run'
        assert TaskBudget(state).view()['sandbox_runs'] == 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        ids = containers().decode().split()
        if ids:
            subprocess.run(['docker', 'rm', '-f', *ids], capture_output=True, timeout=10)
