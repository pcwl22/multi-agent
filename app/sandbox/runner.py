import os
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from app.config.settings import Settings
from app.models.schemas import TestResult
from app.sandbox.output import CappedOutput

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


class DockerRunner:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, workspace: Path, command: tuple[str, ...] = ALLOWED_COMMAND) -> TestResult:
        if tuple(command) != ALLOWED_COMMAND:
            raise ValueError("Only the predefined pytest command is allowed")
        started = time.monotonic()
        name = f"repopilot-{uuid.uuid4().hex}"
        workspace = workspace.resolve(strict=True)
        if "," in str(workspace):
            raise ValueError("Unsupported Docker mount path")
        try:
            ready = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", self.settings.sandbox_image],
                capture_output=True,
                timeout=10,
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
                ]
                # Drain excess output without retaining it in host memory or temporary files.
                with CappedOutput() as stdout, CappedOutput() as stderr:
                    result = subprocess.run(
                        args, stdout=stdout, stderr=stderr, timeout=self.settings.test_timeout
                    )
                    stdout_bytes, stderr_bytes = stdout.finish(), stderr.finish()
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
                    )
        except FileNotFoundError:
            return TestResult(status="unavailable", stderr="Docker executable not found")
        except subprocess.TimeoutExpired:
            return TestResult(
                status="timeout",
                stderr="Docker operation timed out",
                duration_seconds=time.monotonic() - started,
            )
        except (OSError, ET.ParseError) as exc:
            return TestResult(
                status="failed", stderr=f"Sandbox evidence error: {type(exc).__name__}"
            )
        finally:
            try:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass
