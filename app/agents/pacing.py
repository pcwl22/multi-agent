"""Process-local request pacing shared by models using the same endpoint."""

import threading
import time

from app.services.budgets import BudgetExceeded


class RequestPacer:
    def __init__(self):
        self.lock = threading.Lock()
        self.next_start = 0.0

    def wait(self, interval: float, *, deadline: float | None = None) -> float:
        if interval <= 0:
            return 0.0
        acquired = self.lock.acquire(timeout=max(0, deadline - time.monotonic())) if deadline is not None else self.lock.acquire()
        if not acquired:
            raise BudgetExceeded("wall_seconds", "Task deadline exhausted while waiting for model pacing")
        try:
            delay = max(0.0, self.next_start - time.monotonic())
            if deadline is not None and time.monotonic() + delay >= deadline:
                raise BudgetExceeded("wall_seconds", "Task deadline cannot accommodate model pacing")
            if delay:
                time.sleep(delay)
            self.next_start = time.monotonic() + interval
            return delay
        finally:
            self.lock.release()


_pacers: dict[str, RequestPacer] = {}
_registry_lock = threading.Lock()


def endpoint_pacer(endpoint: str | None) -> RequestPacer:
    # No credential is stored in the registry. Pacing all users of an endpoint
    # together is conservative. Separate OS processes are not coordinated.
    key = (endpoint or "https://api.openai.com/v1").rstrip("/")
    with _registry_lock:
        return _pacers.setdefault(key, RequestPacer())
