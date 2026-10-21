"""Offline, read-only ledger audit. Never settles reservations or grants allowance.

Inspect a sealed ledger, not an active worker. External billing receipts remain
separate evidence; absence of a receipt cannot establish zero charge.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from pydantic import Field

from app.models.budgets import BudgetLimits
from app.models.schemas import StrictModel
from app.services.attempts import controlled_path


class LedgerBinding(StrictModel):
    task_id: str = Field(min_length=1, max_length=200)
    limits: BudgetLimits
    deadline: float = Field(gt=0, allow_inf_nan=False)


def audit_ledger(task_root: Path) -> dict:
    root = task_root.absolute()
    path = controlled_path(root, 'budget.sqlite3')
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('Use an existing bounded sealed budget ledger')
    # Immutable mode cannot safely interpret a live WAL. Reject rather than
    # checkpoint it, modify SHM files or accidentally ignore pending writes.
    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('Seal the worker first; journal sidecars are not auditable here')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA integrity_check(1)').fetchone() != ('ok',):
            raise ValueError('Budget ledger integrity failed')
        rows = db.execute('SELECT binding,model_requests,sandbox_runs,tokens,incomplete FROM budget').fetchall()
        if len(rows) != 1:
            raise ValueError('Budget ledger must have exactly one binding')
        binding, requests, runs, tokens, incomplete = rows[0]
        identity = LedgerBinding.model_validate_json(binding)
        limits = identity.limits
        if db.execute('SELECT count(*) FROM reservations').fetchone()[0] > limits.model_requests + limits.sandbox_runs:
            raise ValueError('Reservation count exceeds the frozen allowance')
        reservation_rows = db.execute('SELECT id,kind,completed FROM reservations ORDER BY id').fetchall()
    if before != hashlib.sha256(path.read_bytes()).hexdigest() or any(
        Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')
    ):
        raise ValueError('Budget ledger changed during audit')
    if (any(type(x) is not int or x < 0 for x in (requests, runs, tokens)) or
            incomplete not in (0, 1)):
        raise ValueError('Invalid ledger counters or binding')
    if requests > limits.model_requests or runs > limits.sandbox_runs:
        raise ValueError('Dispatch counters exceed the frozen allowance')
    for ident, kind, completed in reservation_rows:
        if type(ident) is not int or ident <= 0 or kind not in {'model_requests', 'sandbox_runs'} or completed not in (0, 1):
            raise ValueError('Invalid reservation row')
    if requests != sum(r[1] == 'model_requests' for r in reservation_rows) or runs != sum(
        r[1] == 'sandbox_runs' for r in reservation_rows
    ):
        raise ValueError('Counters disagree with reservations')
    pending_model = sum(r[1] == 'model_requests' and not r[2] for r in reservation_rows)
    pending_sandbox = sum(r[1] == 'sandbox_runs' and not r[2] for r in reservation_rows)
    usage_status = 'unconfirmed_dispatch' if pending_model else ('unknown' if incomplete else 'complete')
    return {
        'version': 1, 'ledger_sha256': before, 'binding_sha256': hashlib.sha256(binding.encode()).hexdigest(),
        'model_request_reservations': requests, 'sandbox_run_reservations': runs,
        'pending_model_reservations': pending_model, 'pending_sandbox_reservations': pending_sandbox,
        'observed_tokens': tokens, 'usage_status': usage_status,
        'usage_unknown': bool(incomplete or pending_model),
        'billing_status': 'not_reconciled', 'automatic_replay_allowed': False,
        'scope': 'Sealed local ledger only. Reservations do not prove dispatch or billing; observed tokens do not establish invoice totals.',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task_root', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_ledger(args.task_root), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
