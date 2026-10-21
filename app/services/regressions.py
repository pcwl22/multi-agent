"""Docker-only regression witness from original source plus unmodified added tests."""
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.schemas import TestResult
from app.services.attempts import controlled_path, file_manifest
from app.tools.repository import Repository, diff_repositories, digest, is_test_file, snapshot


class RegressionEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['demonstrated', 'not_demonstrated', 'unavailable', 'no_new_tests']
    generated_tests: list[str] = Field(default_factory=list, max_length=128)
    baseline_workspace: str | None = None
    baseline_result: TestResult | None = None
    fail_to_pass_tests: list[str] = Field(default_factory=list, max_length=512)
    note: str


def regression_witness(state: dict, runner) -> dict:
    current = state['test_results'][-1]
    if current['evidence'] != 'docker' or not current.get('cases'):
        return RegressionEvidence(status='unavailable', note=(
            'Current testcase evidence is absent or a test double; no baseline proof claimed.'
        )).model_dump()
    workspace = Path(state['workspace_path'])
    original = workspace.parent / 'baseline'
    repo = Repository(workspace)
    baseline = set(Repository(original).list_files())
    generated = [p for p in repo.list_files() if is_test_file(p) and p not in baseline]
    if not generated:
        return RegressionEvidence(status='no_new_tests', note='No added test files to replay.').model_dump()
    if len(generated) > 128:
        raise ValueError('Regression witness exceeds 128 added test files')
    if digest(diff_repositories(original, workspace)) != state['diff_digest']:
        raise ValueError('Workspace changed before regression witness')
    root = Path(state.get('task_path') or workspace.parent)
    destination = controlled_path(root, f'regression/attempt-{state["attempts"]}-{uuid.uuid4()}',
                                  directory=True)
    snapshot(Repository(original), destination)
    before = file_manifest(original)
    target = Repository(destination)
    for path in generated:
        output = target.path(path, existing=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(repo.path(path).read_bytes())
    if any(target.path(p).read_bytes() != Repository(original).path(p).read_bytes()
           for p in before):
        raise ValueError("Original tests or source changed in regression replay")
    result = runner.run(destination)
    if result.evidence != 'docker':
        raise ValueError('Baseline runner did not provide Docker evidence')
    passed = {(c['file'], c['classname'], c['name']) for c in current['cases']
              if c['status'] == 'passed' and c['file'] in generated}
    transitions = ['::'.join((c.file, c.classname, c.name)) for c in result.cases
                   if c.status == 'failed' and (c.file, c.classname, c.name) in passed]
    complete = not result.cases_truncated and not current.get('cases_truncated')
    status = ('unavailable' if result.status in {'unavailable', 'timeout'} or not complete
              else 'demonstrated' if transitions else 'not_demonstrated')
    if file_manifest(original) != before or digest(diff_repositories(original, workspace)) != state['diff_digest']:
        raise ValueError('Baseline or current candidate changed during regression witness')
    return RegressionEvidence(status=status, generated_tests=generated,
        baseline_workspace=str(destination), baseline_result=result,
        fail_to_pass_tests=transitions[:512], note=(
            'Same added test failed on original source and passed on this candidate. '
            'This is observed regression evidence, not proof of every issue contract. '
            'Collection errors, missing evidence, truncated cases and tests that pass '
            'on both versions do not demonstrate a regression.'
        )).model_dump()
