from app.services.regressions import regression_witness


def test_test_double_or_missing_cases_cannot_be_presented_as_baseline_proof():
    class NoExecution:
        def run(self, path):
            raise AssertionError('No Docker run should be requested with missing evidence')
    for test in [dict(evidence='test_double'), dict(evidence='docker', cases=[])]:
        witness = regression_witness(dict(test_results=[test]), NoExecution())
        assert witness['status'] == 'unavailable' and witness['baseline_result'] is None
