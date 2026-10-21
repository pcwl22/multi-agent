"""Actual SDK wire/SSE with controlled HTTP, not live provider evidence."""
import json
import time
from types import SimpleNamespace

import httpx
import langchain_openai
import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr, ValidationError

from app.agents.model import LiveModel, ModelFailure
from app.agents.output_diagnostics import response_shape
from app.config.settings import Settings
from app.models.budgets import BudgetLimits
from app.models.schemas import Plan
from app.services.budgets import TaskBudget, budget_scope

PLAN = dict(issue_summary='probe', suspected_modules=[], search_strategy=['inspect'],
            repair_steps=['repair'], validation_strategy=['Docker'])


def response(streaming, reasoning=12):
    base = {'id': 'controlled', 'created': 0, 'model': 'controlled'}
    tool = {'id': 'call', 'type': 'function', 'function': {'name': 'Plan', 'arguments': json.dumps(PLAN)}}
    usage = {'prompt_tokens': 7, 'completion_tokens': 17, 'total_tokens': 24}
    if reasoning is not None:
        usage['completion_tokens_details'] = {'reasoning_tokens': reasoning}
    if not streaming:
        return httpx.Response(200, json={**base, 'object': 'chat.completion',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'role': 'assistant', 'content': None, 'tool_calls': [tool]}}], 'usage': usage})
    chunks = [{**base, 'object': 'chat.completion.chunk', 'choices': [{'index': 0,
        'finish_reason': None, 'delta': {'role': 'assistant', 'tool_calls': [{'index': 0, **tool}]}}]},
        {**base, 'object': 'chat.completion.chunk', 'choices': [{'index': 0,
          'finish_reason': 'tool_calls', 'delta': {}}]},
        {**base, 'object': 'chat.completion.chunk', 'choices': [], 'usage': usage}]
    return httpx.Response(200, text=''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n',
                          headers={'content-type': 'text/event-stream'})


def model_for(monkeypatch, client, **kwargs):
    def constructor(**options):
        return ChatOpenAI(**options, http_client=client)
    monkeypatch.setattr(langchain_openai, 'ChatOpenAI', constructor)
    return LiveModel(Settings(_env_file=None, model_name='controlled',
                             openai_api_key=SecretStr('test-only-key'), **kwargs))


def budget_for(path, tokens=250):
    return TaskBudget({'task_path': str(path), 'task_id': 'wire', 'budget_deadline': time.time()+30,
        'budget_limits': BudgetLimits(model_requests=1, observed_tokens=tokens).model_dump()}, create=True)


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('parameter', ['max_completion_tokens', 'max_tokens'])
@pytest.mark.parametrize('thinking', ['provider_default', 'disabled'])
def test_sdk_sends_one_bounded_limit_and_explicit_vendor_toggle(tmp_path, monkeypatch, streaming, parameter, thinking):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return response(streaming)
    budget = budget_for(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = model_for(monkeypatch, client, model_streaming=streaming,
                          model_max_output_tokens=8192, model_output_token_parameter=parameter,
                          model_thinking=thinking)
        with budget_scope(budget):
            value, stats = model.generate(Plan, {'issue_description': 'probe'})
    assert value.issue_summary == 'probe' and len(seen) == stats['calls'] == 1
    body = seen[0]
    other = 'max_tokens' if parameter == 'max_completion_tokens' else 'max_completion_tokens'
    assert body[parameter] == 250 and other not in body and 'extra_body' not in body
    assert body['tool_choice'] == {'type': 'function', 'function': {'name': 'Plan'}}
    assert body['parallel_tool_calls'] is False
    assert body.get('thinking') == ({'type': 'disabled'} if thinking == 'disabled' else None)
    assert stats['request_policy']['output_token_parameter'] == parameter
    shape = stats['response_shapes'][0]
    assert shape['reasoning_tokens'] == 12 and shape['reasoning_status'] == 'reported'
    assert shape['tool_calls'] == 1 and shape['invalid_tool_calls'] == 0
    assert budget.view()['observed_tokens'] == 24 and budget.view()['usage_complete']


@pytest.mark.parametrize('parameter', ['max_completion_tokens', 'max_tokens'])
@pytest.mark.parametrize('limit', [None, 128])
def test_unbudgeted_wire_does_not_invent_an_output_ceiling(monkeypatch, parameter, limit):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return response(False)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = model_for(monkeypatch, client, model_output_token_parameter=parameter,
                          model_max_output_tokens=limit)
        model.generate(Plan, {})
    assert seen[0].get(parameter) == limit
    other = 'max_tokens' if parameter == 'max_completion_tokens' else 'max_completion_tokens'
    assert other not in seen[0]


@pytest.mark.parametrize('streaming', [False, True])
def test_absent_reasoning_breakdown_is_missing_not_zero(monkeypatch, streaming):
    with httpx.Client(transport=httpx.MockTransport(lambda request: response(streaming, None))) as client:
        model = model_for(monkeypatch, client, model_streaming=streaming)
        _, stats = model.generate(Plan, {})
    assert stats['response_shapes'][0]['reasoning_tokens'] is None
    assert stats['response_shapes'][0]['reasoning_status'] == 'missing'


@pytest.mark.parametrize('reasoning', [-1, 18, 'private-reasoning', True])
def test_invalid_reasoning_breakdown_is_not_attributed_to_visible_output(reasoning):
    raw = SimpleNamespace(content='', tool_calls=[], invalid_tool_calls=[],
                          usage_metadata={'output_tokens': 17, 'output_token_details': {'reasoning': reasoning}})
    shape = response_shape(raw)
    assert shape['reasoning_tokens'] is None and shape['reasoning_status'] == 'invalid'


def test_response_shape_never_copies_body_tool_arguments_or_reasoning_text():
    secret = 'private-body-or-reasoning'
    raw = SimpleNamespace(content=[{'type': 'text', 'text': secret}]*129,
        tool_calls=[{'name': secret, 'args': {'value': secret}}]*129, invalid_tool_calls=[],
        additional_kwargs={'reasoning_content': secret}, usage_metadata={})
    shape = response_shape(raw)
    assert secret not in json.dumps(shape)
    assert shape['text_characters'] == len(secret)*128 and shape['text_measurement'] == 'capped'
    assert shape['tool_calls'] == 128 and shape['tool_count_capped']
    assert shape['reasoning_tokens'] is None


def test_unsupported_vendor_options_do_not_trigger_a_fallback_request(tmp_path, monkeypatch):
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={'error': {'message': 'controlled unsupported option'}})
    budget = budget_for(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = model_for(monkeypatch, client, model_output_token_parameter='max_tokens', model_thinking='disabled')
        with budget_scope(budget), pytest.raises(ModelFailure) as caught:
            model.generate(Plan, {})
    assert len(seen) == caught.value.stats['calls'] == 1
    assert budget.view()['model_requests'] == 1 and not budget.view()['usage_complete']


@pytest.mark.parametrize('kwargs', [{'model_output_token_parameter': 'automatic'}, {'model_thinking': 'enabled'}])
def test_vendor_switches_require_allowlisted_explicit_values(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)
