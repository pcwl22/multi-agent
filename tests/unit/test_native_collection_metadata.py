"""Generator/metadata controls only; never imports target test modules."""
import ast
import json

import pytest

from app.evaluation.historical import prepare, verify
from app.evaluation.native_collection import native_adapter
from tests.unit.test_historical_evaluation import controlled_git_case


def test_native_bridge_is_opt_in_and_produces_a_new_frozen_corpus(tmp_path):
    repo, spec, case = controlled_git_case(tmp_path)
    case['collection_entrypoint'] = 'tests.py'
    spec.write_text(json.dumps([case]), encoding='utf-8')
    legacy = tmp_path / 'legacy'
    native = tmp_path / 'native'
    legacy_digest = prepare(repo.parent, legacy, spec)
    native_digest = prepare(repo.parent, native, spec, collection_protocol='native-v2')
    assert legacy_digest != native_digest
    assert verify(legacy, legacy_digest)['version'] == 1
    lock = verify(native, native_digest)
    assert lock['version'] == 2 and lock['collection_protocol'] == 'unittest-load-tests-v2'
    source = native / 'sources/controlled-fixture/tests/test_original_collection.py'
    assert source.read_text(encoding='utf-8') == native_adapter('tests.py')
    assert (legacy / 'sources/controlled-fixture/tests/test_original.py').read_bytes() == (
        native / 'sources/controlled-fixture/tests/test_original.py').read_bytes()


def test_adapter_validates_entrypoint_and_contains_no_host_execution():
    with pytest.raises(ValueError):
        native_adapter('../secret.py')
    tree = ast.parse(native_adapter('test.py'))
    assert isinstance(tree, ast.Module)
    assert 'loadTestsFromModule' in native_adapter('test.py')
    assert 'subprocess' not in native_adapter('test.py')
