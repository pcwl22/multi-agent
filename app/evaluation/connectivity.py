"""Fresh, sequential connectivity probes; never resumes old or uncertain calls.

No repository code, GitHub write or repair benchmark is involved. The CLI needs
an explicit frozen plan digest. A failed or unaccounted request stops the batch.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Callable

from pydantic import Field, SecretStr

from app.agents.model import LiveModel, ModelFailure
from app.config.settings import Settings
from app.models.budgets import BudgetLimits
from app.models.schemas import Plan, StrictModel
from app.services.budget_audit import audit_ledger
from app.services.budgets import BudgetExceeded, TaskBudget, budget_scope
from app.services.provider_circuit import ProviderCircuit, ProviderCircuitOpen


class ConnectivityPlan(StrictModel):
    version: int = Field(default=1, ge=1, le=1)
    model_name: str = Field(min_length=1, max_length=120)
    # No userinfo, query or fragment can be smuggled into the persisted URL.
    model_base_url: str = Field(pattern=r'^https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?/v1$')
    timeout_seconds: int = Field(default=45, ge=1, le=90)
    observed_tokens_per_cell: int = Field(default=4096, ge=512, le=8192)
    runtime_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    payload: dict = Field(default_factory=lambda: {
        'issue_description': 'Connectivity probe only. Return a short Plan about checking connectivity. No repository exists; no tools or code execution.'})


def atomic_json(path: Path, value: dict | list) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def runtime_digest() -> str:
    root = Path(__file__).parents[1]
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(root.rglob('*.py'))}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def run_probe(plan_path: Path, expected_digest: str, output: Path, api_key: SecretStr, *,
              model_factory: Callable = LiveModel) -> dict:
    raw = plan_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError('Connectivity plan digest differs')
    plan = ConnectivityPlan.model_validate_json(raw)
    if runtime_digest() != plan.runtime_sha256:
        raise ValueError('Connectivity runtime differs from frozen plan')
    # A fresh directory is the durable no-replay boundary, including crashes
    # before any complete response. No code path reopens it for execution.
    output.mkdir(parents=True, exist_ok=False)
    (output / 'plan.json').write_bytes(raw)
    rows = [{'id': 'fresh-nonstreaming', 'streaming': False, 'status': 'not_run'},
            {'id': 'fresh-streaming', 'streaming': True, 'status': 'not_run'}]
    atomic_json(output / 'records.json', rows)
    gate = ProviderCircuit(1)
    stopped = False
    for row in rows:
        if stopped:
            row.update(reason='prior_probe_failed_or_usage_unconfirmed')
            continue
        root = output / row['id']
        root.mkdir()
        limits = BudgetLimits(model_requests=1, observed_tokens=plan.observed_tokens_per_cell,
            sandbox_runs=1, wall_seconds=plan.timeout_seconds + 15)
        budget = TaskBudget({'task_id': row['id'], 'task_path': str(root),
            'budget_limits': limits.model_dump(), 'budget_deadline': time.time() + limits.wall_seconds}, create=True)
        row.update(status='dispatch_uncertain', reason='controller_started_response_not_yet_recorded')
        atomic_json(output / 'records.json', rows)
        settings = Settings(_env_file=None, model_mode='live', model_name=plan.model_name,
            model_base_url=plan.model_base_url, openai_api_key=api_key,
            model_streaming=row['streaming'], model_stream_usage=True,
            model_timeout=plan.timeout_seconds, model_min_interval=7.5)
        stats = {}
        try:
            model = model_factory(settings, dispatch_gate=gate)
            with budget_scope(budget):
                value, stats = model.generate(Plan, plan.payload)
                budget.check()
            row.update(status='passed', result=value.model_dump(), stats=stats)
        except (ModelFailure, BudgetExceeded, ProviderCircuitOpen) as exc:
            row.update(status='failed', error_type=type(exc).__name__, stats=getattr(exc, 'stats', stats))
            if isinstance(exc, BudgetExceeded):
                row['budget_failure'] = exc.detail.model_dump()
        except Exception:
            # No exception string/classname from an untrusted provider is stored.
            row.update(status='failed', error_type='UnexpectedControllerFailure')
        row.pop('reason', None)
        row['ledger'] = audit_ledger(root)
        if row['ledger']['usage_unknown'] or row['status'] != 'passed':
            stopped = True
        atomic_json(output / 'records.json', rows)
    report = {'plan_sha256': expected_digest, 'planned_cells': 2,
        'passed': sum(r['status'] == 'passed' for r in rows),
        'failed': sum(r['status'] == 'failed' for r in rows),
        'not_run': sum(r['status'] == 'not_run' for r in rows),
        'model_request_reservations': sum(r.get('ledger', {}).get('model_request_reservations', 0) for r in rows),
        'known_tokens_including_partial': sum(r.get('ledger', {}).get('observed_tokens', 0) for r in rows),
        'unknown_usage_cells': sum(r.get('ledger', {}).get('usage_unknown', False) for r in rows),
        'connectivity_smoke_passed': all(r['status'] == 'passed' and not r['ledger']['usage_unknown'] for r in rows),
        'repair_ability_evaluated': False, 'billing_reconciled': False,
        'limitations': 'Two smoke probes do not establish sustained availability or repair quality. Observed tokens are not a monetary spending cap. Old probes and budgets are never reopened.'}
    atomic_json(output / 'records.json', rows)
    atomic_json(output / 'report.json', report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Credentials stay in the interactive process, never in the frozen plan.
    import getpass
    secret = SecretStr(getpass.getpass('Provider key (hidden): '))
    print(json.dumps(run_probe(args.plan, args.sha256, args.output, secret), ensure_ascii=False))


if __name__ == '__main__':
    main()
