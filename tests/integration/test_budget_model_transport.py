"""Actual SDK with a controlled HTTP transport, never a live LLM."""
import json
import time

import httpx
import pytest
from langchain_openai import ChatOpenAI

from app.agents.model import LiveModel, ModelFailure
from app.config.settings import Settings
from app.models.schemas import Plan
from app.services.budgets import BudgetExceeded, BudgetLimits, TaskBudget, budget_scope


def budget_for(tmp_path, **limits):
    return TaskBudget({'task_path': str(tmp_path), 'task_id': 'transport', 'budget_deadline': time.time() + 30,
        'budget_limits': BudgetLimits(**limits).model_dump()}, create=True)


@pytest.mark.parametrize('fault', ['server', 'invalid', 'missing_usage', 'usage'])
def test_sdk_budget_counts_physical_attempts_without_hidden_retries(tmp_path, monkeypatch, fault):
    monkeypatch.setenv('OPENAI_API_KEY', 'explicit-test-key')
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if fault == 'server':
            return httpx.Response(503, json={'error': {'message': 'controlled'}})
        value = Plan(issue_summary='expired', suspected_modules=['auth.py'], search_strategy=['expired'],
                     repair_steps=['401'], validation_strategy=['Docker'])
        answer = {'id': 'controlled', 'model': 'controlled', 'object': 'chat.completion', 'created': 0,
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                'content': None, 'tool_calls': [{'id': 'call', 'type': 'function',
                    'function': {'name': 'Plan', 'arguments': '{}' if fault == 'invalid' else value.model_dump_json()}}]}}]}
        if fault != 'missing_usage':
            answer['usage'] = {'prompt_tokens': 4, 'completion_tokens': 3, 'total_tokens': 7}
        return httpx.Response(200, json=answer)
    budget = budget_for(tmp_path, model_requests=1, observed_tokens=10)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = LiveModel(Settings(_env_file=None))
        model.client = ChatOpenAI(model='controlled', http_client=client, max_retries=2)
        with budget_scope(budget):
            if fault == 'server':
                with pytest.raises(ModelFailure):
                    model.generate(Plan, {'issue_description': 'expired'})
            elif fault == 'invalid':
                with pytest.raises(BudgetExceeded) as exc:
                    model.generate(Plan, {'issue_description': 'expired'})
                assert exc.value.resource == 'model_requests' and exc.value.stats['calls'] == 1
            else:
                model.generate(Plan, {'issue_description': 'expired'})
    assert len(requests) == budget.view()['model_requests'] == 1
    assert budget.view()['pending_reservations'] == 0
    if fault in {'usage', 'missing_usage'}:
        assert requests[0].get('max_completion_tokens', requests[0].get('max_tokens', 99999)) <= 10
        assert budget.view()['usage_complete'] is (fault == 'usage')
    if fault in {'server', 'missing_usage'}:
        with pytest.raises(BudgetExceeded, match='usage incomplete'):
            budget.check()


def test_pacing_refuses_wait_longer_than_task_deadline(tmp_path):
    from app.agents.pacing import RequestPacer
    pacer = RequestPacer()
    pacer.next_start = time.monotonic() + 20
    started = time.monotonic()
    with pytest.raises(BudgetExceeded) as exc:
        pacer.wait(5, deadline=time.monotonic() + 0.1)
    assert exc.value.resource == 'wall_seconds' and time.monotonic() - started < 1
