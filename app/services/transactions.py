"""Opt-in patch journal. Recovery requires an explicit digest-bound local action.

No target code is imported or executed. File replacement and checkpoints remain
separate; a journal bridges process loss, not arbitrary power loss or host races.
"""
import ast
import base64
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from app.models.schemas import Patch, StrictModel
from app.services.attempts import controlled_path, file_manifest, manifest_digest
from app.tools.repository import Repository, diff_repositories, digest, is_test_file

logger = logging.getLogger(__name__)
MAX_JOURNAL_BYTES = 8000000


class JournalEdit(StrictModel):
    path: str
    before: str | None = Field(default=None, max_length=140000)
    after: str = Field(max_length=140000)


class PatchJournal(StrictModel):
    version: Literal[1] = 1
    transaction_id: str
    task_id: str
    candidate_id: str | None
    workspace_path: str
    attempt_before: int = Field(ge=0, le=5)
    patch_count_before: int = Field(ge=0, le=6)
    history_count_before: int = Field(ge=0)
    counters_before: list[int] = Field(min_length=3, max_length=3)
    pre_diff_digest: str
    baseline_digest: str
    before_manifest: dict[str, str]
    edits: list[JournalEdit] = Field(min_length=1, max_length=8)
    result: dict
    status: Literal["prepared", "written", "acknowledged"] = "prepared"


class PatchRecoveryDecision(StrictModel):
    journal_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def journal_checkpoint(point: str, journal: PatchJournal) -> None:
    """Observation hook; trusted tests inject hard process loss here."""
    logger.info("patch_journal", extra={"point": point, "transaction_id": journal.transaction_id})


def _paths(state: dict) -> tuple[Path, Path]:
    root = Path(state["task_path"]).resolve(strict=True)
    relative = (f"attempts/{state['candidate_number']:04}/workspace"
                if state.get("retry_workspace_policy") == "isolated" else "workspace")
    workspace = controlled_path(root, relative, directory=True)
    if workspace.resolve(strict=True) != Path(state["workspace_path"]).resolve(strict=True):
        raise ValueError("Patch transaction workspace identity changed")
    return root, workspace


def _save(root: Path, path: Path, journal: PatchJournal) -> None:
    raw = journal.model_dump_json().encode()
    # Leave room for the completed diff before changing any workspace files.
    budget = MAX_JOURNAL_BYTES // 2 if journal.status == "prepared" else MAX_JOURNAL_BYTES
    if len(raw) > budget:
        raise ValueError("Patch journal exceeds write budget")
    path = controlled_path(root, path.relative_to(root).as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = controlled_path(root, f"patch-journal/{uuid4()}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _load(root: Path, path: Path) -> tuple[PatchJournal, str]:
    checked = controlled_path(root, path.relative_to(root).as_posix())
    if checked.stat().st_size > MAX_JOURNAL_BYTES:
        raise ValueError("Patch journal exceeds read budget")
    raw = checked.read_bytes()
    return PatchJournal.model_validate_json(raw), hashlib.sha256(raw).hexdigest()


def _recorded(state: dict, journal: PatchJournal) -> bool:
    expected = journal.result["patches"][0]
    recorded = [p for p in state["patches"]
                if p.get("transaction_id") == journal.transaction_id]
    if recorded and (recorded != [expected] or state["attempts"] <= journal.attempt_before):
        raise ValueError("Checkpoint transaction identity differs from journal")
    return bool(recorded)


def pending(state: dict, *, acknowledge: bool = False) -> list[tuple[Path, PatchJournal, str]]:
    if state.get("patch_transaction_version") != 1:
        return []
    root, _ = _paths(state)
    folder = controlled_path(root, "patch-journal", directory=True)
    if not folder.exists():
        return []
    paths = sorted(folder.glob("*.json"))
    if len(paths) > 6:
        raise ValueError("Too many patch journals")
    result = []
    for path in paths:
        journal, sha = _load(root, path)
        if journal.task_id != state["task_id"]:
            raise ValueError("Patch journal task identity changed")
        if _recorded(state, journal):
            if acknowledge and journal.status != "acknowledged":
                journal_checkpoint("checkpointed", journal)
                journal.status = "acknowledged"
                _save(root, path, journal)
            continue
        if journal.status == "acknowledged":
            raise ValueError("Acknowledged patch missing from checkpoint")
        result.append((path, journal, sha))
    return result


def _decode(value: str | None) -> bytes | None:
    return base64.b64decode(value, validate=True) if value is not None else None


def _verify(state: dict, journal: PatchJournal) -> Path:
    _, workspace = _paths(state)
    if journal.workspace_path != str(workspace) or journal.candidate_id != state.get("candidate_id"):
        raise ValueError("Patch transaction candidate identity changed")
    baseline = file_manifest(workspace.parent / "baseline")
    if manifest_digest(baseline) != journal.baseline_digest or (
        state.get("creation_manifest") and baseline != state["creation_manifest"]
    ):
        raise ValueError("Patch transaction baseline changed")
    for name, fingerprint in baseline.items():
        if is_test_file(name) and journal.before_manifest.get(name) != fingerprint:
            raise ValueError("Original tests changed before patch transaction")
    expected = dict(journal.before_manifest)
    repo = Repository(workspace)
    for edit in journal.edits:
        path = repo.path(edit.path, existing=False)
        if path.exists() and path.stat().st_size > 100000:
            raise ValueError("Patch transaction file exceeds budget")
        current = path.read_bytes() if path.exists() else None
        before, after = _decode(edit.before), _decode(edit.after)
        if (path.suffix != ".py" or path.name.casefold() == "conftest.py" or
            (is_test_file(edit.path) and edit.path in journal.before_manifest)):
            raise ValueError("Patch recovery cannot change existing tests or non-Python files")
        if (len(after) > 100000 or not after.strip() or
            ((hashlib.sha256(before).hexdigest() if before is not None else None)
             != journal.before_manifest.get(edit.path))):
            raise ValueError("Patch journal edit bytes differ from original manifest")
        try:
            ast.parse(after.decode("utf-8"))
        except (SyntaxError, UnicodeError) as exc:
            raise ValueError("Patch journal contains invalid Python") from exc
        if current != before and current != after:
            raise ValueError(f"Patch transaction conflict at {edit.path}; no recovery writes")
        if current == after:
            expected[edit.path] = hashlib.sha256(after).hexdigest()
    if file_manifest(workspace) != expected:
        raise ValueError("Unrecorded workspace changes outside patch transaction")
    return workspace


def inspect(state: dict) -> dict:
    items = pending(state)
    if not items:
        return {"required": False, "transactions": []}
    summaries = []
    for _, journal, sha in items:
        try:
            _verify(state, journal)
            recoverable, reason = True, None
        except (ValueError, OSError) as exc:
            recoverable, reason = False, str(exc)[:1000]
        summaries.append({"transaction_id": journal.transaction_id, "journal_digest": sha,
            "status": journal.status, "attempt": journal.attempt_before + 1,
            "candidate_id": journal.candidate_id, "recoverable": recoverable, "reason": reason,
            "files": [{"path": e.path,
                       "before_sha256": hashlib.sha256(_decode(e.before)).hexdigest() if e.before is not None else None,
                       "after_sha256": hashlib.sha256(_decode(e.after)).hexdigest()} for e in journal.edits]})
    return {"required": True, "transactions": summaries}


def _finish(state: dict, path: Path, journal: PatchJournal) -> dict:
    root, _ = _paths(state)
    workspace = _verify(state, journal)  # Validate all files before the first write.
    repo = Repository(workspace)
    for number, edit in enumerate(journal.edits, 1):
        target = repo.path(edit.path, existing=False)
        after = _decode(edit.after)
        if not target.exists() or target.read_bytes() != after:
            temporary = repo.path(str(target.relative_to(workspace)) +
                                  f".repopilot-{journal.transaction_id}.tmp", existing=False)
            temporary.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as stream:
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            journal_checkpoint(f"temporary-{number}", journal)
            # Check the destination and its ancestors again before replacement.
            target = repo.path(edit.path, existing=False)
            temporary.replace(target)
        journal_checkpoint(f"file-{number}", journal)
    actual = diff_repositories(workspace.parent / "baseline", workspace)
    result = {**journal.result, "diff": actual, "diff_digest": digest(actual)}
    journal.result = result
    journal.status = "written"
    _save(root, path, journal)
    journal_checkpoint("written", journal)
    return result


def apply_transaction(state: dict, patch: Patch, usage: dict, context: str) -> dict:
    root, workspace = _paths(state)
    if pending(state):
        raise ValueError("Pending patch transaction; inspect and explicitly recover before continuing")
    staged = Repository(workspace).stage(patch)
    actual = diff_repositories(workspace.parent / "baseline", workspace)
    if digest(actual) != (state["diff_digest"] or digest("")):
        raise ValueError("Workspace changed before patch transaction")
    edits = [JournalEdit(path=path.relative_to(workspace).as_posix(),
        before=base64.b64encode(path.read_bytes()).decode() if path.exists() else None,
        after=base64.b64encode(content.encode()).decode()) for path, content in staged.items()]
    transaction_id = str(uuid4())
    tags = ({"candidate_id": state["candidate_id"], "candidate_number": state["candidate_number"]}
            if state.get("retry_workspace_policy") == "isolated" else {})
    result = {"patches": [{**patch.model_dump(), "changed_files": [e.path for e in edits],
                           "applied": True, **tags, "transaction_id": transaction_id}],
              "attempts": state["attempts"] + 1, "context": context, **usage}
    journal = PatchJournal(transaction_id=transaction_id, task_id=state["task_id"],
        candidate_id=state.get("candidate_id"), workspace_path=str(workspace),
        attempt_before=state["attempts"], patch_count_before=len(state["patches"]),
        history_count_before=len(state["execution_history"]),
        counters_before=[state[k] for k in ("model_calls", "input_tokens", "output_tokens")],
        pre_diff_digest=state["diff_digest"] or digest(""),
        baseline_digest=manifest_digest(file_manifest(workspace.parent / "baseline")),
        before_manifest=file_manifest(workspace), edits=edits, result=result)
    path = controlled_path(root, f"patch-journal/{state['attempts'] + 1:04}.json")
    if path.exists():
        raise ValueError("Patch journal already exists; replacement refused")
    _save(root, path, journal)
    journal_checkpoint("prepared", journal)
    return _finish(state, path, journal)


def recover(state: dict, journal_digest: str) -> tuple[Path, PatchJournal, dict]:
    items = pending(state)
    if len(items) != 1:
        raise ValueError("Exactly one uncheckpointed patch is required for explicit recovery")
    path, journal, actual_digest = items[0]
    if journal_digest != actual_digest:
        raise ValueError("Patch recovery approval does not match journal digest")
    if (state["attempts"] != journal.attempt_before or
        len(state["patches"]) != journal.patch_count_before or
        (state["diff_digest"] or digest("")) != journal.pre_diff_digest or
        state["approval_status"] != "pending" or
        state["execution_status"] not in {"queued", "running", "failed", "retryable"}):
        raise ValueError("Checkpoint moved outside recoverable patch transaction")
    keys = ("model_calls", "input_tokens", "output_tokens")
    counters = [state[k] for k in keys]
    if counters not in [journal.counters_before, [journal.result[k] for k in keys]]:
        raise ValueError("Model counters changed outside patch transaction")
    result = _finish(state, path, journal)
    if len(state["execution_history"]) > journal.history_count_before:
        result["execution_history"] = []  # A caught failure already recorded model usage.
    result["execution_history"] = [*result.get("execution_history", []),
        {"node": "patch_recovery", "transaction_id": journal.transaction_id, "timestamp": time.time()}]
    result.update(execution_status="running", error=None, failure=None)
    return path, journal, result


def acknowledge(state: dict) -> None:
    pending(state, acknowledge=True)
