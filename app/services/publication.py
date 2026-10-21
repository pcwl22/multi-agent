"""Canonical, credential-free publication requests for separate human approval."""
import hashlib
import json
from typing import Literal

from pydantic import Field, field_validator

from app.models.schemas import StrictModel

SHA256 = r"^[a-f0-9]{64}$"
GIT_SHA = r"^[a-f0-9]{40}$"


class PublicationTarget(StrictModel):
    repository: str
    configured_base_branch: str | None = None
    subdirectory: str = ""


class PublicationEntry(StrictModel):
    path: str
    mode: Literal["100644"] = "100644"
    type: Literal["blob"] = "blob"
    content: str = Field(max_length=100000)
    before_sha256: str | None = Field(default=None, pattern=SHA256)


class PublicationPlan(StrictModel):
    version: Literal[1] = 1
    task_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    candidate_id: str | None = None
    diff_digest: str = Field(pattern=SHA256)
    baseline_digest: str = Field(pattern=SHA256)
    workspace_digest: str = Field(pattern=SHA256)
    target: PublicationTarget
    base_branch: str
    base_sha: str = Field(pattern=GIT_SHA)
    base_tree: str = Field(pattern=GIT_SHA)
    branch: str
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(max_length=20000)
    draft: Literal[True] = True
    entries: list[PublicationEntry] = Field(min_length=1, max_length=128)

    @field_validator("title")
    @classmethod
    def one_line_title(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("PR title must be one nonempty line without control characters")
        return value

    def digest(self) -> str:
        data = json.dumps(self.model_dump(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()


class PublicationOptions(StrictModel):
    title: str | None = Field(default=None, max_length=256)
    body: str | None = Field(default=None, max_length=20000)


class PublicationDecision(StrictModel):
    request_digest: str = Field(pattern=SHA256)
