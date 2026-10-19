import ast
import difflib
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from app.models.schemas import Patch

IGNORED = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".repopilot",
    ".env",
    ".aws",
    ".ssh",
    ".codex",
    ".agents",
    ".pytest_cache",
}
SUFFIXES = {".py", ".toml", ".txt", ".md", ".json", ".yaml", ".yml", ".js", ".ts"}


def is_test_file(relative: str | Path) -> bool:
    parts = str(relative).replace("\\", "/").casefold().split("/")
    name = parts[-1]
    return (
        "tests" in parts or name in {"test.py", "tests.py", "conftest.py"}
        or name.startswith("test_") or name.endswith("_test.py")
    )


class Repository:
    """Bounded text operations; never import or execute target repository code."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Repository must be a directory")

    def path(self, relative: str, *, existing: bool = True) -> Path:
        normalized = relative.replace("\\", "/")
        parts = PurePosixPath(normalized).parts
        if (
            not parts
            or PurePosixPath(normalized).is_absolute()
            or any(
                p in {"..", "."} or ":" in p or "\x00" in p or p.endswith((".", " ")) for p in parts
            )
            or any(p.casefold() in IGNORED or p.casefold().startswith(".env") for p in parts)
            or any(
                p.split(".")[0].casefold()
                in {
                    "con",
                    "prn",
                    "aux",
                    "nul",
                    *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10)),
                }
                for p in parts
            )
        ):
            raise ValueError("Forbidden repository path")
        candidate = self.root.joinpath(*parts)
        for item in [candidate, *candidate.parents]:
            if item == self.root:
                break
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise ValueError("Links and junctions are forbidden")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.root) or resolved == self.root:
            raise ValueError("Path escapes repository")
        if existing and not resolved.is_file():
            raise ValueError("File does not exist")
        if resolved.exists() and resolved.stat().st_nlink > 1:
            raise ValueError("Hard links are forbidden")
        return resolved

    def list_files(self) -> list[str]:
        files = []
        scanned = 0
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(
                d
                for d in dirs
                if d.casefold() not in IGNORED
                and not Path(directory, d).is_symlink()
                and not (
                    hasattr(Path(directory, d), "is_junction") and Path(directory, d).is_junction()
                )
            )
            for name in sorted(names):
                scanned += 1
                if scanned > 10000:
                    raise ValueError("Repository exceeds 10000-file scan limit")
                p = Path(directory, name)
                if p.suffix not in SUFFIXES:
                    continue
                rel = p.relative_to(self.root).as_posix()
                try:
                    checked = self.path(rel)
                    if checked.stat().st_size <= 100000:
                        files.append(rel)
                except ValueError:
                    continue
        return sorted(files)

    def read_file(self, path: str, max_chars: int = 16000) -> str:
        if not 1 <= max_chars <= 100000:
            raise ValueError("Invalid read budget")
        p = self.path(path)
        if p.stat().st_size > 100000:
            raise ValueError("File exceeds read limit")
        return p.read_text(encoding="utf-8")[:max_chars]

    def search_code(self, keyword: str, limit: int = 30) -> list[dict]:
        if not keyword or len(keyword) > 200 or not 1 <= limit <= 100:
            raise ValueError("Invalid search limits")
        matches = []
        for path in self.list_files():
            try:
                lines = self.read_file(path, 100000).splitlines()
            except UnicodeError:
                continue
            for line, text in enumerate(lines, 1):
                if keyword.casefold() in text.casefold():
                    matches.append({"path": path, "line": line, "text": text[:300]})
                    if len(matches) >= limit:
                        return matches
        return matches

    def find_symbol(self, symbol: str) -> list[dict]:
        found = []
        for path in self.list_files():
            if not path.endswith(".py"):
                continue
            try:
                tree = ast.parse(self.read_file(path, 100000))
            except (SyntaxError, UnicodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == symbol:
                        found.append({"path": path, "line": node.lineno, "symbol": symbol})
        return found[:100]

    def inspect_dependencies(self) -> dict[str, str]:
        return {
            p: self.read_file(p, 8000)
            for p in self.list_files()
            if p in {"pyproject.toml", "requirements.txt", "package.json"}
        }

    def stage(self, patch: Patch) -> dict[Path, str]:
        staged: dict[Path, str] = {}
        for edit in patch.edits:
            p = self.path(edit.path, existing=False)
            if p in staged:
                raise ValueError("One edit per file is required")
            if p.suffix != ".py":
                raise ValueError("MVP permits Python source and new Python tests only")
            is_test = is_test_file(p.relative_to(self.root))
            if p.name.casefold() == "conftest.py":
                raise ValueError("Pytest configuration is immutable")
            if is_test and p.exists():
                raise ValueError("Existing tests are immutable")
            if p.exists() and p.stat().st_size > 100000:
                raise ValueError("File exceeds edit limit")
            original = p.read_text(encoding="utf-8") if p.exists() else ""
            if edit.old:
                if original.count(edit.old) != 1:
                    raise ValueError("Edit precondition must match exactly once")
                updated = original.replace(edit.old, edit.new, 1)
            else:
                if p.exists():
                    raise ValueError("Empty old content only allowed for new files")
                updated = edit.new
            if updated == original or not updated.strip():
                raise ValueError("Empty or no-op edit")
            if len(updated.encode("utf-8")) > 100000:
                raise ValueError("Updated file exceeds 100000-byte edit limit")
            ast.parse(updated)
            staged[p] = updated
        return staged

    def apply(self, patch: Patch) -> list[str]:
        staged = self.stage(patch)
        for p, updated in staged.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(updated, encoding="utf-8", newline="\n")
        return [p.relative_to(self.root).as_posix() for p in staged]

    def git_diff(self) -> str:
        # No repository hooks, external diff drivers or textconv are executed.
        metadata = self.root / ".git"
        if not metadata.is_dir() or metadata.is_symlink():
            raise ValueError("Git diff requires a local .git directory (no linked worktrees)")
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                "--no-pager",
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--",
                ".",
            ],
            cwd=self.root,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        )
        if result.returncode:
            raise ValueError("Git diff unavailable (repository may not be initialized)")
        return result.stdout[:200000]


def snapshot(source: Repository, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    size = 0
    for relative in source.list_files():
        src = source.path(relative)
        size += src.stat().st_size
        if size > 20_000_000:
            raise ValueError("Snapshot exceeds 20 MB limit")
        dst = destination / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def diff_repositories(before: Path, after: Path) -> str:
    a, b = Repository(before), Repository(after)
    chunks = []
    for path in sorted(set(a.list_files()) | set(b.list_files())):
        old = a.read_file(path, 100000) if (before / path).exists() else ""
        new = b.read_file(path, 100000) if (after / path).exists() else ""
        if old != new:
            lines = difflib.unified_diff(
                old.splitlines(True),
                new.splitlines(True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
            for line in lines:
                chunks.append(
                    line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                )
    return "".join(chunks)


def digest(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def keywords(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"[A-Za-z_][A-Za-z_0-9]{2,40}", text)))[:12]
