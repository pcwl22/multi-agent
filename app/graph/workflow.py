import logging
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.model import Model, ModelFailure
from app.config.settings import Settings
from app.models.schemas import AgentState, Patch, Plan, Review
from app.tools.repository import Repository, diff_repositories, digest, keywords

logger = logging.getLogger("repopilot.graph")


def build_graph(settings: Settings, model: Model, runner: Any, checkpointer: Any):
    def event(node: str, **details) -> dict:
        return {"node": node, "timestamp": time.time(), **details}

    def guarded(name: str):
        def decorate(fn: Callable):
            @wraps(fn)
            def call(state: AgentState):
                started = time.monotonic()
                try:
                    result = fn(state)
                    result.setdefault("execution_history", []).append(
                        event(name, duration_seconds=time.monotonic() - started)
                    )
                    logger.info("node_complete", extra={"task_id": state["task_id"], "node": name})
                    return result
                except Exception as exc:
                    logger.exception(
                        "node_failed", extra={"task_id": state["task_id"], "node": name}
                    )
                    failed = {
                        "execution_status": "failed",
                        "error": str(exc)[:2000],
                        "execution_history": [
                            event(
                                name,
                                error=str(exc)[:2000],
                                duration_seconds=time.monotonic() - started,
                            )
                        ],
                    }
                    if isinstance(exc, ModelFailure):
                        failed.update(counters(state, exc.stats))
                        failed["execution_history"].append(event("model", **exc.stats))
                    return failed

            return call

        return decorate

    def counters(state, stats):
        return {
            "model_calls": state["model_calls"] + stats["calls"],
            "input_tokens": state["input_tokens"] + stats["input_tokens"],
            "output_tokens": state["output_tokens"] + stats["output_tokens"],
            "token_usage_complete": state.get("token_usage_complete", True)
            and stats.get("usage_complete", True),
        }

    def generate(schema, payload, state):
        value, stats = model.generate(schema, payload)
        return value, {
            **counters(state, stats),
            "execution_history": [event("model", schema=schema.__name__, **stats)],
        }

    def supervisor(state: AgentState):
        if state["execution_status"] in {"failed", "blocked", "approved", "rejected"}:
            return {"next_node": END}
        if not state["plan"] and state["mode"] != "single":
            return {"next_node": "planner", "execution_status": "running"}
        if not state["context"]:
            return {"next_node": "locator", "execution_status": "running"}
        if not state["attempts"]:
            return {"next_node": "coder"}
        feedback = state.get("patch_feedback", [])
        if feedback and feedback[-1]["attempt"] == state["attempts"]:
            if state["retry_count"] < settings.max_retries:
                return {"next_node": "coder", "retry_count": state["retry_count"] + 1}
            return {
                "next_node": END,
                "execution_status": "failed",
                "error": "Patch retry budget exhausted: " + feedback[-1]["error"],
            }
        if (
            not state["test_results"]
            or state["test_results"][-1].get("attempt") != state["attempts"]
        ):
            return {"next_node": "test"}
        test = state["test_results"][-1]
        if test["status"] == "unavailable":
            return {"next_node": END, "execution_status": "blocked", "error": test["stderr"]}
        if test["status"] != "passed":
            if state["retry_count"] < settings.max_retries:
                return {"next_node": "coder", "retry_count": state["retry_count"] + 1}
            return {
                "next_node": END,
                "execution_status": "failed",
                "error": "Test retry budget exhausted",
            }
        if state["mode"] == "multi_full":
            reviews = state["review_results"]
            if not reviews or reviews[-1]["attempt"] != state["attempts"]:
                return {"next_node": "reviewer"}
            if not reviews[-1]["approved"]:
                if state["retry_count"] < settings.max_retries:
                    return {"next_node": "coder", "retry_count": state["retry_count"] + 1}
                return {
                    "next_node": END,
                    "execution_status": "failed",
                    "error": "Review retry budget exhausted",
                }
        return {"next_node": "human", "execution_status": "awaiting_approval"}

    @guarded("planner")
    def planner(state):
        plan, usage = generate(Plan, {"issue_description": state["issue_description"]}, state)
        return {"plan": plan.model_dump(), **usage}

    @guarded("locator")
    def locator(state):
        repo = Repository(state["workspace_path"])
        strategies = (
            state["plan"]["search_strategy"]
            if state["plan"]
            else keywords(state["issue_description"])
        )[:12]
        # Live planners often emit sentences; convert them to bounded literal searches.
        terms = list(
            dict.fromkeys(
                term
                for strategy in strategies
                for term in ([strategy] if strategy.isidentifier() else keywords(strategy))
            )
        )[:12]
        scores: dict[str, int] = {}
        available = set(repo.list_files())
        for hint in (state["plan"]["suspected_modules"] if state["plan"] else [])[:12]:
            path = hint.replace("\\", "/")
            if path in available:
                scores[path] = 50
        history = []
        for term in terms:
            hits = repo.search_code(term)
            history.append({"tool": "search_code", "keyword": term, "matches": len(hits)})
            for hit in hits:
                scores[hit["path"]] = scores.get(hit["path"], 0) + 1
            if term.isidentifier():
                symbols = repo.find_symbol(term)
                history.append({"tool": "find_symbol", "symbol": term, "matches": len(symbols)})
                for hit in symbols:
                    scores[hit["path"]] = scores.get(hit["path"], 0) + 5
        candidates = sorted(scores, key=lambda p: (-scores[p], p))
        if not candidates:
            candidates = repo.list_files()[:20]
        context = ""
        located = []
        for path in candidates[:12]:
            budget = settings.context_chars - len(context) - len(path) - 30
            if budget <= 0:
                break
            text = repo.read_file(path, min(12000, budget))
            context += f"\n--- FILE {path} ---\n{text}\n"
            located.append(path)
            history.append({"tool": "read_file", "path": path, "chars": len(text)})
        dependencies = repo.inspect_dependencies()
        history.append({"tool": "inspect_dependencies", "files": list(dependencies)})
        if not context.strip():
            raise ValueError("Repository contains no readable supported source files")
        return {"context": context, "located_files": located, "retrieval_history": history}

    @guarded("coder")
    def coder(state):
        # Refresh selected files after each edit so retry preconditions use current content.
        repo = Repository(state["workspace_path"])
        context = ""
        for path in state["located_files"]:
            budget = settings.context_chars - len(context) - len(path) - 30
            if budget <= 0:
                break
            context += f"\n--- FILE {path} ---\n{repo.read_file(path, min(12000, budget))}\n"
        patch, usage = generate(
            Patch,
            {
                "mode": state["mode"],
                "issue_description": state["issue_description"],
                "plan": state["plan"],
                "context": context,
                "tests": state["test_results"][-1:],
                "reviews": state["review_results"][-1:],
                "patch_feedback": state.get("patch_feedback", [])[-1:],
            },
            state,
        )
        try:
            changed = repo.apply(patch)
        except (ValueError, SyntaxError) as exc:
            # Validation is completed before any file is written; rejected edits are safe to retry.
            attempt = state["attempts"] + 1
            diff = diff_repositories(Path(state["workspace_path"]).parent / "baseline", repo.root)
            return {
                "patches": [{**patch.model_dump(), "changed_files": [], "applied": False}],
                "patch_feedback": [{"attempt": attempt, "error": str(exc)[:2000]}],
                "attempts": attempt,
                "diff": diff,
                "diff_digest": digest(diff),
                "context": context,
                **usage,
            }
        except Exception as exc:
            stats = {
                key: value
                for key, value in usage["execution_history"][0].items()
                if key not in {"node", "timestamp", "schema"}
            }
            raise ModelFailure(f"Patch rejected: {exc}", stats) from exc
        diff = diff_repositories(Path(state["workspace_path"]).parent / "baseline", repo.root)
        return {
            "patches": [{**patch.model_dump(), "changed_files": changed, "applied": True}],
            "attempts": state["attempts"] + 1,
            "diff": diff,
            "diff_digest": digest(diff),
            "context": context,
            **usage,
        }

    @guarded("test")
    def test(state):
        result = runner.run(Path(state["workspace_path"]))
        return {"test_results": [{**result.model_dump(), "attempt": state["attempts"]}]}

    @guarded("reviewer")
    def reviewer(state):
        review, usage = generate(
            Review,
            {
                "issue_description": state["issue_description"],
                "plan": state["plan"],
                "diff": state["diff"][:60000],
                "test_result": state["test_results"][-1],
            },
            state,
        )
        return {"review_results": [{**review.model_dump(), "attempt": state["attempts"]}], **usage}

    # interrupt raises a BaseException; do not catch or hide it in the guard.
    def human(state):
        decision = interrupt(
            {
                "task_id": state["task_id"],
                "diff_digest": state["diff_digest"],
                "message": "Approve or reject this exact diff",
            }
        )
        if not isinstance(decision, dict) or decision.get("diff_digest") != state["diff_digest"]:
            raise ValueError("Approval does not match current diff")
        approved = decision.get("approved") is True
        return {
            "approval_status": "approved" if approved else "rejected",
            "execution_status": "approved" if approved else "rejected",
            "execution_history": [event("human", approved=approved)],
        }

    graph = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor)
    for name, fn in [
        ("planner", planner),
        ("locator", locator),
        ("coder", coder),
        ("test", test),
        ("reviewer", reviewer),
        ("human", human),
    ]:
        graph.add_node(name, fn)
        graph.add_edge(name, "supervisor")
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda s: s["next_node"],
        {n: n for n in ["planner", "locator", "coder", "test", "reviewer", "human", END]},
    )
    return graph.compile(checkpointer=checkpointer)
