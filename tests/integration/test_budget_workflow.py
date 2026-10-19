"""Budget integration uses explicit fixture models and non-executing runner doubles."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.model import MockModel
from app.api.main import create_app
from app.config.settings import Settings
from app.graph.workflow import build_graph
from app.models.schemas import Patch, TaskRequest
from app.services.budgets import BudgetLimits, TaskBudget
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble


def make_service(tmp_path, **limits):
    settings = Settings(_env_file=None, repository_root=Path(__file__).parents[2] /
        'test_fixtures/repair_repository', data_dir=tmp_path / 'data', task_budgets=True,
        budget_limits=BudgetLimits(**limits))
    return TaskService(settings, model=MockModel(), runner=EvidenceDouble())


def create(service):
    return service.create(TaskRequest(repository_path=str(service.settings.repository_root),
        issue_description='expired token returns 500 expected 401'))


def test_model_limit_stops_before_patch_and_api_refuses_resume(tmp_path):
    service = make_service(tmp_path, model_requests=1)
    try:
        task = create(service)
        state = service.run(task['task_id'])
        assert state['execution_status'] == 'budget_exhausted'
        assert state['budget_failure']['resource'] == 'model_requests'
        assert not state['patches'] and not state['test_results']
        with TestClient(create_app(service=service)) as api:
            view = api.get(f"/api/tasks/{task['task_id']}/budget").json()
            assert view['enabled'] and view['model_requests'] == 1
            assert api.post(f"/api/tasks/{task['task_id']}/resume").status_code == 409
        assert 'status_code=500' in (Path(state['workspace_path']) / 'auth.py').read_text()
    finally:
        service.close()


def test_saved_deadline_blocks_even_if_restart_settings_disable_budgets(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    task = create(service)
    settings = service.settings
    service.close()
    settings.task_budgets = False
    settings.budget_limits.wall_seconds = 86400
    monkeypatch.setattr('app.services.budgets.time.time', lambda: task['budget_deadline'] + 1)
    restarted = TaskService(settings, model=MockModel(), runner=EvidenceDouble())
    try:
        state = restarted.run(task['task_id'])
        assert state['execution_status'] == 'budget_exhausted'
        assert state['budget_failure']['resource'] == 'wall_seconds'
        assert restarted.budget(task['task_id'])['model_requests'] == 0
    finally:
        restarted.close()


def test_crashed_reservation_remains_terminal_after_restart(tmp_path):
    service = make_service(tmp_path)
    task = create(service)
    TaskBudget(task).reserve('model_requests')
    settings = service.settings
    service.close()
    restarted = TaskService(settings, model=MockModel(), runner=EvidenceDouble())
    try:
        state = restarted.run(task['task_id'])
        assert state['execution_status'] == 'budget_exhausted'
        assert state['budget_failure']['resource'] == 'uncertain_dispatch'
        assert not state['plan'] and not state['patches']
    finally:
        restarted.close()


def test_healthy_budget_does_not_change_human_interrupt(tmp_path):
    service = make_service(tmp_path)
    try:
        task = create(service)
        state = service.run(task['task_id'])
        assert state['execution_status'] == 'awaiting_approval'
        view = service.budget(task['task_id'])
        assert view['model_requests'] == 3 and view['sandbox_runs'] == 1
        assert view['pending_reservations'] == 0
        assert len(state['patches']) == 1
    finally:
        service.close()


@pytest.mark.parametrize('exhaustion', ['tokens', 'deadline'])
def test_response_budget_is_checked_before_any_patch_write(tmp_path, monkeypatch, exhaustion):
    service = make_service(tmp_path, observed_tokens=10)
    task = create(service)
    class ExpensivePatch(MockModel):
        def generate(self, schema, payload):
            value, stats = super().generate(schema, payload)
            if schema is Patch:
                if exhaustion == 'tokens':
                    stats['input_tokens'] = 11
                else:
                    monkeypatch.setattr('app.services.budgets.time.time', lambda: task['budget_deadline'] + 1)
            return value, stats
    service.graph = build_graph(
        service.settings, ExpensivePatch(), EvidenceDouble(), service.saver)
    try:
        state = service.run(task['task_id'])
        assert state['execution_status'] == 'budget_exhausted'
        assert not state['patches'] and not state['test_results'] and state['attempts'] == 0
        assert 'status_code=500' in (Path(state['workspace_path']) / 'auth.py').read_text()
        assert service.budget(task['task_id'])['model_requests'] == 2
    finally:
        service.close()
