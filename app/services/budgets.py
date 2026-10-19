"""Opt-in durable dispatch budgets. Reservations precede external work.

The ledger is intentionally independent of LangGraph checkpoint commits: a lost
response never grants a fresh request allowance after process restart.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from app.models.budgets import BudgetLimits
from app.services.attempts import controlled_path


class BudgetExceeded(ValueError):
    def __init__(self, resource: str, message: str):
        self.resource = resource
        super().__init__(message)


_current: ContextVar['TaskBudget | None'] = ContextVar('task_budget', default=None)


def current_budget() -> TaskBudget | None:
    return _current.get()


@contextmanager
def budget_scope(budget: TaskBudget | None) -> Iterator[None]:
    token = _current.set(budget)
    try:
        yield
    finally:
        _current.reset(token)


class TaskBudget:
    def __init__(self, state: dict[str, Any], *, create: bool = False):
        self.root = Path(state['task_path']).resolve(strict=True)
        self.path = controlled_path(self.root, 'budget.sqlite3')
        self.limits = BudgetLimits.model_validate(state['budget_limits'])
        expected = json.dumps({'task_id': state['task_id'], 'limits': self.limits.model_dump(),
                               'deadline': state['budget_deadline']}, sort_keys=True)
        if not self.path.exists() and not create:
            raise BudgetExceeded('ledger_integrity', 'Task budget ledger missing; allowance cannot be reset')
        with self.connect() as db:
            if create:
                db.execute('CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY, binding TEXT, '
                           'last_time REAL, model_requests INTEGER, sandbox_runs INTEGER, '
                           'tokens INTEGER, incomplete INTEGER)')
                db.execute('CREATE TABLE IF NOT EXISTS reservations '
                           '(id INTEGER PRIMARY KEY, kind TEXT, completed INTEGER)')
                db.execute('INSERT OR IGNORE INTO budget VALUES (1,?, ?,0,0,0,0)',
                           (expected, time.time()))
            row = db.execute('SELECT binding,last_time FROM budget WHERE id=1').fetchone()
            if row is None or row[0] != expected:
                raise BudgetExceeded('ledger_integrity', 'Task budget binding changed')
        self.deadline = state['budget_deadline']
        self.anchor_time = max(time.time(), row[1])
        self.anchor_monotonic = time.monotonic()

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def view(self) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute('SELECT last_time,model_requests,sandbox_runs,tokens,incomplete '
                             'FROM budget WHERE id=1').fetchone()
            pending = db.execute('SELECT count(*) FROM reservations WHERE completed=0').fetchone()[0]
        return {'enabled': True, 'limits': self.limits.model_dump(), 'deadline': self.deadline,
                'remaining_seconds': max(0, self.deadline - max(time.time(), row[0], self.anchor_time + time.monotonic() - self.anchor_monotonic)),
                'model_requests': row[1], 'sandbox_runs': row[2], 'observed_tokens': row[3],
                'usage_complete': not bool(row[4]), 'pending_reservations': pending}

    def remaining(self) -> float:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT last_time FROM budget WHERE id=1').fetchone()[0]
            now = max(previous, time.time(), self.anchor_time + time.monotonic() - self.anchor_monotonic)
            db.execute('UPDATE budget SET last_time=? WHERE id=1', (now,))
        remaining = self.deadline - now
        if remaining <= 0:
            raise BudgetExceeded('wall_seconds', 'Task deadline exhausted; no further execution')
        return remaining

    def check(self) -> None:
        self.remaining()
        view = self.view()
        if view['pending_reservations']:
            raise BudgetExceeded('uncertain_dispatch', 'Interrupted dispatch preserved; automatic replay disabled')
        if not view['usage_complete']:
            raise BudgetExceeded('observed_tokens', 'Model usage incomplete; remaining token budget is unknown')
        if view['observed_tokens'] >= self.limits.observed_tokens:
            raise BudgetExceeded('observed_tokens', 'Observed token budget exhausted')
        total = 0
        for path in self.root.rglob('*'):
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise ValueError('Linked task artifact is not allowed')
            if path.is_file():
                total += path.stat().st_size
                if total > self.limits.artifact_bytes:
                    raise BudgetExceeded('artifact_bytes', 'Task artifact admission budget exhausted')

    def reserve(self, kind: str) -> int:
        assert kind in {'model_requests', 'sandbox_runs'}
        self.check()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM reservations WHERE completed=0').fetchone()[0]:
                raise BudgetExceeded('uncertain_dispatch', 'Another dispatch is still unresolved')
            count = db.execute(f'SELECT {kind} FROM budget WHERE id=1').fetchone()[0]
            if count >= getattr(self.limits, kind):
                raise BudgetExceeded(kind, f'Task {kind} budget exhausted')
            db.execute(f'UPDATE budget SET {kind}={kind}+1 WHERE id=1')
            ident = db.execute('INSERT INTO reservations(kind,completed) VALUES (?,0)', (kind,)).lastrowid
        return ident

    def complete(self, ident: int, stats: dict | None = None) -> None:
        stats = stats or {}
        tokens = max(0, int(stats.get('input_tokens', 0))) + max(0, int(stats.get('output_tokens', 0)))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE reservations SET completed=1 WHERE id=? AND completed=0', (ident,)).rowcount
            if changed:
                db.execute('UPDATE budget SET tokens=tokens+?, incomplete=max(incomplete,?) WHERE id=1',
                           (tokens, int(not stats.get('usage_complete', True))))


def for_state(state: dict) -> TaskBudget | None:
    try:
        return TaskBudget(state) if state.get('budget_version') == 1 else None
    except sqlite3.Error as exc:
        raise BudgetExceeded('ledger_integrity', 'Task budget ledger cannot be read safely') from exc


def stopped(exc: BudgetExceeded) -> dict[str, Any]:
    return {'execution_status': 'budget_exhausted', 'error': str(exc),
            'budget_failure': {'resource': exc.resource, 'message': str(exc), 'timestamp': time.time()},
            'next_node': '__end__'}
