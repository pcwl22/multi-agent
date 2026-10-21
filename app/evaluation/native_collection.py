"""Generate a pytest bridge; target imports and test execution happen in Docker.

The native unittest suite runs once, in its native order with class/module
fixtures intact. Pytest items report cached per-test outcomes. An integrity item
reports loader/fixture errors and exposes the native inventory in JUnit.
"""
import textwrap


def native_adapter(entrypoint: str) -> str:
    if entrypoint not in {'test.py', 'tests.py'}:
        raise ValueError('Unsupported native unittest entrypoint')
    return textwrap.dedent('''\
        import importlib.util
        import json
        import sys
        import unittest
        from pathlib import Path

        import pytest

        _entry = Path(__file__).resolve().parents[1] / ENTRYPOINT
        _spec = importlib.util.spec_from_file_location('_repopilot_native', _entry)
        _module = importlib.util.module_from_spec(_spec)
        sys.modules[_spec.name] = _module
        _spec.loader.exec_module(_module)
        _loader = unittest.TestLoader()
        _suite = _loader.loadTestsFromModule(_module)

        def _flatten(suite):
            for test in suite:
                if isinstance(test, unittest.TestSuite):
                    yield from _flatten(test)
                else:
                    yield test.id()

        _ids = list(_flatten(_suite))
        if not _ids or len(_ids) != len(set(_ids)):
            raise ValueError('Native collection is empty or contains ambiguous duplicate IDs')

        class _Result(unittest.TestResult):
            def __init__(self):
                super().__init__()
                self.outcomes = {}
                self.fixture_errors = []
                self.fixture_skips = []

            def startTest(self, test):
                super().startTest(test)
                self.outcomes[test.id()] = ('passed', '')

            def addFailure(self, test, err):
                super().addFailure(test, err)
                self.outcomes[test.id()] = ('failed', self._exc_info_to_string(err, test))

            def addError(self, test, err):
                super().addError(test, err)
                message = self._exc_info_to_string(err, test)
                if test.id() in _ids:
                    self.outcomes[test.id()] = ('failed', message)
                else:
                    self.fixture_errors.append(message)

            def addSkip(self, test, reason):
                super().addSkip(test, reason)
                if test.id() in _ids:
                    self.outcomes[test.id()] = ('skipped', reason)
                else:
                    self.fixture_skips.append(reason)

            def addExpectedFailure(self, test, err):
                super().addExpectedFailure(test, err)
                self.outcomes[test.id()] = ('xfailed', self._exc_info_to_string(err, test))

            def addUnexpectedSuccess(self, test):
                super().addUnexpectedSuccess(test)
                self.outcomes[test.id()] = ('failed', 'Native unexpected success')

            def addSubTest(self, test, subtest, err):
                super().addSubTest(test, subtest, err)
                if err is not None:
                    self.outcomes[test.id()] = ('failed', self._exc_info_to_string(err, test))

        _result = None

        def _execute():
            global _result
            if _result is None:
                _result = _Result()
                _result.startTestRun()
                try:
                    _suite.run(_result)
                finally:
                    _result.stopTestRun()
            return _result

        @pytest.mark.parametrize('native_id', _ids, ids=_ids)
        def test_original_collection(native_id):
            result = _execute()
            status, detail = result.outcomes.get(native_id, ('missing', 'Native test did not finish'))
            if status == 'skipped' or (status == 'missing' and result.fixture_skips and not result.fixture_errors):
                pytest.skip(detail if status == 'skipped' else '; '.join(result.fixture_skips))
            if status == 'xfailed':
                pytest.xfail(detail[-6000:])
            if status != 'passed':
                pytest.fail(detail[-6000:], pytrace=False)

        def test_native_collection_integrity(record_property):
            result = _execute()
            record_property('native_test_ids', json.dumps(_ids))
            record_property('native_tests_run', result.testsRun)
            record_property('native_collection_protocol', 'unittest-load-tests-v2')
            assert not _loader.errors, str(_loader.errors)[-6000:]
            assert not result.fixture_errors, str(result.fixture_errors)[-6000:]
            missing = set(_ids) - result.outcomes.keys()
            assert not missing or result.fixture_skips, str(sorted(missing))[-6000:]
        ''').replace('ENTRYPOINT', repr(entrypoint))
