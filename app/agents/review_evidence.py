"""Compact, source-bound review evidence. Coverage claims remain model judgments."""
import json
import re

from app.agents.feedback import compact_test_evidence
from app.agents.quality import test_functions
from app.tools.repository import Repository, digest, is_test_file


def review_packet(repo: Repository, state: dict, max_chars: int) -> dict:
    current = state["test_results"][-1]
    if current.get("diff_digest") != state["diff_digest"] or (
        state.get("candidate_id") and current.get("candidate_id") != state["candidate_id"]
    ):
        raise ValueError("Review evidence does not match the current candidate")
    changed = state["patches"][-1].get("changed_files", [])
    terms = set(re.findall(r"[A-Za-z_]{4,}", state["issue_description"].lower()))
    cases = current.get("cases", [])
    ranked = sorted(cases, key=lambda c: (
        c.get("file") not in changed,
        -sum(t in c.get("name", "").lower() for t in terms),
        c.get("file", ""), c.get("name", "")))
    facts = []
    cache = {}
    evidence_chars = 0
    for case in ranked:
        if len(facts) == 24:
            break
        path = case.get("file", "")
        try:
            if not is_test_file(path):
                continue
            if path not in cache:
                text = repo.read_file(path, 100000)
                cache[path] = (digest(text), test_functions(text))
            fingerprint, definitions = cache[path]
        except (ValueError, OSError, SyntaxError, UnicodeError):
            continue
        name = case.get("name", "").split("[", 1)[0]
        class_name = case.get("classname", "").split(".")[-1]
        key = class_name + "::" + name if class_name + "::" + name in definitions else name
        original = definitions.get(key, [])
        matches = {key: [a[:300] for a in original[:4]]} if key in definitions else {}
        fact = {"id": f"T{len(facts) + 1:03}", "file": path,
            "name": case.get("name"), "classname": case.get("classname"), "status": case["status"],
            "source_text_sha256": fingerprint, "static_assertions": matches,
            "assertions_truncated": len(original) > 4 or any(len(a) > 300 for a in original),
            "evidence": current.get("evidence"), "image_id": current.get("image_id")}
        size = len(json.dumps(fact, ensure_ascii=False))
        if evidence_chars + size > 8000:
            break
        evidence_chars += size
        facts.append(fact)
    # Current changed files first; don't resend the locator's whole historical context.
    context = ""
    file_facts = []
    available = set(repo.list_files())
    for path in dict.fromkeys([*changed, *state["located_files"]]):
        if path not in available:
            continue
        remaining = min(max_chars // 2, 12000) - len(context) - len(path) - 70
        if remaining <= 0:
            break
        source = repo.read_file(path, 100000)
        shown = source[:min(6000, remaining)]
        ident = f"F{len(file_facts) + 1:03}"
        context += f"\n--- FILE {ident} {path} ---\n{shown}\n"
        file_facts.append({"id": ident, "path": path, "source_text_sha256": digest(source),
                           "shown_chars": len(shown), "total_chars": len(source), "truncated": shown != source})
    test_result = compact_test_evidence(current)
    test_result["stdout"] = test_result.get("stdout", "")[-2000:]
    return {"context": context, "test_result": test_result,
        "review_evidence": {"version": 1, "candidate_id": state.get("candidate_id"),
            "diff_digest": state["diff_digest"], "test_facts": facts, "file_facts": file_facts,
            "test_cases_total": len(cases), "test_cases_not_shown": len(cases) - len(facts),
            "runner_cases_truncated": current.get("cases_truncated", False),
            "interpretation": "Facts bind current test identities, status and statically extracted assertions to source text. They are NOT proof of arbitrary requirements. Omitted tests/context mean unknown, not absence or no coverage. Cite Txxx/Fxxx identities where relevant; do not invent them."}}


def cited_ids(checks: list) -> list[str]:
    # Extraction only: callers compare against the packet's IDs, never execute evidence text.
    return list(dict.fromkeys(ident for check in checks
        for ident in re.findall(r"\b[TF]\d{3}\b", check.evidence)))
