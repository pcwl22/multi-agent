"""Controlled model fixture + actual Docker, not live model quality evidence."""
import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.models.schemas import Edit, Patch, Plan, TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get('REPOPILOT_RUN_DOCKER_TESTS') != '1', reason='Docker tests are opt-in')]


class PreparationFixture:
    def __init__(self, fault):
        self.fault = fault
        self.payloads = []

    def generate(self, schema, payload):
        stats = {'calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'adapter': 'explicit-preparation-fixture'}
        if schema is Plan:
            return Plan(issue_summary='Controlled byte API fixture', suspected_modules=['repair_value.py'],
                search_strategy=['public_api'], repair_steps=['Return 1'], validation_strategy=['Docker']), stats
        assert schema is Patch
        self.payloads.append(payload)
        if len(self.payloads) == 1:
            setup = "struct.pack('>Q', -1)" if self.fault == 'unsigned' else "b'valid'.encode('utf-8')"
        else:
            facts = payload['failure_diagnostics'][-1]['test_preparation_context']['facts']
            assert facts and not facts[0]['runtime_order_observed']
            assert any(c['call'] == ('struct.pack' if self.fault == 'unsigned' else "b'valid'.encode") for c in facts[0]['calls'])
            setup = "b'valid'"
        test = ('import struct\nfrom repair_value import public_api\ndef test_contract():\n'
                f'    data = {setup}\n    assert public_api(data) == 1\n')
        return Patch(rationale='Controlled fixture repair, no model quality claim', edits=[
            Edit(path='repair_value.py', old='return 0', new='return 1'),
            Edit(path='tests/test_new.py', old='', new=test)],
            contract_tests=['tests/test_new.py::test_contract']), stats


@pytest.mark.parametrize('fault', ['unsigned', 'bytes-encode'])
def test_preparation_failure_context_supports_retry_without_weakening_witness(tmp_path, fault):
    root = tmp_path / 'repository'
    (root / 'tests').mkdir(parents=True)
    (root / 'repair_value.py').write_text('def public_api(data):\n    return 0\n', encoding='utf-8')
    original = 'from repair_value import public_api\ndef test_original():\n    assert isinstance(public_api(b"valid"), int)\n'
    (root / 'tests/test_original.py').write_text(original, encoding='utf-8')
    model = PreparationFixture(fault)
    settings = Settings(_env_file=None, repository_root=root, data_dir=tmp_path / 'data',
        retry_workspace_policy='isolated', patch_transactions=True, task_budgets=True,
        repair_quality_checks=True, repair_quality_policy_version=2, max_retries=1, test_timeout=30)
    service = TaskService(settings, model=model, runner=DockerRunner(settings))
    try:
        task = service.create(TaskRequest(repository_path=str(root), mode='single',
            issue_description='Controlled fixture: public_api accepts valid bytes and must return integer 1. Add NEW regression tests.'))
        state = service.run(task['task_id'])
        assert state['execution_status'] == 'awaiting_approval'
        assert len(model.payloads) == state['attempts'] == 2
        assert state['test_results'][0]['failed'] == 1
        assert state['regression_results'][-1]['status'] == 'demonstrated'
        assert state['regression_results'][-1]['baseline_result']['evidence'] == 'docker'
        assert Path(state['workspace_path'], 'tests/test_original.py').read_text(encoding='utf-8') == original
    finally:
        service.close()
