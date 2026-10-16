import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.model import MockModel
from app.api.main import create_app
from app.config.settings import Settings
from app.models.schemas import TaskRequest
from app.services.attempts import file_manifest, prepare_candidate
from app.services.tasks import TaskService
from tests.integration.test_mvp import EvidenceDouble


def windows_denied(code=5):
    error = PermissionError('Controlled Windows activation failure')
    error.winerror = code
    return error


@pytest.mark.parametrize('code', [5, 32, 33])
def test_transient_windows_rename_uses_same_prepared_identity_and_three_tries(tmp_path, monkeypatch, code):
    baseline = tmp_path / 'baseline'
    baseline.mkdir()
    (baseline / 'target.py').write_text('value = 1\n')
    original = Path.rename
    ids = []

    def rename(path, target):
        ids.append(json.loads((path / 'candidate.json').read_text())['candidate_id'])
        if len(ids) < 3:
            raise windows_denied(code)
        return original(path, target)

    monkeypatch.setattr(Path, 'rename', rename)
    candidate = prepare_candidate(tmp_path, 1, file_manifest(baseline))
    assert len(ids) == 3 and len(set(ids)) == 1 and ids[0] == candidate['candidate_id']


def test_non_windows_permission_error_is_not_automatically_retried(tmp_path, monkeypatch):
    baseline = tmp_path / 'baseline'
    baseline.mkdir()
    (baseline / 'target.py').write_text('value = 1\n')
    calls = []

    def denied(path, target):
        calls.append(path)
        raise PermissionError('Ordinary permission failure')

    monkeypatch.setattr(Path, 'rename', denied)
    with pytest.raises(PermissionError):
        prepare_candidate(tmp_path, 1, file_manifest(baseline))
    assert len(calls) == 1
    assert calls[0].is_dir()


def test_failed_initial_activation_is_queryable_and_manual_resume_reuses_staging(tmp_path, monkeypatch):
    root = Path(__file__).parents[2]
    original = Path.rename
    calls = []
    model_calls = []

    class CountedFixture(MockModel):
        def generate(self, schema, payload):
            model_calls.append(schema.__name__)
            return super().generate(schema, payload)

    def denied(path, target):
        calls.append(path)
        raise windows_denied()

    monkeypatch.setattr(Path, 'rename', denied)
    settings = Settings(repository_root=root / 'demo_repository', data_dir=tmp_path / 'data',
                        retry_workspace_policy='isolated')
    service = TaskService(settings, model=CountedFixture(), runner=EvidenceDouble())
    try:
        with TestClient(create_app(service=service)) as api:
            response = api.post('/api/tasks', json=dict(repository_path=str(settings.repository_root),
                               mode='single', issue_description='expired returns 500 expected 401'))
            assert response.status_code == 202
            task = response.json()
            assert task['execution_status'] == 'creation_failed'
            assert task['creation_attempts'] == 1 and task['creation_failures'][0]['winerror'] == 5
            assert len(calls) == 3 and not model_calls
            manifest = json.loads((calls[0] / 'candidate.json').read_text())
            assert api.get('/api/tasks/' + task['task_id']).json()['creation_failures']
            assert not api.get('/api/tasks/' + task['task_id'] + '/diff').json()['matches_recorded']
            service.close()
            service = TaskService(settings, model=CountedFixture(), runner=EvidenceDouble())
        monkeypatch.setattr(Path, 'rename', original)
        service.check_resume(task['task_id'])
        resumed = service.run(task['task_id'])
        assert resumed['execution_status'] == 'awaiting_approval'
        assert resumed['candidate_id'] == manifest['candidate_id']
        assert resumed['creation_attempts'] == 2 and len(resumed['creation_failures']) == 1
        assert resumed['attempts'] == 1 and resumed['retry_count'] == 0
        assert model_calls == ['Patch']
    finally:
        service.close()


def test_partial_baseline_is_retained_and_never_silently_recopied(tmp_path, monkeypatch):
    import app.services.tasks as module

    root = Path(__file__).parents[2]
    original = module.snapshot

    def partial(repo, destination):
        destination.mkdir(parents=True)
        (destination / 'partial.txt').write_text('diagnostic bytes')
        raise OSError('Controlled interruption during initial copy')

    monkeypatch.setattr(module, 'snapshot', partial)
    service = TaskService(Settings(repository_root=root / 'demo_repository', data_dir=tmp_path / 'data'),
                          runner=EvidenceDouble())
    try:
        task = service.create(TaskRequest(repository_path=str(root / 'demo_repository'),
                                          issue_description='expired returns 500 expected 401'))
        assert task['execution_status'] == 'creation_failed'
        orphan = Path(task['task_path']) / 'baseline/partial.txt'
        monkeypatch.setattr(module, 'snapshot', original)
        with pytest.raises(ValueError, match='Partial or changed'):
            service.check_resume(task['task_id'])
        assert orphan.read_text() == 'diagnostic bytes'
    finally:
        service.close()


def test_creation_retry_budget_remains_finite_and_staging_tamper_is_refused(tmp_path, monkeypatch):
    root = Path(__file__).parents[2]
    renames = []

    def denied(path, target):
        renames.append(path)
        raise windows_denied()

    monkeypatch.setattr(Path, 'rename', denied)
    settings = Settings(repository_root=root / 'demo_repository', data_dir=tmp_path / 'data',
                        retry_workspace_policy='isolated', max_retries=1)
    service = TaskService(settings, runner=EvidenceDouble())
    try:
        task = service.create(TaskRequest(repository_path=str(settings.repository_root),
                                          issue_description='expired returns 500 expected 401'))
        result = service.run(task['task_id'])
        assert result['creation_attempts'] == 2 and len(renames) == 6
        assert len(set(renames)) == 1 and not result['model_calls']
        with pytest.raises(ValueError, match='Creation retry budget exhausted'):
            service.check_resume(task['task_id'])
        assert service.run(task['task_id'])['creation_attempts'] == 2
        assert len(renames) == 6
        staged = renames[0]
        target = staged / 'workspace/auth.py'
        target.write_text('changed = True\n')
        with pytest.raises(ValueError, match='Unrecorded staging writes'):
            prepare_candidate(Path(task['task_path']), 1, task['creation_manifest'])
        assert target.read_text() == 'changed = True\n'
    finally:
        service.close()
