import logging
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.api_context import contract_api_context
from app.agents.contracts import literal_input_examples, validate_literal_inputs
from app.agents.feedback import (
    compact_regression_evidence,
    compact_test_evidence,
    failure_feedback,
)
from app.agents.model import Model, ModelFailure
from app.agents.normalization import normalize_candidate
from app.agents.quality import (
    CandidateQualityError,
    failed_assertions,
    protocol,
    validate_candidate,
)
from app.agents.review_evidence import cited_ids, review_packet
from app.agents.scope import repository_path_scope
from app.config.settings import Settings
from app.models.schemas import AgentState, Patch, Plan, Review
from app.services.attempts import (
    candidate_tags,
    prepare_candidate,
    save_candidate,
    validate_isolated,
)
from app.services.budgets import BudgetExceeded, budget_scope, current_budget, for_state, stopped
from app.services.provider_circuit import ProviderCircuitOpen
from app.services.regressions import regression_witness
from app.services.transactions import apply_transaction
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
                result = {}
                budget = None
                try:
                    budget = for_state(state)
                    with budget_scope(budget):
                        if budget:
                            budget.check()
                        result = fn(state)
                        if budget:
                            budget.check()
                    result.setdefault("execution_history", []).append(
                        event(name, duration_seconds=time.monotonic() - started))
                    return result
                except Exception as exc:
                    failed = {**result, "execution_status": "failed", "error": str(exc)[:2000]}
                    history = [*result.get("execution_history", []), event(
                        name, error=str(exc)[:2000], duration_seconds=time.monotonic() - started)]
                    if isinstance(exc, (ModelFailure, BudgetExceeded, ProviderCircuitOpen)) and hasattr(exc, "stats"):
                        failed.update(counters(state, exc.stats))
                        history.append(event("model", **exc.stats))
                        failure = exc.stats.get("failure")
                        if failure:
                            retryable = failure["retryable"] and (
                                state.get("provider_retry_count", 0) < settings.max_retries)
                            failed["failure"] = {**failure, "node": name, "retryable": retryable,
                                "retry_at": time.time() + failure["retry_after_seconds"],
                                "budget_exhausted": failure["retryable"] and not retryable}
                            if retryable:
                                failed["execution_status"] = "retryable"
                    if isinstance(exc, ProviderCircuitOpen):
                        failed.update(execution_status="batch_paused", circuit_failure=exc.snapshot, next_node="__end__")
                    if not isinstance(exc, BudgetExceeded) and budget:
                        try:
                            budget.check()
                        except BudgetExceeded as exhausted:
                            exc = exhausted
                    if isinstance(exc, BudgetExceeded):
                        failed.update(stopped(exc))
                    failed["execution_history"] = history
                    logger.info("node_stopped", extra={"task_id": state["task_id"], "node": name})
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
        budget = current_budget()
        reservation = None
        if budget and not getattr(model, "manages_task_budget", False):
            reservation = budget.reserve("model_requests")
        try:
            value, stats = model.generate(schema, payload)
        except Exception as exc:
            if reservation is not None:
                budget.complete(reservation, getattr(exc, "stats", {"usage_complete": False}))
            raise
        if reservation is not None:
            budget.complete(reservation, stats)
        if budget:
            try:
                budget.check()
            except BudgetExceeded as exc:
                exc.stats = stats
                raise
        return value, {
            **counters(state, stats),
            "execution_history": [event("model", schema=schema.__name__, **stats)],
        }

    def supervisor(state: AgentState):
        if state["execution_status"] in {"budget_exhausted", "batch_paused"}:
            return {"next_node": END}
        if state["execution_status"] not in {"approved", "rejected", "failed"}:
            try:
                if (budget := for_state(state)) is not None:
                    budget.check()
            except BudgetExceeded as exc:
                return stopped(exc)
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
        if state.get("repair_quality_version") in {1, 2} or state["mode"] == "multi_full":
            witnesses = state.get("regression_results", [])
            if not witnesses or witnesses[-1]["attempt"] != state["attempts"]:
                return {"next_node": "regression"}
        if state["mode"] == "multi_full":
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
        api_context = {}
        if state.get("repair_quality_version") == 2:
            context, api_context = contract_api_context(repo, paths, state["issue_description"], settings.context_chars)
        patch, usage = generate(
            Patch,
            {
                **({"candidate_protocol": protocol(state["repair_quality_version"]),
                    **({"contract_api_context": api_context} if api_context else {}),
                    "original_failure_assertions": failed_assertions(repo, state.get("repair_feedback", []))}
                   if state.get("repair_quality_version") in {1, 2} else {}),
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
            if state.get("repair_quality_version") in {1, 2}:
                if state.get("repair_quality_version") == 2:
                    patch, quality = normalize_candidate(repo, patch)
                else:
                    quality = validate_candidate(repo, patch)
                if api_context:
                    usage["execution_history"].append(event("contract_api_context", **api_context, **candidate_tags(state)))
                usage["execution_history"].append(event("candidate_quality", **quality, **candidate_tags(state)))
            validate_literal_inputs(
                state["issue_description"], patch,
                {p: repo.read_file(p, 100000) for p in existing_tests}
                if literal_input_examples(state["issue_description"]) else None,
            )
            if state.get("patch_transaction_version") == 1:
                return apply_transaction(state, patch, usage, context)
            changed = repo.apply(patch)
        except (ValueError, SyntaxError) as exc:
            # Validation is completed before any file is written; rejected edits are safe to retry.
            attempt = state["attempts"] + 1
            diff = diff_repositories(Path(state["workspace_path"]).parent / "baseline", repo.root)
            return {
                "patches": [{**patch.model_dump(), "changed_files": [], "applied": False,
                             **candidate_tags(state)}],
                "patch_feedback": [{"attempt": attempt, "error": str(exc)[:2000],
                                    **({"diagnostics": exc.diagnostics} if isinstance(exc, CandidateQualityError) else {}),
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

    def run_sandbox(workspace):
        budget = current_budget()
        reservation = budget.reserve("sandbox_runs") if budget else None
        try:
            result = runner.run(workspace)
        finally:
            if reservation is not None:
                budget.complete(reservation)
        return result

    class BudgetRunner:
        run = staticmethod(run_sandbox)

    @guarded("test")
    def test(state):
        validate_isolated(state)
        result = run_sandbox(Path(state["workspace_path"]))
        value = result.model_dump()
        feedback = []
        if result.status == "failed":
            feedback = [{**failure_feedback(value, state, prioritize_original=state.get("repair_quality_version") in {1, 2}), **candidate_tags(state)}]
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
        witness = regression_witness(state, BudgetRunner())
        result = {"regression_results": [{**witness, "attempt": state["attempts"],
                  "diff_digest": state["diff_digest"], **candidate_tags(state)}]}
        if state.get("repair_quality_version") in {1, 2} and witness["status"] != "demonstrated":
            if witness["status"] == "unavailable":
                result.update(execution_status="blocked", error="Regression evidence unavailable; preserved without model replay")
            else:
                result["patch_feedback"] = [{"attempt": state["attempts"], **candidate_tags(state),
                    "error": "No fail-to-pass regression witness for this candidate",
                    "diagnostics": [{"code": "regression_not_demonstrated", "correction":
                        "Return a complete candidate with an issue-justified NEW test that fails on the original source and passes on the fix. Do not weaken assertions or edit original tests."}],
                    "regression_evidence": compact_regression_evidence(witness)}]
        return result

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
        packet = review_packet(repo, state, settings.context_chars) if state.get("repair_quality_version") in {1, 2} else {}
        if state.get("repair_quality_version") == 2:
            gates = [e for e in state["execution_history"] if e["node"] == "candidate_quality" and e.get("candidate_id") == state.get("candidate_id")]
            if gates:
                gate = gates[-1]
                packet["binding_provenance"] = {"origin": gate.get("binding_origin"),
                    "original_model_claims": gate.get("raw_proposal", {}).get("contract_tests", []),
                    "resolved_test_identities": gate.get("contract_tests", []),
                    "interpretation": "Derived identities are static source facts, not model claims or semantic coverage proof. Original model prose stays untrusted."}
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
                **packet,
            },
            state,
        )
        if packet:
            evidence = packet["review_evidence"]
            known = {x["id"] for x in [*evidence["test_facts"], *evidence["file_facts"]]}
            invalid = [x for x in cited_ids(review.contract_checks) if x not in known]
            if invalid:
                review.approved = False
                review.concerns.append("Unknown review evidence citations: " + ", ".join(invalid))
            usage["execution_history"].append(event("review_evidence", **{**evidence,
                "context_chars": len(packet["context"]), **candidate_tags(state)}))
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
