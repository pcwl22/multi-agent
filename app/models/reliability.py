"""Bounded reliability metadata; never carries exception text or HTTP bodies."""
from typing import Literal

from pydantic import Field

from app.models.schemas import StrictModel

TransportPhase = Literal['connect', 'read', 'write', 'pool', 'proxy', 'protocol', 'response', 'unknown']
StopKind = Literal['limit_reached', 'usage_unknown', 'dispatch_uncertain', 'ledger_integrity']


class TransportDiagnostics(StrictModel):
    version: Literal[1] = 1
    phase: TransportPhase = 'unknown'
    exception_types: list[str] = Field(default_factory=list, max_length=8)
    chain_truncated: bool = False
    streaming_requested: bool | None = None
    response_completion: Literal['unconfirmed'] = 'unconfirmed'
    interpretation: str = 'Exception classes identify a transport phase, not the billing outcome or server root cause.'


class BudgetStop(StrictModel):
    kind: StopKind
    resource: str
    message: str


class CircuitSnapshot(StrictModel):
    version: Literal[1] = 1
    enabled: bool
    threshold: int = Field(ge=0, le=20)
    opened: bool = False
    consecutive_failures: int = 0
    failure_signature: str | None = None
    triggering_attempt_id: str | None = None
    opened_at: float | None = None
    admitted: int = 0
    completed: int = 0
    in_flight: int = 0
    evidence_write_failed: bool = False
    ordering: str = 'Completion order across this batch; already admitted calls may finish. Open is latched, with no automatic reset or replay.'


def budget_stop_notice(state: dict) -> str:
    detail = state.get('budget_failure') or {}
    kind = detail.get('kind')
    if kind is None:  # Display old saved tasks accurately without rewriting their evidence.
        kind = {'uncertain_dispatch': 'dispatch_uncertain', 'ledger_integrity': 'ledger_integrity'}.get(detail.get('resource'))
        if kind is None:
            kind = 'usage_unknown' if not state.get('token_usage_complete', True) else 'limit_reached'
    return {
        'usage_unknown': '模型用量尚未确认，任务已停止并保留现场。核对提供方用量前不会自动重发；这不表示额度一定已用完。',
        'dispatch_uncertain': '上次执行是否完成尚未确认，任务已停止并保留现场，避免重复发送。',
        'ledger_integrity': '预算记录无法安全核验，任务已停止并保留现场。此任务不会自动继续。',
        'limit_reached': '任务已达到预算限制，现场与 Diff 已保留。此任务不再发起模型或 Docker 执行。',
    }[kind]
