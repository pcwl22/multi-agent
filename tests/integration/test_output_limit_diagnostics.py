"""Real SDK parsing with controlled HTTP/SSE; these are not live LLM tests."""
import json
import time

import httpx
import langchain_openai
import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError

from app.agents.model import LiveModel, ModelFailure
from app.agents.output_diagnostics import observe_output
from app.config.settings import Settings
from app.models.budgets import BudgetLimits
from app.models.schemas import Plan
from app.services.budgets import BudgetExceeded, TaskBudget, budget_scope

VALUE = dict(issue_summary='probe', suspected_modules=[], search_strategy=['inspect'],
             repair_steps=['repair'], validation_strategy=['Docker'])


def wire_response(streaming, reason, valid=True, include_usage=True):
    arguments = json.dumps(VALUE) if valid else '{}'
    base = {'id': 'controlled', 'created': 0, 'model': 'controlled'}
    tool = {'id': 'call', 'type': 'function', 'function': {'name': 'Plan', 'arguments': arguments}}
    if streaming:
        chunks = [{**base, 'object': 'chat.completion.chunk', 'choices': [
            {'index': 0, 'finish_reason': None, 'delta': {'role': 'assistant',
                                                     'tool_calls': [{'index': 0, **tool}]}}]},
            {**base, 'object': 'chat.completion.chunk', 'choices': [
                {'index': 0, 'finish_reason': reason, 'delta': {}}]}]
        if include_usage:
            chunks.append({**base, 'object': 'chat.completion.chunk', 'choices': [],
                           'usage': {'prompt_tokens': 7, 'completion_tokens': 11, 'total_tokens': 18}})
        return httpx.Response(200, text=''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n',
                              headers={'content-type': 'text/event-stream'})
    body = {**base, 'object': 'chat.completion', 'choices': [{'index': 0, 'finish_reason': reason,
            'message': {'role': 'assistant', 'content': None, 'tool_calls': [tool]}}]}
    if include_usage:
        body['usage'] = {'prompt_tokens': 7, 'completion_tokens': 11, 'total_tokens': 18}
    return httpx.Response(200, json=body)


def budget_at(path, tokens=20000):
    return TaskBudget({'task_path': str(path), 'task_id': 'output-limit',
        'budget_deadline': time.time()+30,
        'budget_limits': BudgetLimits(model_requests=4, observed_tokens=tokens).model_dump()}, create=True)


def connect(monkeypatch, client, **settings):
    def constructor(**kwargs):
        return ChatOpenAI(**kwargs, http_client=client)
    monkeypatch.setattr(langchain_openai, 'ChatOpenAI', constructor)
    return LiveModel(Settings(_env_file=None, model_name='controlled',
                             openai_api_key=SecretStr('test-only-key'), **settings))


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('valid', [False, True])
def test_length_finish_stops_without_parse_replay_and_retains_usage(tmp_path, monkeypatch, streaming, valid):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return wire_response(streaming, 'length', valid)
    budget = budget_at(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = connect(monkeypatch, client, model_streaming=streaming, model_max_output_tokens=8192)
        with budget_scope(budget), pytest.raises(ModelFailure) as caught:
            model.generate(Plan, {'issue_description': 'probe'})
    stats = caught.value.stats
    assert len(seen) == stats['calls'] == budget.view()['model_requests'] == 1
    assert stats['usage_complete'] and budget.view()['observed_tokens'] == 18
    assert budget.view()['pending_reservations'] == 0
    assert stats['output_failure']['kind'] == 'output_truncated'
    assert stats['structured_attempts'][0]['finish_reason'] == 'length'
    assert stats['structured_attempts'][0]['output_limit'] == 8192
    assert 'failure' not in stats  # Truncation is not provider connectivity failure.
    assert seen[0].get('max_completion_tokens', seen[0].get('max_tokens')) == 8192


@pytest.mark.parametrize('configured,tokens,expected', [(None, 20000, 4096), (8192, 20000, 8192),
                                                       (8192, 100, 100), (32, 20000, 32)])
def test_effective_output_ceiling_respects_configuration_and_remaining_budget(tmp_path, monkeypatch, configured, tokens, expected):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return wire_response(False, 'tool_calls')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = connect(monkeypatch, client, model_max_output_tokens=configured)
        with budget_scope(budget_at(tmp_path, tokens)):
            value, stats = model.generate(Plan, {})
    assert value.issue_summary == 'probe'
    assert seen[0].get('max_completion_tokens', seen[0].get('max_tokens')) == expected
    assert stats['structured_attempts'] == [{'schema_name': 'Plan', 'finish_reason': 'tool_calls',
                                            'parse_status': 'parsed', 'output_limit': expected}]


def test_nontruncated_invalid_schema_retains_bounded_two_attempts(tmp_path, monkeypatch):
    seen = []
    def handler(request):
        seen.append(request)
        return wire_response(False, 'tool_calls', valid=False)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = connect(monkeypatch, client)
        with budget_scope(budget_at(tmp_path)), pytest.raises(ModelFailure) as caught:
            model.generate(Plan, {})
    assert len(seen) == caught.value.stats['calls'] == 2
    assert caught.value.stats['output_failure']['kind'] == 'schema_invalid'
    assert all(x['parse_status'] == 'invalid' for x in caught.value.stats['structured_attempts'])


def test_truncated_missing_usage_stays_unknown_and_cannot_be_replayed(tmp_path, monkeypatch):
    budget = budget_at(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(lambda request: wire_response(False, 'length', include_usage=False))) as client:
        model = connect(monkeypatch, client)
        with budget_scope(budget), pytest.raises(ModelFailure) as caught:
            model.generate(Plan, {})
    assert caught.value.stats['calls'] == 1 and not caught.value.stats['usage_complete']
    with pytest.raises(BudgetExceeded, match='usage incomplete'):
        budget.check()


def test_safe_observation_does_not_copy_provider_or_parser_text():
    secret = 'private-provider-value'
    observation = observe_output(secret, {'finish_reason': secret, 'body': secret}, 'invalid', 4096)
    assert secret not in json.dumps(observation)
    assert observation['schema_name'] == observation['finish_reason'] == 'other'
    assert observe_output('Plan', {}, 'missing', None)['finish_reason'] == 'unknown'


@pytest.mark.parametrize('limit', [0, -1, 32769])
def test_output_limit_configuration_rejects_invalid_bounds(limit):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, model_max_output_tokens=limit)
