"""Allowlisted diagnostics and circuit controls, no provider or target execution."""
import json
import time

import httpx
import pytest
from openai import APIConnectionError

from app.agents.failures import provider_failure
from app.agents.transport import transport_diagnostics
from app.models.reliability import budget_stop_notice
from app.services.budgets import BudgetExceeded, BudgetLimits, TaskBudget, stopped
from app.services.provider_circuit import ProviderCircuit, ProviderCircuitOpen


@pytest.mark.parametrize('kind,phase', [
    (httpx.ConnectTimeout, 'connect'), (httpx.ReadTimeout, 'read'),
    (httpx.WriteTimeout, 'write'), (httpx.PoolTimeout, 'pool'),
    (httpx.ConnectError, 'connect'), (httpx.ReadError, 'read'),
    (httpx.WriteError, 'write'), (httpx.ProxyError, 'proxy'),
    (httpx.RemoteProtocolError, 'protocol'), (httpx.LocalProtocolError, 'protocol'),
])
def test_sdk_wrapper_retains_specific_phase_without_private_data(kind, phase):
    wrapper = APIConnectionError(request=httpx.Request('POST', 'https://private.invalid/secret',
        headers={'Authorization': 'Bearer private-credential'}))
    wrapper.__cause__ = kind('private-body-and-token')
    value = provider_failure(wrapper, streaming=True)
    assert value['diagnostics']['phase'] == phase
    assert value['diagnostics']['streaming_requested'] is True
    assert value['diagnostics']['response_completion'] == 'unconfirmed'
    assert 'private' not in json.dumps(value) and 'Bearer' not in json.dumps(value)


def test_unknown_exception_names_messages_and_cycle_are_bounded():
    secret_class = type('PrivateCredentialInClassName', (Exception,), {})
    error = secret_class('PrivateExceptionBody')
    error.__cause__ = error
    detail = transport_diagnostics(error)
    assert detail['exception_types'] == ['OtherException'] and detail['chain_truncated']
    assert 'Private' not in json.dumps(detail)


def fail(circuit, kind='connection', phase='connect'):
    permit, _ = circuit.admit(lambda: None)
    circuit.complete(permit, {'kind': kind, 'diagnostics': {'phase': phase}})
    return permit


def test_success_and_different_failure_reset_matching_streak():
    circuit = ProviderCircuit(3)
    fail(circuit)
    fail(circuit)
    permit, _ = circuit.admit(lambda: None)
    circuit.complete(permit)
    assert circuit.snapshot()['consecutive_failures'] == 0
    fail(circuit, phase='read')
    fail(circuit)
    fail(circuit)
    assert not circuit.snapshot()['opened']
    fail(circuit)
    assert circuit.snapshot()['opened']


def test_in_flight_success_cannot_reopen_circuit_and_completion_is_idempotent():
    snapshots = []
    circuit = ProviderCircuit(1, on_change=snapshots.append)
    slow, _ = circuit.admit(lambda: None)
    failed = fail(circuit)
    circuit.complete(failed, {'kind': 'connection'})
    circuit.complete(slow)
    assert circuit.snapshot()['opened'] and circuit.snapshot()['completed'] == 2
    assert circuit.snapshot()['in_flight'] == 0
    reserve_calls = []
    with pytest.raises(ProviderCircuitOpen):
        circuit.admit(lambda: reserve_calls.append(True))
    assert not reserve_calls and snapshots[-1]['opened']


def test_disabled_circuit_and_fatal_credentials():
    disabled = ProviderCircuit(0)
    for _ in range(5):
        fail(disabled)
    assert not disabled.snapshot()['opened']
    enabled = ProviderCircuit(20)
    fail(enabled, kind='credentials')
    assert enabled.snapshot()['opened']


def test_refused_budget_does_not_acquire_or_charge_circuit_permit():
    circuit = ProviderCircuit(3)
    def refuse():
        raise BudgetExceeded('model_requests', 'controlled limit')
    with pytest.raises(BudgetExceeded):
        circuit.admit(refuse)
    assert circuit.snapshot()['admitted'] == circuit.snapshot()['in_flight'] == 0


@pytest.mark.parametrize('situation,kind,resource', [
    ('unknown', 'usage_unknown', 'observed_tokens'),
    ('pending', 'dispatch_uncertain', 'uncertain_dispatch'),
    ('numeric', 'limit_reached', 'observed_tokens'),
])
def test_budget_stop_kind_survives_ledger_restart(tmp_path, situation, kind, resource):
    state = {'task_id': 'controlled-budget', 'task_path': str(tmp_path),
        'budget_limits': BudgetLimits(observed_tokens=10).model_dump(), 'budget_deadline': time.time() + 30}
    budget = TaskBudget(state, create=True)
    reservation = budget.reserve('model_requests')
    if situation != 'pending':
        budget.complete(reservation, {'usage_complete': situation != 'unknown',
            'input_tokens': 10 if situation == 'numeric' else 0})
    with pytest.raises(BudgetExceeded) as caught:
        TaskBudget(state).check()
    value = stopped(caught.value)
    assert value['execution_status'] == 'budget_exhausted'  # Existing clients keep their contract.
    assert value['budget_failure']['kind'] == kind and value['budget_failure']['resource'] == resource
    if situation == 'unknown':
        assert TaskBudget(state).view()['usage_status'] == 'unknown'
        assert TaskBudget(state).view()['observed_tokens'] == 0


@pytest.mark.parametrize('state,phrase', [
    ({'budget_failure': {'kind': 'usage_unknown'}}, '用量尚未确认'),
    ({'budget_failure': {'resource': 'uncertain_dispatch'}}, '上次执行是否完成尚未确认'),
    ({'budget_failure': {'resource': 'ledger_integrity'}}, '无法安全核验'),
    ({'budget_failure': {'resource': 'observed_tokens'}, 'token_usage_complete': False}, '用量尚未确认'),
    ({'budget_failure': {'kind': 'limit_reached'}, 'token_usage_complete': True}, '达到预算限制'),
])
def test_new_and_legacy_budget_notices_preserve_meaning(state, phrase):
    assert phrase in budget_stop_notice(state)


@pytest.mark.parametrize('when', ['admission', 'completion'])
def test_evidence_write_failure_latches_without_losing_completed_usage(when):
    def unavailable(snapshot):
        if when == 'admission' or snapshot['completed']:
            raise OSError('private filesystem path')
    gate = ProviderCircuit(3, on_change=unavailable)
    reservations = []
    if when == 'admission':
        with pytest.raises(ProviderCircuitOpen):
            gate.admit(lambda: reservations.append(True))
        assert not reservations and gate.snapshot()['admitted'] == 0
    else:
        token, _ = gate.admit(lambda: reservations.append(True))
        gate.complete(token)
        assert gate.snapshot()['completed'] == 1 and gate.snapshot()['in_flight'] == 0
    assert gate.snapshot()['opened'] and gate.snapshot()['evidence_write_failed']
    assert 'private' not in json.dumps(gate.snapshot())
    with pytest.raises(ProviderCircuitOpen):
        gate.admit(lambda: reservations.append(True))
