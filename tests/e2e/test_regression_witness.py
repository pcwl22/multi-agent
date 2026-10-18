import os
from pathlib import Path

import pytest

from app.agents.model import MockModel
from app.config.settings import Settings
from app.models.schemas import Review, TaskRequest
from app.services.regressions import regression_witness
from app.services.tasks import TaskService
from app.tools.repository import Repository, diff_repositories, digest, snapshot

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get('REPOPILOT_RUN_DOCKER_TESTS') != '1', reason='Docker opt-in')]


class WitnessReviewer(MockModel):
    def __init__(self):
        self.witness = None

    def generate(self, schema, payload):
        if schema is Review:
            self.witness = payload['regression_evidence'][-1]
            assert self.witness['status'] == 'demonstrated'
            assert self.witness['baseline_result']['evidence'] == 'docker'
            assert self.witness['fail_to_pass_tests']
            assert self.witness['diff_digest']
        return super().generate(schema, payload)


def test_reviewer_gets_same_test_baseline_failure_and_candidate_pass_with_actual_docker(tmp_path):
    root = Path(__file__).parents[2]
    model = WitnessReviewer()
    service = TaskService(Settings(repository_root=root / 'test_fixtures' / 'repair_repository', data_dir=tmp_path / 'data',
                                   retry_workspace_policy='isolated'), model=model)
    try:
        task = service.create(TaskRequest(repository_path=str(root / 'test_fixtures' / 'repair_repository'),
                                          issue_description='expired returns 500 expected 401'))
        state = service.run(task['task_id'])
        assert state['execution_status'] == 'awaiting_approval' and model.witness
        witness = model.witness
        assert witness['candidate_id'] == state['candidate_id']
        baseline = Path(state['task_path']) / 'baseline'
        replay = Path(witness['baseline_workspace'])
        current = Path(state['workspace_path'])
        for file in Repository(baseline).list_files():
            assert (replay / file).read_bytes() == (baseline / file).read_bytes()
        for file in witness['generated_tests']:
            assert (replay / file).read_bytes() == (current / file).read_bytes()
        assert all(t['status'] == 'passed' for t in state['test_results'])
        assert state['approval_status'] == 'pending'
    finally:
        service.close()


def test_passing_smoke_test_on_both_versions_is_not_regression_proof(tmp_path):
    from app.sandbox.runner import DockerRunner

    original = tmp_path / 'baseline'
    original.mkdir()
    (original / 'target.py').write_text('value = 1\n')
    current = tmp_path / 'workspace'
    snapshot(Repository(original), current)
    (current / 'target.py').write_text('value = 2\n')
    (current / 'tests').mkdir()
    (current / 'tests/test_smoke.py').write_text('def test_smoke():\n    assert True\n')
    runner = DockerRunner(Settings())
    result = runner.run(current)
    state = dict(workspace_path=str(current), task_path=str(tmp_path), attempts=1,
                 diff_digest=digest(diff_repositories(original, current)),
                 test_results=[result.model_dump()])
    witness = regression_witness(state, runner)
    assert witness['status'] == 'not_demonstrated' and not witness['fail_to_pass_tests']
    assert witness['baseline_result']['status'] == 'passed'
