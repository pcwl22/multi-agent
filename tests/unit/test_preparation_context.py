"""Static NEW-test facts; test source is deliberately never imported on host."""
import json

from app.agents.feedback import failure_feedback
from app.agents.test_context import preparation_context
from app.tools.repository import Repository, digest


def sample(tmp_path):
    root = tmp_path / 'workspace'
    (root / 'tests').mkdir(parents=True)
    code = """raise RuntimeError('Target source must never execute on host')
def test_timestamp():
    data = struct.pack('>Q', -1)
    assert public_api(data) is None

def test_unicode():
    assert slugify('ÄΩ', separator=' ') == 'ao'
"""
    (root / 'tests/test_new.py').write_text(code, encoding='utf-8')
    return root, code


def test_preparation_context_preserves_literal_types_and_unobserved_order(tmp_path):
    root, code = sample(tmp_path)
    packet = preparation_context(Repository(root), [
        {'origin': 'generated_test', 'file': 'tests/test_new.py', 'test': 'test_timestamp'},
        {'origin': 'generated_test', 'file': 'tests/test_new.py', 'test': 'test_unicode'}])
    first, second = packet['facts']
    assert first['source_text_sha256'] == digest(code) and not first['runtime_order_observed']
    assert first['calls'][0]['call'] == 'struct.pack'
    assert first['calls'][0]['arguments'][1] == {'expression': '-1', 'literal_type': 'int'}
    assert 'ÄΩ' in json.dumps(second, ensure_ascii=False)
    assert packet['context_chars'] <= packet['context_limit']


def test_original_unknown_paths_and_small_budget_do_not_invent_facts(tmp_path):
    root, _ = sample(tmp_path)
    observations = [
        {'origin': 'original_test', 'file': 'tests/test_new.py', 'test': 'test_timestamp'},
        {'origin': 'generated_test', 'file': '../outside.py', 'test': 'test_timestamp'},
        {'origin': 'generated_test', 'file': 'tests/test_new.py', 'test': 'missing'}]
    assert not preparation_context(Repository(root), observations)['facts']
    assert not preparation_context(Repository(root), [
        {'origin': 'generated_test', 'file': 'tests/test_new.py', 'test': 'test_unicode'}], 20)['facts']


def test_default_feedback_contract_unchanged_and_new_context_explicit(tmp_path):
    root, _ = sample(tmp_path)
    (root.parent / 'baseline/tests').mkdir(parents=True)
    result = {'status': 'failed', 'evidence': 'docker', 'cases': [{
        'file': 'tests/test_new.py', 'name': 'test_timestamp', 'status': 'failed',
        'message': 'argument out of range', 'details': 'Controlled Docker-shaped observation'}]}
    state = {'workspace_path': str(root), 'attempts': 1, 'diff_digest': 'controlled'}
    assert 'test_preparation_context' not in failure_feedback(result, state)
    value = failure_feedback(result, state, include_preparation=True)
    assert value['test_preparation_context']['facts'][0]['test'] == 'test_timestamp'
