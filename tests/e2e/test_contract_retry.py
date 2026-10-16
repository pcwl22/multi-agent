"""Explicit fixture + real Docker; proves reuse of immutable prior-attempt tests."""

import os
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.evaluation.runner import holdout_workspace
from app.models.schemas import Edit, Patch, TaskRequest
from app.sandbox.runner import DockerRunner
from app.services.tasks import TaskService

pytestmark = [pytest.mark.docker, pytest.mark.skipif(
    os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1", reason="Docker tests are opt-in"
)]


class SourceOnlyRetryFixture:
    def __init__(self):
        self.payloads = []

    def generate(self, schema, payload):
        assert schema is Patch
        self.payloads.append(payload)
        if len(self.payloads) == 1:
            edits = [
                Edit(path="pagination.py", old="start = page * page_size",
                     new="start = (page - 1) * page_size"),
                Edit(path="tests/test_literal_example.py", old="", new=(
                    "from pagination import paginate\n\n"
                    "def test_literal_example():\n"
                    "    assert paginate(range(1,8), 2, 2) == [3,4]\n"
                )),
            ]
        else:
            assert "tests/test_literal_example.py" in payload["existing_test_paths"]
            assert "def test_literal_example" in payload["context"]
            assert payload["tests"][-1]["failed"] > 0
            edits = [Edit(path="pagination.py",
                          old="return items[start : start + page_size]",
                          new="return list(items[start : start + page_size])")]
        return Patch(rationale="Explicit two-attempt fixture, not an LLM result", edits=edits), {
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "adapter": "test-fixture",
        }


def test_correct_existing_literal_test_allows_source_only_retry(tmp_path):
    corpus = Path(__file__).parents[2] / "app/evaluation/expanded"
    source = corpus / "repos/one-based-page"
    model = SourceOnlyRetryFixture()
    settings = Settings(repository_root=source, data_dir=tmp_path / "data", max_retries=1)
    runner = DockerRunner(settings)
    service = TaskService(settings, model=model, runner=runner)
    try:
        task = service.create(TaskRequest(repository_path=str(source), mode="single",
                                          issue_description="For range(1,8), page 2 size 2 must return [3,4]."))
        state = service.run(task["task_id"])
        assert state["execution_status"] == "awaiting_approval"
        assert state["attempts"] == 2 and state["retry_count"] == 1
        assert [test["status"] for test in state["test_results"]] == ["failed", "passed"]
        assert state["patch_feedback"] == []
        new_test = Path(state["workspace_path"]) / "tests/test_literal_example.py"
        assert new_test.read_text(encoding="utf8") == state["patches"][0]["edits"][1]["new"]
        holdout = tmp_path / "holdout"
        holdout_workspace(Path(state["workspace_path"]), holdout,
                          corpus / "acceptance/test_pagination_sequence_acceptance.py")
        accepted = runner.run(holdout)
        assert accepted.status == "passed" and accepted.passed == 10
    finally:
        service.close()
