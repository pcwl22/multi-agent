from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.model import MockModel
from app.config.settings import Settings
from app.graph.workflow import build_graph
from app.models.schemas import Edit, Patch
from tests.integration.test_mvp import EvidenceDouble, initial


class RejectedThenCorrected(MockModel):
    def __init__(self, permanent: bool = False):
        self.calls = 0
        self.permanent = permanent

    def generate(self, schema, payload):
        if schema is Patch:
            self.calls += 1
            if self.calls == 1 or self.permanent:
                return Patch(
                    rationale="Rejected immutable-test edit fixture",
                    edits=[
                        Edit(path="auth.py", old="status_code=500", new="status_code=401"),
                        Edit(path="tests/test_auth.py", old="401", new="500"),
                    ],
                ), {"calls": 0, "input_tokens": 0, "output_tokens": 0}
            assert "immutable" in payload["patch_feedback"][-1]["error"]
            assert "status_code=500" in payload["context"]
        return super().generate(schema, payload)


def test_validation_rejection_feedback_retries_without_running_unapplied_patch(tmp_path: Path):
    state = initial(tmp_path)
    model = RejectedThenCorrected()
    graph = build_graph(Settings(), model, EvidenceDouble(), InMemorySaver())
    result = graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    assert result["execution_status"] == "awaiting_approval"
    assert result["attempts"] == 2 and result["retry_count"] == 1
    assert [patch["applied"] for patch in result["patches"]] == [False, True]
    assert len(result["test_results"]) == 1 and result["test_results"][0]["attempt"] == 2
    baseline = Path(state["workspace_path"]).parent / "baseline/tests/test_auth.py"
    assert (
        baseline.read_bytes() == (Path(state["workspace_path"]) / "tests/test_auth.py").read_bytes()
    )


def test_repeated_rejection_exhausts_the_shared_retry_budget(tmp_path: Path):
    state = initial(tmp_path)
    model = RejectedThenCorrected(permanent=True)
    graph = build_graph(Settings(max_retries=1), model, EvidenceDouble(), InMemorySaver())
    result = graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    assert result["execution_status"] == "failed"
    assert result["attempts"] == 2 and result["retry_count"] == 1 and model.calls == 2
    assert result["test_results"] == []
    assert "Patch retry budget exhausted" in result["error"]
