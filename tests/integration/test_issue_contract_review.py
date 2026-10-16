from langgraph.checkpoint.memory import InMemorySaver

from app.agents.model import MockModel
from app.config.settings import Settings
from app.graph.workflow import build_graph
from app.models.schemas import ContractCheck, Review
from tests.integration.test_mvp import EvidenceDouble, initial


class ContractReviewer(MockModel):
    def __init__(self):
        self.payloads = []

    def generate(self, schema, payload):
        value, usage = super().generate(schema, payload)
        if schema is Review:
            self.payloads.append(payload)
            value.approved = True
            value.contract_checks = [ContractCheck(
                requirement="The original example's input type must be covered",
                satisfied=False,
                evidence="The added test substitutes a different type",
            )]
        return value, usage


def test_failed_contract_overrides_passing_tests_and_approval_flag(tmp_path):
    state = initial(tmp_path)
    model = ContractReviewer()
    graph = build_graph(Settings(max_retries=0), model, EvidenceDouble(), InMemorySaver())
    result = graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    assert result["execution_status"] == "failed"
    assert result["error"] == "Review retry budget exhausted"
    assert not result["review_results"][-1]["approved"]
    payload = model.payloads[0]
    assert payload["issue_description"] == state["issue_description"]
    assert "--- FILE auth.py ---" in payload["context"]
    assert "status_code=401" in payload["context"]
    assert "def test_" in payload["context"]
    assert payload["test_result"]["evidence"] == "test_double"
