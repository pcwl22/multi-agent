
from app.agents.feedback import failure_feedback
from app.sandbox.runner import parse_junit_cases


def test_literal_assertion_feedback_has_original_provenance_and_repeat_fingerprint(tmp_path):
    for name in ['baseline', 'workspace']:
        (tmp_path / name / 'tests').mkdir(parents=True)
        (tmp_path / name / 'tests/test_contract.py').write_text('pass\n')
    report = tmp_path / 'junit.xml'
    report.write_text('<testsuite><testcase file="tests/test_contract.py" name="test_tail" line="4">'
                      '<failure message="assert range(7, 8) == [7]">'
                      'E       assert range(7, 8) == [7]</failure></testcase></testsuite>')
    parsed = parse_junit_cases(report)
    state = dict(workspace_path=str(tmp_path / 'workspace'), attempts=1,
                 diff_digest='a' * 64, repair_feedback=[])
    result = dict(status='failed', evidence='docker', **parsed)
    first = failure_feedback(result, state)
    item = first['observations'][0]
    assert item['origin'] == 'original_test' and item['line'] == 5
    assert item['actual_expression'] == 'range(7, 8)'
    assert item['expected_expression'] == '[7]'
    second = failure_feedback(result, {**state, 'repair_feedback': [first]})
    assert second['identical_prior_failures'] == 1
    assert failure_feedback(result, {**state, 'diff_digest': 'b' * 64,
                                     'repair_feedback': [first]})['identical_prior_failures'] == 0


def test_testcase_paths_cannot_escape_and_unparseable_assertions_stay_observations(tmp_path):
    for name in ['baseline', 'workspace']:
        (tmp_path / name).mkdir()
    result = dict(status='failed', evidence='docker', cases=[dict(
        file='../outside.py', name='untrusted', status='error',
        details='E       assert call(secret)\n', message='raw', line=None)])
    feedback = failure_feedback(result, dict(workspace_path=str(tmp_path / 'workspace'),
                                            attempts=1, diff_digest='x'))
    assert feedback['observations'][0]['origin'] == 'unknown'
    assert feedback['observations'][0]['file'] == ''
    assert feedback['observations'][0]['expected_expression'] is None


def test_junit_case_limit_keeps_failures_and_marks_incomplete_evidence(tmp_path):
    report = tmp_path / 'junit.xml'
    report.write_text('<testsuite>' + '<testcase name="passing"/>' * 520 +
                      '<testcase name="bad"><failure message="oops"/></testcase></testsuite>')
    result = parse_junit_cases(report)
    assert result['cases_truncated'] and len(result['cases']) == 512
    assert result['cases'][0]['name'] == 'bad'
