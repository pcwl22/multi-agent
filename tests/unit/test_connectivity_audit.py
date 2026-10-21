"""New read-only audit and redaction controls; no live provider calls."""
import hashlib
import json
import sqlite3
import time

import httpx
import pytest
from openai import APIStatusError

from app.agents.failures import provider_failure
from app.agents.transport import response_identity, sdk_versions
from app.models.budgets import BudgetLimits
from app.services.budget_audit import audit_ledger
from app.services.budgets import TaskBudget


@pytest.mark.parametrize('status,kind', [(401, 'credentials'), (403, 'credentials'),
    (429, 'rate_limit'), (500, 'provider_unavailable'), (503, 'provider_unavailable')])
def test_http_status_and_hashed_correlation_are_safe(status, kind):
    response = httpx.Response(status, request=httpx.Request('POST', 'https://private.invalid/secret'),
        headers={'x-request-id': 'private-id', 'authorization': 'private-secret'}, text='private-body')
    exc = APIStatusError('private-message', response=response, body={'secret': 'private-body'})
    actual = provider_failure(exc, streaming=True)
    assert actual['kind'] == kind
    assert actual['diagnostics']['http_status'] == status
    assert actual['diagnostics']['request_id_sha256'] == hashlib.sha256(b'private-id').hexdigest()
    assert actual['diagnostics']['streaming_requested']
    assert 'private' not in json.dumps(actual)


def test_wrapped_status_is_retained_without_reading_exception_message():
    response = httpx.Response(503, request=httpx.Request('POST', 'https://private.invalid'))
    wrapped = ValueError('private-message')
    wrapped.__cause__ = httpx.HTTPStatusError('private-body', request=response.request, response=response)
    actual = provider_failure(wrapped)
    assert actual['kind'] == 'provider_unavailable'
    assert actual['diagnostics']['http_status'] == 503
    assert actual['diagnostics']['phase'] == 'response'


def test_header_allowlist_and_local_sdk_metadata():
    assert response_identity(httpx.Response(200, headers={'x-request-id': 'x' * 513, 'other-id': 'private'})) == {'http_status': 200}
    assert response_identity(None) == {}
    assert {'httpx', 'openai', 'langchain-openai'} <= sdk_versions().keys()


def create_ledger(root):
    root.mkdir()
    return TaskBudget({'task_id': 'controlled', 'task_path': str(root),
        'budget_deadline': time.time() + 60, 'budget_limits': BudgetLimits().model_dump()}, create=True)


@pytest.mark.parametrize('state,expected', [('pending', 'unconfirmed_dispatch'), ('unknown', 'unknown'), ('complete', 'complete')])
def test_read_only_audit_preserves_bytes_and_never_resets_allowance(tmp_path, state, expected):
    budget = create_ledger(tmp_path / 'sealed')
    ident = budget.reserve('model_requests')
    if state != 'pending':
        budget.complete(ident, {'usage_complete': state == 'complete', 'input_tokens': 7})
    before = {p.name: p.read_bytes() for p in budget.root.iterdir()}
    actual = audit_ledger(budget.root)
    assert actual['usage_status'] == expected
    assert actual['usage_unknown'] is (state != 'complete')
    assert actual['model_request_reservations'] == 1
    assert actual['billing_status'] == 'not_reconciled' and not actual['automatic_replay_allowed']
    assert actual['observed_tokens'] == (0 if state == 'pending' else 7)
    assert before == {p.name: p.read_bytes() for p in budget.root.iterdir()}


@pytest.mark.parametrize('sidecar', ['-wal', '-shm', '-journal'])
def test_audit_refuses_journal_sidecars_without_modifying_them(tmp_path, sidecar):
    budget = create_ledger(tmp_path / 'unsealed')
    path = budget.root / ('budget.sqlite3' + sidecar)
    path.write_bytes(b'controlled-unsealed')
    with pytest.raises(ValueError, match='Seal'):
        audit_ledger(budget.root)
    assert path.read_bytes() == b'controlled-unsealed'


def test_audit_refuses_inconsistent_counters_and_linked_ledger(tmp_path):
    budget = create_ledger(tmp_path / 'corrupt')
    with sqlite3.connect(budget.path) as db:
        db.execute('UPDATE budget SET model_requests=1')
    with pytest.raises(ValueError, match='Counters'):
        audit_ledger(budget.root)
    linked = tmp_path / 'linked'
    linked.mkdir()
    try:
        (linked / 'budget.sqlite3').symlink_to(budget.path)
    except OSError:
        return  # Counter validation above is still executed on Windows.
    with pytest.raises(ValueError, match='Links'):
        audit_ledger(linked)
