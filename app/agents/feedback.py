"""Bounded, literal failure observations. Target text is parsed, never evaluated."""
import ast
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.tools.repository import Repository, digest, is_test_file


class FailureObservation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file: str = ''
    test: str
    origin: str
    line: int | None = None
    message: str
    assertion: str = ''
    actual_expression: str | None = None
    expected_expression: str | None = None
    details: str


def observations(result: dict, baseline: Path, workspace: Path, *, prioritize_original: bool = False) -> list[dict]:
    original = set(Repository(baseline).list_files())
    repo = Repository(workspace)
    items = []
    cases = result.get('cases', [])
    if prioritize_original:
        cases = sorted(cases, key=lambda c: c.get('file', '').replace('\\', '/') not in original)
    for case in cases:
        if case['status'] not in {'failed', 'error'}:
            continue
        path = case.get('file', '').replace('\\', '/')
        try:
            repo.path(path)
        except ValueError:
            path = ''
        assertion = ''
        actual = expected = None
        for line in case.get('details', '').splitlines():
            match = re.match(r'^E\s+assert (.+)$', line)
            if not match:
                continue
            assertion = match[1][:1000]
            try:
                node = ast.parse(assertion, mode='eval').body
                if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
                    actual, expected = ast.unparse(node.left), ast.unparse(node.comparators[0])
            except (SyntaxError, ValueError):
                pass
            break
        items.append(FailureObservation(
            file=path, test=case.get('name', '')[:1000], line=case.get('line'),
            origin='original_test' if path in original else
                   'generated_test' if path and is_test_file(path) else 'unknown',
            message=case.get('message', '')[:2000], assertion=assertion,
            actual_expression=actual, expected_expression=expected,
            details=case.get('details', '')[-2000:],
        ).model_dump())
        if len(items) == 8:
            break
    return items


def failure_feedback(result: dict, state: dict, *, prioritize_original: bool = False) -> dict:
    workspace = Path(state['workspace_path'])
    items = observations(result, workspace.parent / 'baseline', workspace, prioritize_original=prioritize_original)
    signature = [{k: o[k] for k in ('file', 'test', 'origin', 'assertion', 'message')}
                 for o in items]
    # Missing testcase evidence remains a bounded raw fallback, never invented assertions.
    if not signature:
        signature = [dict(status=result['status'], stderr=result.get('stderr', '')[:1000],
                          stdout=result.get('stdout', '')[-2000:])]
    normalized = re.sub(r'0x[0-9a-fA-F]+', '0xADDRESS', json.dumps(signature, sort_keys=True))
    fingerprint = digest(normalized)
    repeated = sum(p.get('diff_digest') == state['diff_digest'] and
                   p.get('failure_fingerprint') == fingerprint
                   for p in state.get('repair_feedback', []))
    return dict(attempt=state['attempts'], diff_digest=state['diff_digest'],
                failure_fingerprint=fingerprint, identical_prior_failures=repeated,
                observations=items, evidence=result['evidence'],
                raw_fallback=not bool(items),
                instruction=(
                    'This complete candidate and failure have already occurred. Identify why '
                    'the observed result violates the ORIGINAL issue; return a changed complete '
                    'candidate. Do not repeat the failing diff or weaken correct tests.'
                    if repeated else
                    'Compare the observed assertion with the ORIGINAL issue. Correct source '
                    'or an unjustified NEW test; existing tests stay immutable.'))


def compact_test_evidence(result: dict) -> dict:
    """Keep full evidence on disk, send bounded failure observations to the model."""
    value = {k: v for k, v in result.items() if k != "cases"}
    value["stdout"] = value.get("stdout", "")[-12000:]
    value["stderr"] = value.get("stderr", "")[-2000:]
    failures = [c for c in result.get("cases", []) if c["status"] in {"failed", "error"}]
    value["cases"] = [{**c, "details": c.get("details", "")[-2000:]} for c in failures[:8]]
    value["model_cases_omitted"] = len(result.get("cases", [])) - len(value["cases"])
    return value


def compact_regression_evidence(value: dict) -> dict:
    result = dict(value)
    if value.get("baseline_result"):
        result["baseline_result"] = compact_test_evidence(value["baseline_result"])
    transitions = value.get("fail_to_pass_tests", [])
    result["fail_to_pass_count"] = len(transitions)
    result["fail_to_pass_tests"] = transitions[:32]
    return result
