"""Batch-local latched circuit checked atomically before each model dispatch."""
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from app.models.reliability import CircuitSnapshot


class ProviderCircuitOpen(ValueError):
    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        super().__init__('Batch model dispatch paused by provider circuit; no new request was sent')


class ProviderCircuit:
    def __init__(self, threshold: int = 3, *, on_change: Callable[[dict], None] | None = None):
        self.state = CircuitSnapshot(enabled=threshold > 0, threshold=threshold)
        self.lock = threading.RLock()
        self.active: set[str] = set()
        self.on_change = on_change

    def snapshot(self) -> dict:
        with self.lock:
            return self.state.model_dump()

    def publish(self) -> None:
        if self.on_change:
            try:
                self.on_change(self.state.model_dump())
            except Exception:
                # Evidence failure stops the batch without discarding a completed
                # response's usage or exposing filesystem exception text.
                self.state.evidence_write_failed = True
                self.state.opened = True
                self.state.opened_at = self.state.opened_at or time.time()
                self.state.failure_signature = 'evidence_write:unknown'


    def admit(self, reserve: Callable[[], Any]) -> tuple[str, Any]:
        with self.lock:
            if not self.state.opened:
                self.publish()  # Check evidence availability before charging/admitting.
            if self.state.opened:
                raise ProviderCircuitOpen(self.state.model_dump())
            reservation = reserve()  # A refused budget does not acquire a dispatch permit.
            attempt_id = uuid.uuid4().hex
            self.active.add(attempt_id)
            self.state.admitted += 1
            self.state.in_flight = len(self.active)
            # The durable task ledger owns dispatch reservations; this batch-local
            # snapshot is refreshed before admission and on completion, not a
            # resumable dispatch log.
            return attempt_id, reservation

    def complete(self, attempt_id: str, failure: dict | None = None) -> None:
        with self.lock:
            if attempt_id not in self.active:
                return  # Idempotent observation cannot advance a failure streak twice.
            self.active.remove(attempt_id)
            self.state.in_flight = len(self.active)
            self.state.completed += 1
            if not self.state.opened and self.state.enabled:
                kind = (failure or {}).get('kind')
                if kind in {'connection', 'timeout', 'provider_unavailable', 'rate_limit', 'usage_missing', 'credentials'}:
                    phase = (failure or {}).get('diagnostics', {}).get('phase', 'unknown')
                    if phase not in {'connect', 'read', 'write', 'pool', 'proxy', 'protocol', 'response'}:
                        phase = 'unknown'
                    signature = kind + ':' + phase
                    self.state.consecutive_failures = self.state.consecutive_failures + 1 if self.state.failure_signature == signature else 1
                    self.state.failure_signature = signature
                    if self.state.consecutive_failures >= self.state.threshold or kind == 'credentials':
                        self.state.opened = True
                        self.state.opened_at = time.time()
                        self.state.triggering_attempt_id = attempt_id
                else:
                    self.state.consecutive_failures = 0
                    self.state.failure_signature = None
            self.publish()
