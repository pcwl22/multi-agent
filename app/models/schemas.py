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
    acceptance_contracts: list[str] = Field(default_factory=list, max_length=32)


class Edit(StrictModel):
    path: str
    old: str = Field(max_length=50000)
    new: str = Field(max_length=50000)


class Patch(StrictModel):
    rationale: str
    edits: list[Edit] = Field(min_length=1, max_length=8)
    contract_tests: list[str] = Field(default_factory=list, max_length=32)


class ContractCheck(StrictModel):
    requirement: str = Field(max_length=2000)
    satisfied: bool
    evidence: str = Field(max_length=4000)


class Review(StrictModel):
    approved: bool
    summary: str
    concerns: list[str]
    contract_checks: list[ContractCheck] = Field(default_factory=list, max_length=32)


class TestCaseEvidence(StrictModel):
    file: str = Field(default="", max_length=500)
    name: str = Field(default="", max_length=1000)
    classname: str = Field(default="", max_length=1000)
    line: int | None = None
    status: Literal["passed", "failed", "error", "skipped"]
    message: str = Field(default="", max_length=2000)
    details: str = Field(default="", max_length=6000)


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
    cases: list[TestCaseEvidence] = Field(default_factory=list, max_length=512)
    cases_truncated: bool = False


class TaskRequest(StrictModel):
    issue_description: str | None = Field(default=None, min_length=5, max_length=10000)
    github_issue_url: str | None = Field(default=None, max_length=300)
    repository_path: str
    mode: Mode = "multi_full"
    retry_workspace_policy: Literal["preserve", "isolated"] | None = None

    @model_validator(mode="after")
    def require_one_source(self):
        if bool(self.issue_description) == bool(self.github_issue_url):
            raise ValueError("Provide exactly one issue_description or github_issue_url")
        return self


class Approval(StrictModel):
    publication_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    diff_digest: str = Field(min_length=64, max_length=64)
    candidate_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")


class AgentState(TypedDict):
    task_id: str
    thread_id: str
    issue_description: str
    repository_path: str
    workspace_path: str
    task_path: str
    budget_initialized: bool
    budget_version: int | None
    budget_limits: dict
    budget_deadline: float
    budget_failure: dict | None
    patch_transaction_version: int | None
    repair_quality_version: int | None
    publication_contract_version: int
    retry_workspace_policy: Literal["preserve", "isolated"]
    baseline_manifest: dict[str, str]
    creation_manifest: dict[str, str]
    creation_attempts: int
    creation_failures: list[dict]
    candidate_id: str | None
    candidate_number: int
    approved_candidate_id: str | None
    previous_candidate_diff: str
    attempt_history: Annotated[list[dict], operator.add]
    mode: Mode
    execution_status: str
    plan: dict[str, Any] | None
    located_files: list[str]
    context: str
    patches: Annotated[list[dict], operator.add]
    patch_feedback: Annotated[list[dict], operator.add]
    test_results: Annotated[list[dict], operator.add]
    repair_feedback: Annotated[list[dict], operator.add]
    regression_results: Annotated[list[dict], operator.add]
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
    failure: dict[str, Any] | None
    provider_retry_count: int
    next_node: str
    diff: str
    diff_digest: str
