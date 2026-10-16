"""Export only RepoPilot's installed dependency closure, not the global environment."""

import platform
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pending = [
        Requirement(r) for r in project["dependencies"] + project["optional-dependencies"]["dev"]
    ]
    seen = set()
    versions = {}
    while pending:
        req = pending.pop()
        key = (canonicalize_name(req.name), frozenset(req.extras))
        dist = metadata.distribution(req.name)
        if not req.specifier.contains(dist.version, prereleases=True):
            raise ValueError(f"Installed dependency mismatch: {req}, found {dist.version}")
        if key in seen:
            continue
        seen.add(key)
        versions[key[0]] = dist.version
        for value in dist.requires or []:
            dependency = Requirement(value)
            if dependency.marker is None or any(
                dependency.marker.evaluate({"extra": extra}) for extra in {"", *req.extras}
            ):
                pending.append(dependency)
    lines = [
        "# Generated from the tested dependency closure by scripts/lock_verified_environment.py",
        f"# Python {platform.python_version()} / {platform.system()}; no API keys or local paths.",
        "# pywin32 is platform-scoped; validate other platforms with CI.",
    ]
    for name, version in sorted(versions.items()):
        marker = '; sys_platform == "win32"' if name == "pywin32" else ""
        lines.append(f"{name}=={version}{marker}")
    content = "\n".join(lines) + "\n"
    (root / "requirements.lock").write_text(content, encoding="utf-8")
    (root / "docs/verified-environment.txt").write_text(content, encoding="utf-8")
    print(f"Exported {len(versions)} verified dependencies")


if __name__ == "__main__":
    main()
