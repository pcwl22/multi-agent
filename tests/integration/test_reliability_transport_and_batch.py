"""Actual SDK + injected HTTP transport; fixture fault controls, never live-LLM evidence."""
import json
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.agents.model import LiveModel, ModelFailure
from app.api.main import create_app
from app.config.settings import Settings
from app.evaluation.runner import run_evaluation
from app.models.schemas import Plan, TaskRequest, TestResult
from app.services.budgets import BudgetExceeded, BudgetLimits, TaskBudget, budget_scope
from app.services.provider_circuit import ProviderCircuit, ProviderCircuitOpen
from app.services.tasks import TaskService

SOURCE = Path(__file__).parents[2] / 'test_fixtures/repair_repository'


def make_budget(root, **limits):
    root.mkdir(parents=True, exist_ok=True)
    return TaskBudget({'task_path': str(root), 'task_id': root.name,
        'budget_deadline': time.time() + 60, 'budget_limits': BudgetLimits(**limits).model_dump()}, create=True)


def controlled_model(settings, client, gate=None):
    settings = settings.model_copy(update={'openai_api_key': SecretStr('explicit-test-key')})
    model = LiveModel(settings, dispatch_gate=gate)
    model.client = ChatOpenAI(model='controlled-sdk', api_key='explicit-test-key', http_client=client,
        streaming=settings.model_streaming, stream_usage=True, max_retries=2)
    return model


class CutStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b'data: {"id":"controlled","object":"chat.completion.chunk","created":0,"model":"controlled","choices":[{"index":0,"delta":{"role":"assistant","content":"partial"},"finish_reason":null}]}\n\n'
        raise httpx.ReadError('private-stream-token')


@pytest.mark.parametrize('fault,phase', [
    ('connect', 'connect'), ('read_timeout', 'read'), ('proxy', 'proxy'),
    ('protocol', 'protocol'), ('stream_cut', 'read'),
])
def test_physical_fault_is_once_charged_diagnosed_and_prevents_next_dispatch(tmp_path, fault, phase):
    requests = []
    def handler(request):
        requests.append(request)
        if fault == 'stream_cut':
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=CutStream())
        exc_type = {'connect': httpx.ConnectError, 'read_timeout': httpx.ReadTimeout,
                    'proxy': httpx.ProxyError, 'protocol': httpx.RemoteProtocolError}[fault]
        raise exc_type('private-request-url-and-token', request=request)
    gate = ProviderCircuit(1)
    budget = make_budget(tmp_path / 'first')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = controlled_model(Settings(_env_file=None, model_streaming=fault == 'stream_cut'), client, gate)
        with budget_scope(budget), pytest.raises(ModelFailure) as caught:
            model.generate(Plan, {'issue_description': 'Explicit controlled SDK failure'})
        stats = caught.value.stats
        assert stats['calls'] == len(requests) == budget.view()['model_requests'] == 1
        assert stats['failure']['diagnostics']['phase'] == phase
        assert 'private' not in json.dumps(stats)
        assert not budget.view()['usage_complete'] and budget.view()['pending_reservations'] == 0
        with pytest.raises(BudgetExceeded):
            budget.check()
        fresh = make_budget(tmp_path / 'second')
        with budget_scope(fresh), pytest.raises(ProviderCircuitOpen) as blocked:
            model.generate(Plan, {'issue_description': 'Must not issue another request'})
        assert blocked.value.stats['calls'] == fresh.view()['model_requests'] == 0
    assert gate.snapshot()['opened'] and gate.snapshot()['completed'] == 1
    assert gate.snapshot()['in_flight'] == 0 and len(requests) == 1


@pytest.mark.parametrize('usage', [True, False])
def test_completed_response_usage_is_distinct_from_missing_usage(tmp_path, usage):
    value = Plan(issue_summary='controlled', suspected_modules=['auth.py'], search_strategy=['expired'],
        repair_steps=['explicit fixture'], validation_strategy=['Docker'])
    def handler(request):
        response = {'id': 'controlled', 'model': 'controlled-sdk', 'object': 'chat.completion', 'created': 0,
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'call', 'type': 'function', 'function': {'name': 'Plan', 'arguments': value.model_dump_json()}}]}}]}
        if usage:
            response['usage'] = {'prompt_tokens': 4, 'completion_tokens': 3, 'total_tokens': 7}
        return httpx.Response(200, json=response)
    gate = ProviderCircuit(1)
    budget = make_budget(tmp_path / 'budget')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, budget_scope(budget):
        model = controlled_model(Settings(_env_file=None), client, gate)
        answer, stats = model.generate(Plan, {'issue_description': 'Controlled successful response'})
    assert answer == value and stats['calls'] == 1
    assert gate.snapshot()['opened'] is (not usage)
    assert stats['transport_attempts'][0]['outcome'] == ('response_complete' if usage else 'usage_missing')
    assert budget.view()['usage_status'] == ('complete' if usage else 'unknown')


class BaselineOnly:
    def __init__(self):
        self.calls = 0
    def run(self, workspace):
        self.calls += 1
        return TestResult(status='failed', failed=1, evidence='test_double')


@pytest.mark.parametrize('workers,threshold,attempts', [(1, 2, 2), (2, 1, 2)])
def test_batch_retains_unexecuted_cells_and_bounds_in_flight_requests(tmp_path, monkeypatch, workers, threshold, attempts):
    requests = []
    barrier = threading.Barrier(2) if workers == 2 else None
    def handler(request):
        requests.append(request)
        if barrier:
            barrier.wait(timeout=15)
        raise httpx.ConnectError('controlled connection fault', request=request)
    baseline = BaselineOnly()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        def factory(settings, *, dispatch_gate):
            return controlled_model(settings, client, dispatch_gate)
        monkeypatch.setattr('app.evaluation.runner.LiveModel', factory)
        settings = Settings(_env_file=None, model_mode='live', repository_root=SOURCE, data_dir=tmp_path / 'data',
            task_budgets=True, evaluation_provider_failure_threshold=threshold)
        output = tmp_path / 'report'
        report = run_evaluation(settings, SOURCE, output, workers=workers, evaluation_runner=baseline)
    records = [json.loads(line) for line in (output / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(records) == 9 and len(requests) == attempts
    assert sum(r['model_calls'] for r in records) == attempts
    not_run = [r for r in records if r['execution_status'] == 'not_run']
    assert len(not_run) == 9 - attempts
    assert all(r['task_id'] is None and r['tokens'] == 0 and not r['model_attempted'] for r in not_run)
    assert all(r['not_run_reason'] == 'provider_circuit_open' for r in not_run)
    assert sum(m['not_run'] for m in report['modes'].values()) == 9 - attempts
    assert all(m['planned_ready_and_accepted_rate'] == 0 for m in report['modes'].values())
    assert report['provider_circuit']['opened'] and report['provider_circuit']['in_flight'] == 0
    assert baseline.calls == workers
    with pytest.raises(ValueError, match='fresh output'):
        run_evaluation(settings, SOURCE, output, evaluation_runner=baseline)


@pytest.mark.parametrize('stop', ['unknown', 'circuit'])
def test_task_api_and_restart_never_replay_uncertain_or_batch_paused_requests(tmp_path, stop):
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ConnectError('controlled fault', request=request)
    gate = ProviderCircuit(1)
    if stop == 'circuit':
        token, _ = gate.admit(lambda: None)
        gate.complete(token, {'kind': 'connection'})
    settings = Settings(_env_file=None, model_mode='live', repository_root=SOURCE,
        data_dir=tmp_path / 'data', task_budgets=True)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = TaskService(settings, model=controlled_model(settings, client, gate), runner=BaselineOnly())
        task = service.create(TaskRequest(repository_path=str(SOURCE), issue_description='Explicit fixture connectivity check'))
        result = service.run(task['task_id'])
        assert result['execution_status'] == ('budget_exhausted' if stop == 'unknown' else 'batch_paused')
        if stop == 'unknown':
            assert result['budget_failure']['kind'] == 'usage_unknown'
        service.close()
        settings.task_budgets = False
        restarted = TaskService(settings, model=controlled_model(settings, client), runner=BaselineOnly())
        try:
            with TestClient(create_app(service=restarted)) as api:
                assert api.post(f"/api/tasks/{task['task_id']}/resume").status_code == 409
                view = api.get(f"/api/tasks/{task['task_id']}/budget").json()
                assert view['usage_status'] == ('unknown' if stop == 'unknown' else 'complete')
            with pytest.raises(ValueError):
                restarted.run(task['task_id'])
        finally:
            restarted.close()
    assert len(requests) == (1 if stop == 'unknown' else 0)


def test_local_pre_dispatch_failure_does_not_invent_unknown_usage(tmp_path, monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        raise AssertionError('No HTTP dispatch expected')
    gate = ProviderCircuit(1)
    budget = make_budget(tmp_path / 'budget')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = controlled_model(Settings(_env_file=None), client, gate)
        def invalid_config(**kwargs):
            raise ValueError('private local configuration')
        monkeypatch.setattr(model.client.root_client, 'with_options', invalid_config)
        with budget_scope(budget), pytest.raises(ModelFailure) as caught:
            model.generate(Plan, {'issue_description': 'Controlled pre-dispatch configuration fault'})
    assert caught.value.stats['calls'] == budget.view()['model_requests'] == 0
    assert caught.value.stats['usage_complete'] and budget.view()['usage_complete']
    assert 'private' not in json.dumps(caught.value.stats)
    assert not requests and gate.snapshot()['admitted'] == 0
