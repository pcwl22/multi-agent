"""Bounded workspace metadata; model edit paths are never rewritten."""
from app.tools.repository import Repository

MAX_SCOPE_PATHS = 80


def repository_path_scope(repo: Repository, remote_subdirectory: str) -> dict[str, object]:
    paths = repo.list_files()
    shown = paths[:MAX_SCOPE_PATHS]
    return {
        "remote_subdirectory": remote_subdirectory,
        "workspace_paths": shown,
        "paths_truncated": len(paths) > MAX_SCOPE_PATHS,
        "path_mapping": [
            {"remote_path": f"{remote_subdirectory}/{path}" if remote_subdirectory else path,
             "workspace_edit_path": path}
            for path in shown
        ],
        "instruction": (
            "The workspace root is already the configured remote subdirectory. "
            "Use workspace_edit_path and FILE markers for suspected_modules and Edit.path. "
            "Do not prepend remote_subdirectory. New Python test files use this same root. "
            "Existing tests and edit preconditions remain protected."
        ),
    }
