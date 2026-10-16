from app.evaluation.feedback import FaultInjectionModel
from app.models.schemas import Edit, Patch
from app.tools.repository import Repository


class CandidateModel:
    def __init__(self):
        self.calls = 0

    def generate(self, schema, payload):
        self.calls += 1
        return Patch(
            rationale="candidate",
            edits=[Edit(path="cache.py", old="return False", new="return True")],
        ), {"calls": 1, "model_reported": "test-double"}


def test_first_injection_is_explicit_and_recovery_candidate_is_unchanged(tmp_path):
    (tmp_path / "cache.py").write_text("def is_expired(*args):\n    return False\n")
    underlying = CandidateModel()
    model = FaultInjectionModel(underlying, "first")
    model.workspace = tmp_path
    injected, stats = model.generate(Patch, {})
    assert "fault_injection" in stats
    assert model.audit[-1]["injected"] is True
    Repository(tmp_path).apply(injected)
    assert "+ 101" in (tmp_path / "cache.py").read_text()
    recovered, stats = model.generate(
        Patch,
        {"tests": [dict(attempt=1, status="failed", failed=1, stdout="actual assertion log")]},
    )
    assert underlying.calls == 2
    assert recovered.rationale == "candidate" and recovered.edits[0].new == "return True"
    assert "fault_injection" not in stats
    assert model.audit[-1]["failed_test_feedback"][0]["attempt"] == 1
    assert model.audit[-1]["injected"] is False


def test_always_policy_calls_underlying_model_and_changes_every_candidate(tmp_path):
    (tmp_path / "cache.py").write_text("def is_expired(*args):\n    return False\n")
    underlying = CandidateModel()
    model = FaultInjectionModel(underlying, "always")
    model.workspace = tmp_path
    for attempt in (1, 2):
        patch, stats = model.generate(Patch, {})
        Repository(tmp_path).apply(patch)
        assert stats["fault_injection"]["patch_call"] == attempt
    assert underlying.calls == 2
    assert all(event["injected"] for event in model.audit)
