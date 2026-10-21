"""Preserved candidate directories and evidence; target files are never executed here."""

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.tools.repository import Repository, diff_repositories, digest, is_test_file, snapshot


class CandidateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = Field(ge=1, le=6)
    candidate_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    baseline_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def file_manifest(root: Path) -> dict[str, str]:
    repo = Repository(root)
    return {
        name: hashlib.sha256(repo.path(name).read_bytes()).hexdigest() for name in repo.list_files()
    }


def manifest_digest(manifest: dict[str, str]) -> str:
    return digest(json.dumps(manifest, sort_keys=True, separators=(",", ":")))


def candidate_tags(state: dict) -> dict:
    if state.get("retry_workspace_policy") != "isolated":
        return {}
    return {"candidate_id": state["candidate_id"], "candidate_number": state["candidate_number"]}


def controlled_path(task_root: Path, relative: str, *, directory: bool = False) -> Path:
    # Repository.path checks each existing ancestor for links/junctions as well.
    if directory:
        path = Repository(task_root).path(relative + "/.directory-probe", existing=False).parent
        if path.exists() and not path.is_dir():
            raise ValueError("Candidate path is not a directory")
        return path
    return Repository(task_root).path(relative, existing=False)


def activate_staging(task_root: Path, staging: Path, destination: Path) -> None:
    """Retry only Windows access/sharing errors; never replace an existing candidate."""
    for attempt in range(3):
        # Validate the absolute move targets and their ancestors again on every retry.
        checked_staging = controlled_path(task_root, staging.relative_to(task_root).as_posix(),
                                          directory=True)
        checked_destination = controlled_path(task_root, destination.relative_to(task_root).as_posix(),
                                              directory=True)
        if (checked_staging.resolve() != staging.resolve() or
                checked_destination.resolve() != destination.resolve() or
                not staging.resolve().is_relative_to(task_root.resolve()) or
                not destination.resolve().is_relative_to(task_root.resolve())):
            raise ValueError("Candidate activation paths changed")
        if destination.exists():
            raise ValueError("Candidate destination already exists; replacement refused")
        try:
            staging.rename(destination)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 2:
                raise
            time.sleep(0.05 * (attempt + 1))


def reusable_staging(task_root: Path, number: int, expected: dict[str, str]) -> Path | None:
    attempts = controlled_path(task_root, "attempts", directory=True)
    matches = []
    if attempts.exists():
        for entry in sorted(attempts.glob("preparing-*")):
            relative = entry.relative_to(task_root).as_posix()
            path = controlled_path(task_root, relative, directory=True)
            manifest_path = controlled_path(task_root, relative + "/candidate.json")
            if not manifest_path.is_file():
                continue  # Keep incomplete snapshots; never reset them.
            manifest = CandidateManifest.model_validate_json(manifest_path.read_text(encoding="utf8"))
            if manifest.number != number:
                continue
            if (manifest.baseline_digest != manifest_digest(expected) or
                    file_manifest(controlled_path(task_root, relative + "/baseline", directory=True)) != expected or
                    file_manifest(controlled_path(task_root, relative + "/workspace", directory=True)) != expected):
                raise ValueError("Unrecorded staging writes found; preserved without replay")
            matches.append(path)
    if len(matches) > 1:
        raise ValueError("Ambiguous prepared candidates; preserved without choosing one")
    return matches[0] if matches else None


def prepare_candidate(task_root: Path, number: int, expected: dict[str, str]) -> dict:
    original = controlled_path(task_root, "baseline", directory=True)
    if file_manifest(original) != expected:
        raise ValueError("Original baseline changed; candidate preparation refused")
    destination = controlled_path(task_root, f"attempts/{number:04}", directory=True)
    expected_digest = manifest_digest(expected)
    if not destination.exists():
        staging = reusable_staging(task_root, number, expected)
        if staging is None:
            staging = controlled_path(task_root, f"attempts/preparing-{uuid.uuid4()}", directory=True)
            staging.mkdir(parents=True)
            snapshot(Repository(original), staging / "baseline")
            snapshot(Repository(original), staging / "workspace")
            manifest = CandidateManifest(
                number=number, candidate_id=str(uuid.uuid4()), baseline_digest=expected_digest
            )
            (staging / "candidate.json").write_text(manifest.model_dump_json(), encoding="utf8")
        activate_staging(task_root, staging, destination)
    manifest = CandidateManifest.model_validate_json(
        controlled_path(task_root, f"attempts/{number:04}/candidate.json").read_text(
            encoding="utf8"
        )
    )
    if manifest.number != number or manifest.baseline_digest != expected_digest:
        raise ValueError("Candidate identity or baseline differs from preparation record")
    candidate_baseline = controlled_path(
        task_root, f"attempts/{number:04}/baseline", directory=True
    )
    candidate_workspace = controlled_path(
        task_root, f"attempts/{number:04}/workspace", directory=True
    )
    if file_manifest(candidate_baseline) != expected or (
        file_manifest(candidate_workspace) != expected
    ):
        raise ValueError("Unrecorded candidate writes found; preserved without replay")
    return {
        "candidate_id": manifest.candidate_id,
        "candidate_number": number,
        "workspace_path": str(destination / "workspace"),
    }


def validate_isolated(state: dict, task_root: Path | None = None) -> None:
    if state.get("retry_workspace_policy") != "isolated":
        return
    root = Path(state["task_path"]).resolve(strict=True)
    if task_root is not None and root != task_root.resolve(strict=True):
        raise ValueError("Task storage identity differs")
    expected = state["baseline_manifest"]
    workspace = controlled_path(
        root, f"attempts/{state['candidate_number']:04}/workspace", directory=True
    )
    if Path(state["workspace_path"]).resolve(strict=True) != workspace.resolve(strict=True):
        raise ValueError("Active workspace differs from candidate identity")
    manifest = CandidateManifest.model_validate_json(
        controlled_path(root, f"attempts/{state['candidate_number']:04}/candidate.json").read_text(
            encoding="utf8"
        )
    )
    if (
        manifest.number != state["candidate_number"]
        or manifest.candidate_id != state["candidate_id"]
        or (manifest.baseline_digest != manifest_digest(expected))
    ):
        raise ValueError("Candidate identity or baseline fingerprint differs")
    if file_manifest(controlled_path(root, "baseline", directory=True)) != expected or (
        file_manifest(
            controlled_path(
                root, f"attempts/{state['candidate_number']:04}/baseline", directory=True
            )
        )
        != expected
    ):
        raise ValueError("Immutable baseline changed")
    repo = Repository(workspace)
    for name, fingerprint in expected.items():
        if (
            is_test_file(name)
            and hashlib.sha256(repo.path(name).read_bytes()).hexdigest() != fingerprint
        ):
            raise ValueError("Original tests changed")
    for archived in state.get("attempt_history", []):
        if (
            file_manifest(
                controlled_path(
                    root, f"attempts/{archived['candidate_number']:04}/workspace", directory=True
                )
            )
            != archived["workspace_manifest"]
            or (
                hashlib.sha256(
                    controlled_path(
                        root, f"attempts/{archived['candidate_number']:04}/evidence.json"
                    ).read_bytes()
                ).hexdigest()
                != archived["evidence_sha256"]
            )
            or file_manifest(
                controlled_path(
                    root, f"attempts/{archived['candidate_number']:04}/baseline", directory=True
                )
            )
            != expected
        ):
            raise ValueError("Archived candidate evidence changed")


def save_candidate(state: dict) -> dict[str, Any]:
    """Record actual bytes plus recorded state; never overwrite prior candidate directories."""
    root = Path(state["task_path"])
    workspace = Path(state["workspace_path"])
    actual = diff_repositories(workspace.parent / "baseline", workspace)
    number = state["candidate_number"]
    evidence = {
        **candidate_tags(state),
        "execution_status": state["execution_status"],
        "diff": actual,
        "diff_digest": digest(actual),
        "recorded_digest": state["diff_digest"],
        "matches_recorded": digest(actual) == (state["diff_digest"] or digest("")),
        "patches": [p for p in state["patches"] if p.get("candidate_id") == state["candidate_id"]],
        "tests": [
            t for t in state["test_results"] if t.get("candidate_id") == state["candidate_id"]
        ],
        "reviews": [
            r for r in state["review_results"] if r.get("candidate_id") == state["candidate_id"]
        ],
        "patch_feedback": [
            f
            for f in state.get("patch_feedback", [])
            if f.get("candidate_id") == state["candidate_id"]
        ],
        "repair_feedback": [f for f in state.get("repair_feedback", [])
                            if f.get("candidate_id") == state["candidate_id"]],
        "regression_results": [r for r in state.get("regression_results", [])
                               if r.get("candidate_id") == state["candidate_id"]],
        "model_calls_total": state["model_calls"],
        "retry_count": state["retry_count"],
        "workspace_manifest": file_manifest(workspace),
    }
    content = json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=2).encode("utf8")
    path = controlled_path(root, f"attempts/{number:04}/evidence.json")
    temporary = controlled_path(root, f"attempts/{number:04}/evidence-{uuid.uuid4()}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return {
        **candidate_tags(state),
        "workspace_path": str(workspace),
        "diff_digest": digest(actual),
        "workspace_manifest": evidence["workspace_manifest"],
        "evidence_sha256": hashlib.sha256(content).hexdigest(),
    }
