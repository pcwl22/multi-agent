"""Explicit fixture model, actual Docker; validates V2 without a live-model claim."""
import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.models.schemas import ContractCheck, Edit, Patch, Plan, Review, TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService

pytestmark = [pytest.mark.docker, pytest.mark.skipif(os.environ.get('REPOPILOT_RUN_DOCKER_TESTS') != '1', reason='Docker opt-in')]


class NormalizationFixture:
    def __init__(self, overlapping=False):
        self.calls = 0
        self.overlapping = overlapping

    def generate(self, schema, payload):
        usage = {'calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'adapter': 'explicit-normalization-fixture'}
        if schema is Plan:
            return Plan(issue_summary='Controlled functions', suspected_modules=['repair_operations.py'], search_strategy=['first', 'second'], repair_steps=['Update both values'], validation_strategy=['Docker']), usage
        if schema is Review:
            assert payload['binding_provenance']['origin'] == 'derived_from_actual_new_definitions'
            assert payload['binding_provenance']['original_model_claims'] == []
            return Review(approved=True, summary='Controlled review only', concerns=[],
                contract_checks=[ContractCheck(requirement='New tests', satisfied=True, evidence=payload['review_evidence']['test_facts'][0]['id'])]), usage
        assert schema is Patch and payload['candidate_protocol']['version'] == 2
        assert {x['symbol'] for x in payload['contract_api_context']['api_slices']} >= {'first', 'second'}
        self.calls += 1
        source = 'def first():\n    return 1\n\ndef second():\n    return 2\n'
        if self.overlapping and self.calls == 1:
            edits = [Edit(path='repair_operations.py', old='def first():\n    return 1', new='def first():\n    return 3'),
                     Edit(path='repair_operations.py', old='return 1', new='return 3')]
        elif self.overlapping:
            assert payload['patch_feedback'][-1]['diagnostics'][0]['code'] == 'overlapping_edits'
            edits = [Edit(path='repair_operations.py', old=source, new=source.replace('return 1', 'return 3').replace('return 2', 'return 4'))]
        else:
            edits = [Edit(path='repair_operations.py', old='return 1', new='return 3'),
                     Edit(path='repair_operations.py', old='return 2', new='return 4')]
        edits.append(Edit(path='tests/test_new.py', old='', new='from repair_operations import first, second\ndef test_values():\n    assert (first(), second()) == (3, 4)\n'))
        return Patch(rationale='Controlled independent hunks with omitted metadata', edits=edits), usage


@pytest.mark.parametrize('mode', ['single', 'multi_no_review', 'multi_full'])
def test_independent_edits_and_omitted_metadata_need_no_extra_model_retry(tmp_path, mode):
    _run(tmp_path, mode, False)


def test_overlap_is_preserved_and_retried_as_a_complete_candidate(tmp_path):
    _run(tmp_path, 'single', True)


def _run(tmp_path, mode, overlapping):
    root = tmp_path / 'repository'
    (root / 'tests').mkdir(parents=True)
    (root / 'repair_operations.py').write_text('def first():\n    return 1\n\ndef second():\n    return 2\n', encoding='utf-8')
    (root / 'tests/test_original.py').write_text('from repair_operations import first\ndef test_original():\n    assert isinstance(first(), int)\n', encoding='utf-8')
    settings = Settings(_env_file=None, repository_root=root, data_dir=tmp_path / 'data',
        retry_workspace_policy='isolated', patch_transactions=True, repair_quality_checks=True,
        repair_quality_policy_version=2, max_retries=1, test_timeout=30)
    model = NormalizationFixture(overlapping)
    service = TaskService(settings, model=model, runner=DockerRunner(settings))
    try:
        task = service.create(TaskRequest(repository_path=str(root), mode=mode,
            issue_description='Controlled fixture: first and second must return 3 and 4. Add NEW tests.'))
        state = service.run(task['task_id'])
        assert state['execution_status'] == 'awaiting_approval'
        assert state['repair_quality_version'] == 2
        assert state['attempts'] == (2 if overlapping else 1)
        assert state['regression_results'][-1]['status'] == 'demonstrated'
        assert state['regression_results'][-1]['baseline_result']['evidence'] == 'docker'
        event = [e for e in state['execution_history'] if e['node'] == 'candidate_quality'][-1]
        assert event['binding_origin'] == 'derived_from_actual_new_definitions'
        assert state['patches'][-1]['contract_tests'] == ['tests/test_new.py::test_values']
        if not overlapping:
            assert len(state['patches'][-1]['edits']) == 2
            assert event['normalization'][0]['input_edit_indices'] == [1, 2]
        before = Path(state['task_path']) / 'baseline/tests/test_original.py'
        assert before.read_bytes() == (Path(state['workspace_path']) / 'tests/test_original.py').read_bytes()
    finally:
        service.close()
