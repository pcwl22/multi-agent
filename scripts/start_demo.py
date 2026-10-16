"""Start the local API and Streamlit together; Ctrl+C stops both owned children."""

import argparse
import getpass
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", default="deepseek-v4.1-flash")
    parser.add_argument("--base-url", default="https://muyuan.do/v1")
    parser.add_argument("--repository", type=Path, default=root / "demo_repository")
    parser.add_argument("--data", type=Path, default=root / ".repopilot/demo-session")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--ui-port", type=int, default=8501)
    parser.add_argument("--interval", type=float, default=7.5)
    parser.add_argument("--retry-workspace-policy", choices=["preserve", "isolated"],
                        default="preserve")
    args = parser.parse_args()
    if args.api_port == args.ui_port:
        parser.error("API and UI ports must differ")
    for port in (args.api_port, args.ui_port):
        if not 1024 <= port <= 65535:
            parser.error("Use ports between 1024 and 65535")
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"Port {port} is occupied; choose another port")
    source = args.repository.resolve(strict=True)
    data = args.data.resolve()
    if data.is_relative_to(source) or source.is_relative_to(data):
        parser.error("Repository and task storage must not overlap")
    if not 0 <= args.interval <= 60:
        parser.error("Interval must be between 0 and 60 seconds")
    data.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "REPOPILOT_REPOSITORY_ROOT": str(source),
            "REPOPILOT_DATA_DIR": str(data),
            "REPOPILOT_MODEL_MODE": "live" if args.live else "mock",
            "REPOPILOT_MODEL_NAME": args.model,
            "REPOPILOT_MODEL_BASE_URL": args.base_url,
            "REPOPILOT_MODEL_MIN_INTERVAL": str(args.interval),
            "REPOPILOT_MODEL_TIMEOUT": "120",
            "REPOPILOT_RETRY_WORKSPACE_POLICY": args.retry_workspace_policy,
        }
    )
    if args.live and not env.get("OPENAI_API_KEY"):
        env["OPENAI_API_KEY"] = getpass.getpass("Provider API key (hidden): ")
        if not env["OPENAI_API_KEY"]:
            parser.error("Live mode requires a credential")
    # Child processes receive only the credentials they need. Never print env.
    ui_env = {
        k: v
        for k, v in env.items()
        if k not in {"OPENAI_API_KEY", "GITHUB_TOKEN", "LANGSMITH_API_KEY"}
    }
    ui_env["REPOPILOT_API_URL"] = f"http://127.0.0.1:{args.api_port}"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    children = []
    try:
        with (data / "api.log").open("ab") as api_log, (data / "ui.log").open("ab") as ui_log:
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.api.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(args.api_port),
                        "--workers",
                        "1",
                    ],
                    cwd=root,
                    env=env,
                    stdout=api_log,
                    stderr=api_log,
                    creationflags=flags,
                )
            )
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "streamlit",
                        "run",
                        str(root / "frontend/demo.py"),
                        "--server.address",
                        "127.0.0.1",
                        "--server.port",
                        str(args.ui_port),
                        "--server.headless",
                        "true",
                        "--browser.gatherUsageStats",
                        "false",
                    ],
                    cwd=root,
                    env=ui_env,
                    stdout=ui_log,
                    stderr=ui_log,
                    creationflags=flags,
                )
            )
            env.pop("OPENAI_API_KEY", None)
            print(f"UI: http://127.0.0.1:{args.ui_port}", flush=True)
            print(f"API: http://127.0.0.1:{args.api_port}/docs", flush=True)
            print(f"Logs: {data}; Ctrl+C stops this session.", flush=True)
            while all(child.poll() is None for child in children):
                time.sleep(0.5)
            raise SystemExit("A demo process exited. Inspect the session logs.")
    except KeyboardInterrupt:
        print("Stopping demo session.", flush=True)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
