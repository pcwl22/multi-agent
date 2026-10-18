import logging
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.contracts import literal_input_examples, validate_literal_inputs
from app.agents.feedback import (
    compact_regression_evidence,
    compact_test_evidence,
    failure_feedback,
)
from app.agents.model import Model, ModelFailure
from app.agents.scope import repository_path_scope
from app.config.settings import Settings
from app.models.schemas import AgentState, Patch, Plan, Review
from app.services.attempts import (
    candidate_tags,
    prepare_candidate,
    save_candidate,
    validate_isolated,
)
from app.services.regressions import regression_witness
from app.tools.repository import Repository, diff_repositories, digest, is_test_file, keywords

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
                        failure = exc.stats.get("failure")
                        if failure:
                            retryable = failure["retryable"] and (
                                state.get("provider_retry_count", 0) < settings.max_retries
                            )
                            failed["failure"] = {
                                **failure,
                                "node": name,
                                "retryable": retryable,
                                "retry_at": time.time() + failure["retry_after_seconds"],
                                "budget_exhausted": failure["retryable"] and not retryable,
                            }
                            if retryable:
                                failed["execution_status"] = "retryable"
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
        if settings.model_path_scope:
            payload = {**payload, "repository_path_scope": repository_path_scope(
                Repository(state["workspace_path"]), settings.github_repository_subdirectory,
            )}
        value, stats = model.generate(schema, payload)
        return value, {
            **counters(state, stats),
            "execution_history": [event("model", schema=schema.__name__, **stats)],
        }

    def supervisor(state: AgentState):
        retry_node = "prepare_attempt" if state.get("retry_workspace_policy") == "isolated" else "coder"
        if state["execution_status"] in {"failed", "retryable", "blocked", "approved", "rejected"}:
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
                return {"next_node": retry_node, "retry_count": state["retry_count"] + 1}
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
                return {"next_node": retry_node, "retry_count": state["retry_count"] + 1}
            return {
                "next_node": END,
                "execution_status": "failed",
                "error": "Test retry budget exhausted",
            }
        if state["mode"] == "multi_full":
            witnesses = state.get("regression_results", [])
            if not witnesses or witnesses[-1]["attempt"] != state["attempts"]:
                return {"next_node": "regression"}
            reviews = state["review_results"]
            if not reviews or reviews[-1]["attempt"] != state["attempts"]:
                return {"next_node": "reviewer"}
            if not reviews[-1]["approved"]:
                if state["retry_count"] < settings.max_retries:
                    return {"next_node": retry_node, "retry_count": state["retry_count"] + 1}
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
        available = set(repo.list_files())
        paths = [p for p in dict.fromkeys([
            *state["located_files"],
            *(p for patch in state["patches"] for p in patch.get("changed_files", [])),
        ]) if p in available]
        existing_tests = [p for p in repo.list_files() if p.endswith(".py") and is_test_file(p)]
        for path in paths:
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
                "tests": [compact_test_evidence(t) for t in state["test_results"][-1:]],
                "failure_diagnostics": state.get("repair_feedback", [])[-2:],
                "reviews": state["review_results"][-1:],
                "patch_feedback": state.get("patch_feedback", [])[-1:],
                "literal_input_examples": literal_input_examples(state["issue_description"]),
                "existing_test_paths": existing_tests,
                "retry_workspace_policy": state.get("retry_workspace_policy", "preserve"),
                "previous_candidate_diff": state.get("previous_candidate_diff", "")[:60000],
                "candidate_instructions": (
                    "This workspace is a fresh ORIGINAL baseline copy. Return the COMPLETE "
                    "fix plus correct NEW tests against the displayed original context. "
                    "Previous candidate diff and test failures are archived evidence, not "
                    "files in this workspace. Original tests remain immutable. You may reuse "
                    "a test filename absent from existing_test_paths; older directories stay unchanged."
                    if state.get("retry_workspace_policy") == "isolated" else "Continue in current workspace."
                ),
            },
            state,
        )
        try:
            validate_literal_inputs(
                state["issue_description"], patch,
                {p: repo.read_file(p, 100000) for p in existing_tests}
                if literal_input_examples(state["issue_description"]) else None,
            )
            changed = repo.apply(patch)
        except (ValueError, SyntaxError) as exc:
            # Validation is completed before any file is written; rejected edits are safe to retry.
            attempt = state["attempts"] + 1
            diff = diff_repositories(Path(state["workspace_path"]).parent / "baseline", repo.root)
            return {
                "patches": [{**patch.model_dump(), "changed_files": [], "applied": False,
                             **candidate_tags(state)}],
                "patch_feedback": [{"attempt": attempt, "error": str(exc)[:2000],
                                    **candidate_tags(state)}],
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
            "patches": [{**patch.model_dump(), "changed_files": changed, "applied": True,
                         **candidate_tags(state)}],
            "attempts": state["attempts"] + 1,
            "diff": diff,
            "diff_digest": digest(diff),
            "context": context,
            **usage,
        }

    @guarded("test")
    def test(state):
        validate_isolated(state)
        result = runner.run(Path(state["workspace_path"]))
        value = result.model_dump()
        feedback = []
        if result.status == "failed":
            feedback = [{**failure_feedback(value, state), **candidate_tags(state)}]
        return {"test_results": [{**value, "attempt": state["attempts"],
                                  "diff_digest": state["diff_digest"], **candidate_tags(state)}],
                "repair_feedback": feedback}

    @guarded("prepare_attempt")
    def prepare_attempt(state):
        validate_isolated(state)
        old_workspace = Path(state["workspace_path"])
        actual = diff_repositories(old_workspace.parent / "baseline", old_workspace)
        if digest(actual) != (state["diff_digest"] or digest("")):
            raise ValueError("Workspace changed outside the recorded repair")
        archived = save_candidate(state)
        candidate = prepare_candidate(Path(state["task_path"]), state["attempts"] + 1,
                                      state["baseline_manifest"])
        return {**candidate, "attempt_history": [archived],
                "previous_candidate_diff": state["diff"], "diff": "", "diff_digest": digest(""),
                "approval_status": "pending", "approved_candidate_id": None,
                "execution_status": "running"}

    @guarded("regression")
    def regression(state):
        validate_isolated(state)
        return {"regression_results": [{**regression_witness(state, runner),
                 "attempt": state["attempts"], "diff_digest": state["diff_digest"],
                 **candidate_tags(state)}]}

    @guarded("reviewer")
    def reviewer(state):
        repo = Repository(state["workspace_path"])
        context = ""
        available = set(repo.list_files())
        paths = [p for p in dict.fromkeys([
            *state["located_files"],
            *(p for patch in state["patches"] for p in patch.get("changed_files", [])),
        ]) if p in available]
        for path in paths:
            budget = settings.context_chars - len(context) - len(path) - 30
            if budget <= 0:
                break
            context += f"\n--- FILE {path} ---\n{repo.read_file(path, min(12000, budget))}\n"
        review, usage = generate(
            Review,
            {
                "issue_description": state["issue_description"],
                "plan": state["plan"],
                "diff": state["diff"][:60000],
                "test_result": compact_test_evidence(state["test_results"][-1]),
                "context": context,
                "contract_tests": state["patches"][-1].get("contract_tests", []),
                "regression_evidence": [compact_regression_evidence(r) for r in
                                        state.get("regression_results", [])[-1:]],
            },
            state,
        )
        # Explicitly failed contracts override an inconsistent approval flag.
        if any(not check.satisfied for check in review.contract_checks):
            review.approved = False
        return {"review_results": [{**review.model_dump(), "attempt": state["attempts"],
                                    **candidate_tags(state)}], **usage}

    # interrupt raises a BaseException; do not catch or hide it in the guard.
    def human(state):
        decision = interrupt(
            {
                "task_id": state["task_id"],
                "diff_digest": state["diff_digest"],
                "message": "Approve or reject this exact diff",
                **candidate_tags(state),
            }
        )
        if not isinstance(decision, dict) or decision.get("diff_digest") != state["diff_digest"]:
            raise ValueError("Approval does not match current diff")
        if state.get("retry_workspace_policy") == "isolated" and (
            decision.get("candidate_id") != state["candidate_id"]
        ):
            raise ValueError("Approval does not match current candidate")
        approved = decision.get("approved") is True
        return {
            "approval_status": "approved" if approved else "rejected",
            "execution_status": "approved" if approved else "rejected",
            "execution_history": [event("human", approved=approved)],
            "approved_candidate_id": state.get("candidate_id") if approved else None,
        }

    graph = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("prepare_attempt", prepare_attempt)
    graph.add_conditional_edges(
        "prepare_attempt",
        lambda state: "coder" if state["execution_status"] == "running" else "supervisor",
        {"coder": "coder", "supervisor": "supervisor"},
    )
    for name, fn in [
        ("planner", planner),
        ("locator", locator),
        ("coder", coder),
        ("test", test),
        ("regression", regression),
        ("reviewer", reviewer),
        ("human", human),
    ]:
        graph.add_node(name, fn)
        graph.add_edge(name, "supervisor")
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda s: s["next_node"],
        {n: n for n in ["planner", "locator", "coder", "test", "reviewer", "human", "prepare_attempt", "regression", END]},
    )
    return graph.compile(checkpointer=checkpointer)
