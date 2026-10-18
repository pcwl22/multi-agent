from app.agents.scope import MAX_SCOPE_PATHS, repository_path_scope
from app.tools.repository import Repository


def test_subdirectory_mapping_keeps_edit_paths_relative_and_secrets_hidden(tmp_path):
    (tmp_path / "auth.py").write_text("value = 1\n")
    (tmp_path / ".env").write_text("PRIVATE_TEST_VALUE=never-send\n")
    scope = repository_path_scope(Repository(tmp_path), "packages/service")
    assert scope["workspace_paths"] == ["auth.py"]
    assert scope["path_mapping"] == [
        {"remote_path": "packages/service/auth.py", "workspace_edit_path": "auth.py"}]
    assert str(tmp_path) not in str(scope)
    assert "never-send" not in str(scope)


def test_scope_inventory_is_bounded_and_root_mapping_has_no_slash_prefix(tmp_path):
    for index in range(MAX_SCOPE_PATHS + 1):
        (tmp_path / f"module_{index:03d}.py").write_text("value = 1\n")
    scope = repository_path_scope(Repository(tmp_path), "")
    assert len(scope["workspace_paths"]) == MAX_SCOPE_PATHS
    assert scope["paths_truncated"] is True
    assert all(item["remote_path"] == item["workspace_edit_path"]
               for item in scope["path_mapping"])
