"""Validated, task-frozen resource limits."""
from pydantic import Field

from app.models.schemas import StrictModel


class BudgetLimits(StrictModel):
    wall_seconds: float = Field(default=900, ge=1, le=86400)
    model_requests: int = Field(default=20, ge=1, le=200)
    observed_tokens: int = Field(default=200000, ge=1, le=10000000)
    sandbox_runs: int = Field(default=10, ge=1, le=100)
    artifact_bytes: int = Field(default=268435456, ge=1048576, le=2147483648)
    result_bytes: int = Field(default=8388608, ge=1048576, le=33554432)
