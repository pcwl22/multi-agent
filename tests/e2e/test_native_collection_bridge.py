"""Controlled upstream-shaped fixtures executed exclusively in actual Docker."""
import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.evaluation.native_collection import native_adapter
from app.sandbox.runner import DockerRunner

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get('REPOPILOT_RUN_DOCKER_TESTS') != '1', reason='Docker tests are opt-in')]


def repository(root: Path, mode: str) -> Path:
    (root / 'tests').mkdir(parents=True)
    (root / 'sample.py').write_text('def twice():\n    """\n    >>> twice()\n    2\n    """\n    return ' + ('3' if mode == 'doctest-fail' else '2') + '\n', encoding='utf-8')
    source = '''import doctest
import unittest
import sample

class Original(unittest.TestCase):
    starts = 0
    @classmethod
    def setUpClass(cls):
        cls.starts += 1
        assert cls.starts == 1, 'Class fixture must run exactly once'
    def test_one(self):
        self.assertTrue(True)
    def test_two(self):
        self.assertEqual(self.starts, 1)

def load_tests(loader, tests, pattern):
    tests.addTests(doctest.DocTestSuite(sample))
    return tests
'''
    if mode == 'replace':
        source = source.replace('self.assertTrue(True)', 'self.fail("Must be removed by load_tests")')
        source = source.replace('tests.addTests(doctest.DocTestSuite(sample))\n    return tests', 'return doctest.DocTestSuite(sample)')
    if mode == 'fixture-error':
        source = source.replace("cls.starts += 1", "raise RuntimeError('Controlled fixture error')")
    if mode == 'subtest-fail':
        source = source.replace('self.assertTrue(True)', 'with self.subTest(value=1):\n            self.assertEqual(1, 2)')
    if mode == 'skip-class':
        source = source.replace("cls.starts += 1", "raise unittest.SkipTest('Controlled class skip')")
    (root / 'tests.py').write_text(source, encoding='utf-8')
    (root / 'tests/test_original_collection.py').write_text(native_adapter('tests.py'), encoding='utf-8')
    return root


@pytest.mark.parametrize('mode,passed,failed,skipped', [
    ('good', 4, 0, 0), ('doctest-fail', 3, 1, 0), ('replace', 2, 0, 0),
    ('fixture-error', 1, 3, 0), ('subtest-fail', 3, 1, 0), ('skip-class', 2, 0, 2),
])
def test_load_tests_doctests_native_fixtures_and_outcomes(tmp_path, mode, passed, failed, skipped):
    root = repository(tmp_path / 'repository', mode)
    before = (root / 'tests.py').read_bytes()
    result = DockerRunner(Settings(_env_file=None, test_timeout=30)).run(root)
    assert result.evidence == 'docker' and result.image_id
    assert (result.passed, result.failed, result.skipped) == (passed, failed, skipped), result.model_dump()
    assert result.status == ('failed' if failed else 'passed')
    assert (root / 'tests.py').read_bytes() == before
    assert any('sample.twice' in case.name for case in result.cases)
