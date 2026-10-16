import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.models.schemas import Edit, Patch, TaskRequest
from app.services.tasks import TaskService


class RepeatingCandidate:
    def __init__(self):
        self.calls = 0

    def generate(self, schema, payload):
        assert schema is Patch
        if self.calls:
            feedback = payload['failure_diagnostics'][-1]
            assert feedback['observations'][0]['origin'] == 'generated_test'
            assert feedback['identical_prior_failures'] == self.calls - 1
        self.calls += 1
        return Patch(rationale='Controlled repeated-failure fixture', edits=[
            Edit(path='target.py', old='return n', new='return n * ' + ('2' if self.calls == 3 else '1')),
            Edit(path='tests/test_regression.py', old='', new=(
                'from target import calculate\n\ndef test_regression():\n    assert calculate(2) == 4\n')),
        ]), dict(calls=0, input_tokens=0, output_tokens=0, adapter='controlled-fixture')


@pytest.mark.docker
@pytest.mark.skipif(os.environ.get('REPOPILOT_RUN_DOCKER_TESTS') != '1', reason='Docker opt-in')
def test_real_docker_repeat_feedback_changes_third_candidate_within_shared_budget(tmp_path):
    source = tmp_path / 'source'
    (source / 'tests').mkdir(parents=True)
    (source / 'target.py').write_text('def calculate(n):\n    return n\n')
    original = source / 'tests/test_contract.py'
    original.write_text('from target import calculate\n\ndef test_original():\n    assert calculate(0) == 0\n')
    model = RepeatingCandidate()
    service = TaskService(Settings(repository_root=source, data_dir=tmp_path / 'data',
                                   retry_workspace_policy='isolated', max_retries=2), model=model)
    try:
        task = service.create(TaskRequest(repository_path=str(source), mode='single',
                                          issue_description='Return twice the input'))
        result = service.run(task['task_id'])
        assert result['execution_status'] == 'awaiting_approval'
        assert result['attempts'] == model.calls == 3 and result['retry_count'] == 2
        assert [t['status'] for t in result['test_results']] == ['failed', 'failed', 'passed']
        assert all(t['cases'] and t['evidence'] == 'docker' for t in result['test_results'])
        assert len(result['repair_feedback']) == 2
        for number in [1, 2, 3]:
            assert (Path(result['task_path']) / 'attempts' / f'{number:04}' /
                    'workspace/tests/test_contract.py').read_bytes() == original.read_bytes()
    finally:
        service.close()
