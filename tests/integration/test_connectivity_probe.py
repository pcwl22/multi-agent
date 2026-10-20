"""Actual SDK with controlled HTTP responses; never billed/live evidence."""
import hashlib
import json

import httpx
import pytest
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.agents.model import LiveModel
from app.evaluation.connectivity import ConnectivityPlan, run_probe, runtime_digest
from app.models.schemas import Plan


def freeze(tmp_path):
    path = tmp_path / 'plan.json'
    path.write_text(ConnectivityPlan(model_name='controlled-sdk', model_base_url='https://controlled.invalid/v1',
        runtime_sha256=runtime_digest()).model_dump_json(), encoding='utf-8')
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def factory(client):
    def create(settings, *, dispatch_gate):
        model = LiveModel(settings, dispatch_gate=dispatch_gate)
        model.min_interval = 0  # Controlled local HTTP fixtures need no provider pacing.
        model.client = ChatOpenAI(model='controlled-sdk', api_key='explicit-test-key',
            http_client=client, max_retries=2, streaming=settings.model_streaming, stream_usage=True)
        return model
    return create


@pytest.mark.parametrize('status', [401, 429, 503])
def test_failed_first_probe_stops_batch_and_cannot_be_replayed(tmp_path, status):
    path, digest = freeze(tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={'x-request-id': 'private-request-id'}, json={'error': 'private-body'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        output = tmp_path / 'results'
        report = run_probe(path, digest, output, SecretStr('explicit-test-key'), model_factory=factory(client))
        assert len(requests) == report['model_request_reservations'] == 1
        assert report['failed'] == report['not_run'] == report['unknown_usage_cells'] == 1
        assert not report['connectivity_smoke_passed'] and not report['repair_ability_evaluated']
        with pytest.raises(FileExistsError):
            run_probe(path, digest, output, SecretStr('explicit-test-key'), model_factory=factory(client))
    raw = (output / 'records.json').read_text(encoding='utf-8')
    assert 'private' not in raw and 'explicit-test-key' not in raw
    row = json.loads(raw)[0]
    assert row['stats']['failure']['diagnostics']['http_status'] == status
    assert row['stats']['sdk_versions']


def test_interrupted_dispatch_keeps_intent_and_pending_ledger(tmp_path):
    path, digest = freeze(tmp_path)
    def handler(request):
        raise KeyboardInterrupt()
    output = tmp_path / 'results'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(KeyboardInterrupt):
        run_probe(path, digest, output, SecretStr('explicit-test-key'), model_factory=factory(client))
    from app.services.budget_audit import audit_ledger
    audit = audit_ledger(output / 'fresh-nonstreaming')
    assert audit['pending_model_reservations'] == 1 and audit['usage_unknown']
    rows = json.loads((output / 'records.json').read_text(encoding='utf-8'))
    assert [r['status'] for r in rows] == ['dispatch_uncertain', 'not_run']
    assert not (output / 'report.json').exists()
    with pytest.raises(FileExistsError):
        run_probe(path, digest, output, SecretStr('explicit-test-key'))


def test_frozen_plan_and_runtime_checked_before_output_creation(tmp_path):
    path, digest = freeze(tmp_path)
    with pytest.raises(ValueError, match='digest'):
        run_probe(path, '0' * 64, tmp_path / 'bad', SecretStr('explicit-test-key'))
    assert not (tmp_path / 'bad').exists()
    value = json.loads(path.read_text(encoding='utf-8'))
    value['runtime_sha256'] = '0' * 64
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='runtime'):
        run_probe(path, hashlib.sha256(path.read_bytes()).hexdigest(), tmp_path / 'changed', SecretStr('explicit-test-key'))
    assert not (tmp_path / 'changed').exists()


@pytest.mark.parametrize('usage', [True, False])
def test_success_requires_both_transport_modes_and_complete_usage(tmp_path, usage):
    path, digest = freeze(tmp_path)
    requests = []
    value = Plan(issue_summary='controlled', suspected_modules=['none'], search_strategy=['none'],
        repair_steps=['none'], validation_strategy=['none'])
    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload.get('stream', False))
        tool = {'id': 'call_controlled', 'type': 'function', 'function': {
            'name': 'Plan', 'arguments': value.model_dump_json()}}
        counts = {'prompt_tokens': 4, 'completion_tokens': 3, 'total_tokens': 7}
        if not payload.get('stream'):
            response = {'id': 'controlled', 'model': 'controlled-sdk', 'object': 'chat.completion', 'created': 0,
                'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                    'role': 'assistant', 'content': None, 'tool_calls': [tool]}}]}
            if usage:
                response['usage'] = counts
            return httpx.Response(200, json=response)
        chunk = {'id': 'controlled', 'model': 'controlled-sdk', 'object': 'chat.completion.chunk', 'created': 0,
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'delta': {
                'role': 'assistant', 'tool_calls': [{**tool, 'index': 0}]}}]}
        final = {**chunk, 'choices': [], 'usage': counts}
        body = 'data: ' + json.dumps(chunk) + '\n\ndata: ' + json.dumps(final) + '\n\ndata: [DONE]\n\n'
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=body)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = run_probe(path, digest, tmp_path / 'results', SecretStr('explicit-test-key'), model_factory=factory(client))
    assert report['connectivity_smoke_passed'] is usage
    assert requests == ([False, True] if usage else [False])
    assert report['model_request_reservations'] == (2 if usage else 1)
    assert report['known_tokens_including_partial'] == (14 if usage else 0)
