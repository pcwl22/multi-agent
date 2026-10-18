import uuid
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.model import MockModel
from app.config.settings import Settings
from app.graph.workflow import build_graph
from app.models.schemas import TestResult
from app.tools.repository import Repository, snapshot


class EvidenceDouble:
    """Route tests only. This never represents execution of repository tests."""

    def run(self, workspace):
        return TestResult(status="passed", exit_code=0, passed=1, evidence="test_double")


def initial(tmp_path, mode="multi_full"):
    repo = Repository(Path(__file__).parents[2] / "test_fixtures" / "repair_repository")
    snapshot(repo, tmp_path / "baseline")
    snapshot(repo, tmp_path / "workspace")
    return dict(
        task_id=str(uuid.uuid4()),
        thread_id=str(uuid.uuid4()),
        issue_description="expired token returns 500, expected 401",
        repository_path=str(repo.root),
        workspace_path=str(tmp_path / "workspace"),
        mode=mode,
        execution_status="queued",
        plan=None,
        located_files=[],
        context="",
        patches=[],
        test_results=[],
        review_results=[],
        retry_count=0,
        attempts=0,
        approval_status="pending",
        execution_history=[],
        retrieval_history=[],
        model_calls=0,
        input_tokens=0,
        output_tokens=0,
        error=None,
        next_node="",
        diff="",
        diff_digest="",
    )


def test_mvp_reaches_approval(tmp_path):
    state = initial(tmp_path)
    graph = build_graph(Settings(), MockModel(), EvidenceDouble(), InMemorySaver())
    result = graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    assert result["execution_status"] == "awaiting_approval"
    assert result["__interrupt__"]
    assert result["attempts"] == 1
    assert result["test_results"][-1]["evidence"] == "test_double"
    assert result["review_results"][-1]["approved"]
