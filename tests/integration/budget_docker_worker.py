"""Trusted process-loss helper. Target Python tests execute exclusively in Docker."""
import json
import sys
from pathlib import Path

from app.config.settings import Settings
from app.sandbox.runner import DockerRunner
from app.services.budgets import TaskBudget, budget_scope

state = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
budget = TaskBudget(state)
reservation = budget.reserve('sandbox_runs')
with budget_scope(budget):
    DockerRunner(Settings(_env_file=None, test_timeout=5)).run(Path(state['workspace_path']))
budget.complete(reservation)
