import operator
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import TypedDict

Mode = Literal["single", "multi_no_review", "multi_full"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Plan(StrictModel):
    issue_summary: str
    suspected_modules: list[str]
    search_strategy: list[str]
    repair_steps: list[str]
    validation_strategy: list[str]


class Edit(StrictModel):
    path: str
    old: str = Field(max_length=50000)
    new: str = Field(max_length=50000)


class Patch(StrictModel):
    rationale: str
    edits: list[Edit] = Field(min_length=1, max_length=8)


class Review(StrictModel):
    approved: bool
    summary: str
    concerns: list[str]


class TestResult(StrictModel):
    __test__: ClassVar[bool] = False
    status: Literal["passed", "failed", "unavailable", "timeout"]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    image_id: str | None = None
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: float = 0
    evidence: Literal["docker", "test_double"] = "docker"


class TaskRequest(StrictModel):
    issue_description: str | None = Field(default=None, min_length=5, max_length=10000)
    github_issue_url: str | None = Field(default=None, max_length=300)
    repository_path: str
    mode: Mode = "multi_full"

    @model_validator(mode="after")
    def require_one_source(self):
        if bool(self.issue_description) == bool(self.github_issue_url):
            raise ValueError("Provide exactly one issue_description or github_issue_url")
        return self


class Approval(StrictModel):
    diff_digest: str = Field(min_length=64, max_length=64)


class AgentState(TypedDict):
    task_id: str
    thread_id: str
    issue_description: str
    repository_path: str
    workspace_path: str
    mode: Mode
    execution_status: str
    plan: dict[str, Any] | None
    located_files: list[str]
    context: str
    patches: Annotated[list[dict], operator.add]
    patch_feedback: Annotated[list[dict], operator.add]
    test_results: Annotated[list[dict], operator.add]
    review_results: Annotated[list[dict], operator.add]
    retry_count: int
    attempts: int
    approval_status: str
    execution_history: Annotated[list[dict], operator.add]
    retrieval_history: Annotated[list[dict], operator.add]
    model_calls: int
    input_tokens: int
    output_tokens: int
    token_usage_complete: bool
    error: str | None
    next_node: str
    diff: str
    diff_digest: str
