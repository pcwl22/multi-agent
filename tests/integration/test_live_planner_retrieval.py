from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from app.agents.model import MockModel
from app.config.settings import Settings
from app.graph.workflow import build_graph
from app.models.schemas import Plan
from tests.integration.test_mvp import EvidenceDouble, initial


class ProsePlanner(MockModel):
    def generate(self, schema, payload):
        value, usage = super().generate(schema, payload)
        if schema is Plan:
            value.search_strategy = [
                "Inspect the token validation and error handling logic in "
                "auth.py to locate the authenticate symbol and expired branch."
            ]
        return value, usage


def test_prose_strategy_uses_keywords_and_suspected_module_before_fallback(tmp_path: Path):
    state = initial(tmp_path)
    for i in range(30):
        (Path(state["workspace_path"]) / f"00_irrelevant_{i:02}.py").write_text(
            f"unrelated_value = {i}\n", encoding="utf-8"
        )
    graph = build_graph(Settings(), ProsePlanner(), EvidenceDouble(), InMemorySaver())
    result = graph.invoke(state, {"configurable": {"thread_id": state["thread_id"]}})
    assert result["execution_status"] == "awaiting_approval"
    assert result["located_files"][0] == "auth.py"
    assert any(item.get("symbol") == "authenticate" for item in result["retrieval_history"])
    assert all(
        len(item["keyword"]) <= 200
        for item in result["retrieval_history"]
        if item["tool"] == "search_code"
    )
