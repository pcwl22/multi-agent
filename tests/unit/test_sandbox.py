import subprocess
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.sandbox.runner import DockerRunner, parse_junit


def test_command_allowlist(tmp_path):
    with pytest.raises(ValueError, match="predefined"):
        DockerRunner(Settings()).run(tmp_path, ("sh", "-c", "id"))


def test_no_host_fallback(monkeypatch, tmp_path):
    calls = []

    def unavailable(args, **kwargs):
        calls.append(args)
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", unavailable)
    result = DockerRunner(Settings()).run(tmp_path)
    assert result.status == "unavailable"
    assert all(args[0] == "docker" for args in calls)


def test_junit_counts(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text(
        "<testsuites><testsuite><testcase/><testcase><failure/>"
        "</testcase><testcase><skipped/></testcase></testsuite></testsuites>"
    )
    assert parse_junit(report) == {"passed": 1, "failed": 1, "errors": 0, "skipped": 1}


def test_container_restrictions(monkeypatch, tmp_path):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if "run" in args:
            mount = next(a for a in args if a.endswith("target=/results"))
            output = Path(mount.split("source=", 1)[1].split(",target=", 1)[0])
            (output / "junit.xml").write_text("<testsuite><testcase/></testsuite>")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", run)
    result = DockerRunner(Settings()).run(tmp_path)
    assert result.status == "passed"
    command = next(c for c in calls if "run" in c)
    for option in [
        "--network=none",
        "--read-only",
        "--user=65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=64",
    ]:
        assert option in command
    assert all("docker.sock" not in c for c in command)
