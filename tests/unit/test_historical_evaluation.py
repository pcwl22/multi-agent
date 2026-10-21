"""Metadata and local-Git fixtures only; these never execute target Python."""
import json
import subprocess
from pathlib import Path

import pytest

from app.evaluation.historical import eligible, manifest, prepare, sha, summarize, verify


def controlled_git_case(tmp_path):
    repo = tmp_path / 'upstream/example'
    repo.mkdir(parents=True)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()
    git('init')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    (repo/'code.py').write_text('VALUE = 0\n', encoding='utf-8')
    (repo/'tests').mkdir()
    (repo/'tests/test_original.py').write_text('def test_original():\n    assert True\n', encoding='utf-8')
    git('add', '.')
    git('commit', '-m', 'controlled baseline')
    before = git('rev-parse', 'HEAD')
    (repo/'code.py').write_text('VALUE = 1\n', encoding='utf-8')
    git('add', '.')
    git('commit', '-m', 'controlled reference')
    fix = git('rev-parse', 'HEAD')
    spec_dir = tmp_path/'spec'
    (spec_dir/'acceptance').mkdir(parents=True)
    (spec_dir/'acceptance/test_contract.py.txt').write_text('def test_contract():\n    assert True\n', encoding='utf-8')
    case = {'id':'controlled-fixture','upstream':'example','url':'https://github.com/example/fixture',
        'before_commit':before, 'fix_commit':fix, 'repaired_files':['code.py'],
        'issue':'Controlled unit metadata fixture, never real upstream evidence.',
        'acceptance':'test_contract.py.txt', 'collection_entrypoint':None}
    spec = spec_dir/'spec.json'
    spec.write_text(json.dumps([case]), encoding='utf-8')
    return repo, spec, case


def test_registry_is_four_pinned_public_projects_with_private_oracles():
    from app.evaluation import historical
    root = Path(historical.__file__).parent/'historical_cases'
    cases = json.loads((root/'spec.json').read_text(encoding='utf-8'))
    assert len(cases) == len({x['url'] for x in cases}) == 4
    assert all(len(x['fix_commit']) == len(x['before_commit']) == 40 for x in cases)
    assert all((root/'acceptance'/x['acceptance']).is_file() for x in cases)


def test_prepare_preserves_original_tests_and_separates_oracle(tmp_path):
    repo, spec, _ = controlled_git_case(tmp_path)
    root = tmp_path/'corpus'
    digest = prepare(repo.parent, root, spec)
    lock = verify(root, digest)
    source, reference = root/'sources/controlled-fixture', root/'references/controlled-fixture'
    assert (source/'tests/test_original.py').read_bytes() == (reference/'tests/test_original.py').read_bytes()
    assert (source/'code.py').read_bytes() != (reference/'code.py').read_bytes()
    assert not (source/'acceptance').exists()
    assert (root/'acceptance/test_contract.py').is_file()
    assert lock['cases'][0]['original_tests'] == {'tests/test_original.py':sha((source/'tests/test_original.py').read_bytes())}


@pytest.mark.parametrize('target', ['dataset.json', 'acceptance/test_contract.py',
    'sources/controlled-fixture/code.py', 'references/controlled-fixture/code.py', 'lock.json'])
def test_frozen_input_tampering_is_detected_before_evaluation(tmp_path, target):
    repo, spec, _ = controlled_git_case(tmp_path)
    root = tmp_path/'corpus'
    digest = prepare(repo.parent, root, spec)
    with (root/target).open('ab') as stream:
        stream.write(b'\nchanged')
    with pytest.raises(ValueError, match='changed'):
        verify(root, digest)


@pytest.mark.parametrize('fault', ['parent', 'test-overlay', 'traversal'])
def test_invalid_provenance_is_rejected_before_export(tmp_path, fault):
    repo, spec, case = controlled_git_case(tmp_path)
    if fault == 'parent':
        case['before_commit'] = case['fix_commit']
    else:
        case['repaired_files'] = ['tests/test_original.py' if fault=='test-overlay' else '../escape.py']
    spec.write_text(json.dumps([case]), encoding='utf-8')
    root = tmp_path/'corpus'
    with pytest.raises(ValueError):
        prepare(repo.parent, root, spec)
    assert not root.exists()


def test_success_requires_ready_plus_independent_acceptance_and_keeps_failures():
    rows = [{'mode':'multi_full','execution_status':'awaiting_approval','strict_success':True,
        'acceptance':{'status':'passed'},'tokens':9,'model_calls':3,'duration_seconds':1},
        {'mode':'multi_full','execution_status':'failed','strict_success':False,
         'acceptance':{'status':'passed'},'tokens':10,'model_calls':4,'duration_seconds':2},
        {'mode':'multi_full','execution_status':'budget_exhausted','strict_success':False,
         'acceptance':None,'tokens':None,'model_calls':1,'duration_seconds':3}]
    result = summarize(rows)['multi_full']
    assert result['planned_runs']==3 and result['ready_and_accepted']==1
    assert result['holdout_passed']==2 and result['strict_success_rate']==pytest.approx(1/3)
    assert result['budget_exhausted']==result['unknown_usage']==1


def test_control_gate_rejects_doubles_errors_and_nonfailing_baselines():
    def result(status, **kwargs):
        return dict(status=status, passed=2 if status=='passed' else 0, failed=1 if status=='failed' else 0,
                    errors=0,evidence='docker',image_id='sha256:metadata-double-only',**kwargs)
    control={'baseline_suite':result('passed'),'baseline_holdout':result('failed'),
        'reference_suite':result('passed'),'reference_holdout':result('passed')}
    assert eligible(control)
    control['reference_suite']['evidence']='test_double'
    assert not eligible(control)
    control['reference_suite']['evidence']='docker'
    control['baseline_holdout']['errors']=1
    assert not eligible(control)
    control['baseline_holdout']['errors']=0
    control['baseline_holdout']['status']='passed'
    assert not eligible(control)


def test_linked_corpus_file_is_not_followed(tmp_path):
    external=tmp_path/'external'
    external.write_text('private',encoding='utf-8')
    root=tmp_path/'corpus'
    root.mkdir()
    try:
        (root/'link.py').symlink_to(external)
    except OSError:
        pytest.skip('No symlink privilege')
    with pytest.raises(ValueError,match='Linked'):
        manifest(root)


@pytest.mark.parametrize('link_path,allowed', [('docs/link.md',True),('package/link.py',False)])
def test_only_recorded_noncode_documentation_links_may_be_omitted(tmp_path, link_path, allowed):
    repo,spec,case=controlled_git_case(tmp_path)
    def git(*args,input=None):
        return subprocess.check_output(['git','-C',str(repo),*args],input=input).decode().strip()
    blob=git('hash-object','-w','--stdin',input=b'../README.md')
    git('update-index','--add','--cacheinfo',f'120000,{blob},{link_path}')
    git('commit','-m','controlled link baseline')
    case['before_commit']=git('rev-parse','HEAD')
    (repo/'code.py').write_text('VALUE = 2\n',encoding='utf-8')
    git('add','code.py')
    git('commit','-m','controlled link reference')
    case['fix_commit']=git('rev-parse','HEAD')
    spec.write_text(json.dumps([case]),encoding='utf-8')
    root=tmp_path/'corpus'
    if allowed:
        digest=prepare(repo.parent,root,spec)
        lock=verify(root,digest)
        assert lock['cases'][0]['unmaterialized_documentation_links']==[
            {'path':link_path,'mode':'120000','git_blob_sha':blob}]
        assert not (root/'sources/controlled-fixture'/link_path).exists()
    else:
        with pytest.raises(ValueError,match='link'):
            prepare(repo.parent,root,spec)
