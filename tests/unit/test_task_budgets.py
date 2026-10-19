"""Durable budgets, explicitly controlled clocks and no provider calls."""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.budgets import BudgetExceeded, BudgetLimits, TaskBudget


def state_for(tmp_path, **limits):
    return {'task_path': str(tmp_path), 'task_id': 'test-task', 'budget_version': 1,
            'budget_limits': BudgetLimits(**limits).model_dump(), 'budget_deadline': time.time() + 60}


def test_restart_keeps_reservation_and_refuses_uncertain_replay(tmp_path):
    state = state_for(tmp_path)
    budget = TaskBudget(state, create=True)
    budget.reserve('model_requests')
    restarted = TaskBudget(state)
    assert restarted.view()['model_requests'] == 1
    with pytest.raises(BudgetExceeded, match='Interrupted dispatch'):
        restarted.reserve('model_requests')


def test_missing_ledger_and_changed_limits_cannot_reset_allowance(tmp_path):
    state = state_for(tmp_path)
    with pytest.raises(ValueError, match='missing'):
        TaskBudget(state)
    TaskBudget(state, create=True)
    state['budget_limits']['model_requests'] += 1
    with pytest.raises(ValueError, match='binding changed'):
        TaskBudget(state, create=True)


@pytest.mark.parametrize('resource', ['model_requests', 'sandbox_runs'])
def test_dispatch_limits_and_duplicate_completion(tmp_path, resource):
    state = state_for(tmp_path, **{resource: 1})
    budget = TaskBudget(state, create=True)
    ident = budget.reserve(resource)
    budget.complete(ident, {'input_tokens': 2})
    budget.complete(ident, {'input_tokens': 2})
    assert budget.view()['observed_tokens'] == 2
    with pytest.raises(BudgetExceeded) as exc:
        budget.reserve(resource)
    assert exc.value.resource == resource
    assert budget.view()[resource] == 1


@pytest.mark.parametrize('stats', [{'usage_complete': False}, {'input_tokens': 6, 'output_tokens': 5}])
def test_unknown_or_exhausted_usage_blocks_new_work(tmp_path, stats):
    budget = TaskBudget(state_for(tmp_path, observed_tokens=10), create=True)
    ident = budget.reserve('model_requests')
    budget.complete(ident, stats)
    with pytest.raises(BudgetExceeded) as exc:
        budget.check()
    assert exc.value.resource == 'observed_tokens'


def test_clock_rollback_does_not_restore_elapsed_allowance(tmp_path, monkeypatch):
    state = state_for(tmp_path)
    budget = TaskBudget(state, create=True)
    monkeypatch.setattr('app.services.budgets.time.time', lambda: state['budget_deadline'] - 1)
    assert budget.remaining() == pytest.approx(1, abs=0.1)
    monkeypatch.setattr('app.services.budgets.time.time', lambda: state['budget_deadline'] - 30)
    assert TaskBudget(state).remaining() == pytest.approx(1, abs=0.1)
    monkeypatch.setattr('app.services.budgets.time.time', lambda: state['budget_deadline'])
    with pytest.raises(BudgetExceeded) as exc:
        budget.check()
    assert exc.value.resource == 'wall_seconds'


def test_artifact_admission_preserves_oversized_files(tmp_path):
    budget = TaskBudget(state_for(tmp_path, artifact_bytes=1048576), create=True)
    evidence = tmp_path / 'evidence.bin'
    evidence.write_bytes(b'x' * 1048576)
    with pytest.raises(BudgetExceeded) as exc:
        budget.check()
    assert exc.value.resource == 'artifact_bytes'
    assert evidence.stat().st_size == 1048576


def test_parallel_dispatch_cannot_exceed_single_allowance(tmp_path):
    state = state_for(tmp_path, model_requests=1)
    TaskBudget(state, create=True)
    def reserve(_):
        try:
            return TaskBudget(state).reserve('model_requests')
        except BudgetExceeded:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        reservations = list(pool.map(reserve, range(4)))
    assert len([x for x in reservations if x is not None]) == 1
