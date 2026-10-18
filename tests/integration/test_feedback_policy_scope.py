from pathlib import Path

import app.evaluation.feedback as feedback
from app.config.settings import Settings
from app.models.schemas import Edit, Patch, Plan, Review, TestResult


class TTLFixtureModel:
    """Explicit trial-controller double; no provider request or target execution."""

    def generate(self, schema, payload):
        if schema is Plan:
            value = Plan(issue_summary="TTL fixture", suspected_modules=["cache.py"],
                         search_strategy=["is_expired"], repair_steps=["fix boundary"],
                         validation_strategy=["controlled runner double"])
        elif schema is Patch:
            value = Patch(rationale="controlled TTL repair", edits=[Edit(
                path="cache.py", old="return now >= inserted_at + ttl + 101",
                new="return now >= inserted_at + ttl",
            )])
        elif schema is Review:
            value = Review(approved=True, summary="controlled review double", concerns=[])
        else:
            raise AssertionError(schema)
        return value, {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                       "adapter": "test_double"}


def test_feedback_trial_holds_retry_policy_constant_under_isolated_default(tmp_path, monkeypatch):
    selected_policies = []

    class SyntaxRunnerDouble:
        """Classifies fixture text without importing or executing target Python."""

        def __init__(self, settings):
            selected_policies.append(settings.retry_workspace_policy)

        def run(self, workspace):
            source = (Path(workspace) / "cache.py").read_text(encoding="utf-8")
            passed = "return now >= inserted_at + ttl\n" in source
            return TestResult(status="passed" if passed else "failed", exit_code=0 if passed else 1,
                              passed=int(passed), failed=int(not passed), evidence="test_double",
                              stdout="Controlled syntax-runner double; not Docker test evidence")

    monkeypatch.setattr(feedback, "create_model", lambda settings: TTLFixtureModel())
    monkeypatch.setattr(feedback, "DockerRunner", SyntaxRunnerDouble)
    settings = Settings(model_mode="live", retry_workspace_policy="isolated", _env_file=None)
    report = feedback.run_feedback_experiments(settings, tmp_path / "trial")
    assert [r["policy"] for r in report["records"]] == ["first", "always"]
    assert all(r["expected_outcome_verified"] for r in report["records"])
    assert selected_policies == ["preserve", "preserve"]
    assert report["retry_workspace_policy"] == "preserve"
    assert report["configured_retry_workspace_policy"] == "isolated"
    assert settings.retry_workspace_policy == "isolated"
    assert all(test["evidence"] == "test_double" for r in report["records"] for test in r["tests"])
