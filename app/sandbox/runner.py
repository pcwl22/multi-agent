import os
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from app.config.settings import Settings
from app.models.schemas import TestCaseEvidence, TestResult
from app.sandbox.output import CappedOutput
from app.sandbox.reports import TAIL_BYTES, decode_report, report_wrapper
from app.services.budgets import BudgetExceeded, current_budget

ALLOWED_COMMAND = ("python", "-m", "pytest", "tests", "-q")


def parse_junit(path: Path) -> dict[str, int]:
    if not path.exists() or path.stat().st_size > 2_000_000:
        return {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    failed = sum(c.find("failure") is not None for c in cases)
    errors = sum(c.find("error") is not None for c in cases)
    skipped = sum(c.find("skipped") is not None for c in cases)
    return {
        "passed": len(cases) - failed - errors - skipped,
        "failed": failed,
        "errors": errors,
        "skipped": skipped,
    }


def parse_junit_cases(path: Path) -> dict:
    if not path.exists() or path.stat().st_size > 2_000_000:
        return {"cases": [], "cases_truncated": True}
    cases = []
    for case in ET.parse(path).getroot().iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        detail = failure if failure is not None else error
        status = ("failed" if failure is not None else "error" if error is not None
                  else "skipped" if case.find("skipped") is not None else "passed")
        line = case.get("line", "")
        cases.append(TestCaseEvidence(
            file=case.get("file", "")[:500], name=case.get("name", "")[:1000],
            classname=case.get("classname", "")[:1000],
            line=int(line) + 1 if line.isdigit() else None, status=status,
            message=(detail.get("message", "") if detail is not None else "")[:2000],
            details=(detail.text or "")[:6000] if detail is not None else "",
        ).model_dump())
    # Preserve failure observations first without changing full-suite counts.
    cases.sort(key=lambda c: c["status"] not in {"failed", "error"})
    return {"cases": cases[:512], "cases_truncated": len(cases) > 512}


class DockerRunner:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, workspace: Path, command: tuple[str, ...] = ALLOWED_COMMAND) -> TestResult:
        if tuple(command) != ALLOWED_COMMAND:
            raise ValueError("Only the predefined pytest command is allowed")
        budget = current_budget()
        started = time.monotonic()
        def timeout(maximum):
            return min(maximum, budget.remaining()) if budget else maximum

        name = f"repopilot-{uuid.uuid4().hex}"
        workspace = workspace.resolve(strict=True)
        if "," in str(workspace):
            raise ValueError("Unsupported Docker mount path")
        try:
            ready = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", self.settings.sandbox_image],
                capture_output=True,
                timeout=timeout(10),
            )
            if ready.returncode:
                return TestResult(
                    status="unavailable",
                    stderr=(
                        "Docker daemon or sandbox image unavailable. Build sandbox/Dockerfile. "
                        "Host execution is disabled."
                    ),
                )
            image_id = (ready.stdout or b"").decode("utf-8", errors="replace").strip() or None
            with tempfile.TemporaryDirectory(prefix="repopilot-results-") as output:
                if os.name != "nt":
                    os.chmod(output, 0o777)
                args = [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    "--network=none",
                    "--log-driver=none",
                    "--cpus=1",
                    "--memory=512m",
                    "--memory-swap=512m",
                    "--pids-limit=64",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--user=65534:65534",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--mount",
                    f"type=bind,source={workspace},target=/workspace,readonly",
                    "--mount",
                    f"type=bind,source={Path(output).resolve()},target=/results",
                    "--workdir=/workspace",
                    "--env=PYTHONDONTWRITEBYTECODE=1",
                    "--env=PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                    "--env=PYTHONPATH=/workspace:/workspace/src",
                    "--env=HOME=/tmp",
                    self.settings.sandbox_image,
                    *command,
                    "-p",
                    "no:cacheprovider",
                    "--junitxml=/results/junit.xml",
                    "-o", "junit_family=xunit1",
                ]
                marker = ("REPOPILOT_JUNIT_" + uuid.uuid4().hex + "=").encode()
                if budget:
                    # No writable host mount. The container's report filesystem has
                    # a kernel-enforced byte limit; only a bounded XML envelope leaves it.
                    mount = args.index(f"type=bind,source={Path(output).resolve()},target=/results")
                    del args[mount - 1:mount + 1]
                    args[args.index("--workdir=/workspace"):args.index("--workdir=/workspace")] = [
                        "--tmpfs", f"/results:rw,noexec,nosuid,size={budget.limits.result_bytes},mode=1777"]
                    args.insert(2, f"--label=repopilot.task={budget.root.name}")
                    image = args.index(self.settings.sandbox_image)
                    command_args = args[image + 1:]
                    wrapper = report_wrapper(command_args, marker, timeout(self.settings.test_timeout))
                    args[image + 1:] = ["python", "-c", wrapper]
                # Drain excess output without retaining it in host memory or temporary files.
                with CappedOutput(tail_limit=TAIL_BYTES if budget else 0) as stdout, CappedOutput() as stderr:
                    result = subprocess.run(
                        args, stdout=stdout, stderr=stderr, timeout=timeout(self.settings.test_timeout)
                    )
                    stdout_bytes, stderr_bytes = stdout.finish(), stderr.finish()
                    if budget:
                        if result.returncode == 124:
                            if budget.view()["remaining_seconds"] <= 0:
                                raise BudgetExceeded("wall_seconds", "Task deadline reached in container")
                            return TestResult(status="timeout", stderr="Sandbox self-watchdog timed out",
                                              duration_seconds=time.monotonic() - started)
                        try:
                            report = decode_report(bytes(stdout.tail), marker)
                        except ValueError as exc:
                            raise BudgetExceeded("result_bytes", str(exc)) from exc
                        (Path(output) / "junit.xml").write_bytes(report)
                        stdout_bytes = stdout_bytes.split(marker, 1)[0]
                    counts = parse_junit(Path(output) / "junit.xml")
                    return TestResult(
                        status="passed"
                        if result.returncode == 0 and counts["passed"] > 0
                        else "failed",
                        exit_code=result.returncode,
                        stdout=stdout_bytes.decode("utf-8", errors="replace"),
                        stderr=stderr_bytes.decode("utf-8", errors="replace"),
                        output_truncated=stdout.truncated or stderr.truncated,
                        image_id=image_id,
                        duration_seconds=time.monotonic() - started,
                        **counts,
                        **parse_junit_cases(Path(output) / "junit.xml"),
                    )
        except FileNotFoundError:
            return TestResult(status="unavailable", stderr="Docker executable not found")
        except subprocess.TimeoutExpired:
            if budget and budget.view()["remaining_seconds"] <= 0:
                raise BudgetExceeded("wall_seconds", "Task deadline reached during Docker execution")
            return TestResult(
                status="timeout",
                stderr="Docker operation timed out",
                duration_seconds=time.monotonic() - started,
            )
        except BudgetExceeded:
            raise
        except (OSError, ValueError, ET.ParseError) as exc:
            return TestResult(
                status="failed", stderr=f"Sandbox evidence error: {type(exc).__name__}"
            )
        finally:
            try:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
