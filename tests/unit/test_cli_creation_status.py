import json
import sys

import pytest

import app.cli as cli


@pytest.mark.parametrize("resume", [False, True])
def test_cli_creation_failure_is_nonzero_and_closes_service(monkeypatch, capsys, resume):
    closed = []

    class ServiceDouble:
        """CLI status propagation only; never executes target code or a model."""

        def __init__(self, settings):
            pass

        def create(self, request):
            return {"task_id": "controlled-task"}

        def run(self, task_id):
            assert task_id == "controlled-task"
            return {"task_id": task_id, "execution_status": "creation_failed"}

        def close(self):
            closed.append(True)

    monkeypatch.setattr(cli, "TaskService", ServiceDouble)
    monkeypatch.setattr(sys, "argv", ["repopilot", *(["--resume", "controlled-task"] if resume else [])])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["execution_status"] == "creation_failed"
    assert "creation" in captured.err.lower()
    assert closed == [True]
