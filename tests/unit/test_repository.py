from pathlib import Path

import pytest

from app.agents.model import MockModel
from app.models.schemas import Edit, Patch, Plan
from app.tools.repository import Repository, diff_repositories, snapshot


@pytest.fixture
def copied(tmp_path):
    source = Repository(Path(__file__).parents[2] / "test_fixtures" / "repair_repository")
    snapshot(source, tmp_path / "baseline")
    snapshot(source, tmp_path / "workspace")
    return Repository(tmp_path / "workspace")


def test_search_symbol_and_dependencies(copied):
    assert copied.search_code("expired")[0]["path"] == "auth.py"
    assert copied.find_symbol("authenticate")[0]["line"] == 6
    assert "requirements.txt" in copied.inspect_dependencies()


def test_mock_plan_and_patch(copied):
    plan, stats = MockModel().generate(Plan, {"issue_description": "expired token"})
    assert plan.validation_strategy
    assert stats["calls"] == 0
    patch, _ = MockModel().generate(Patch, {"context": copied.read_file("auth.py")})
    copied.apply(patch)
    diff = diff_repositories(copied.root.parent / "baseline", copied.root)
    assert "+        raise HTTPException(status_code=401" in diff
    assert "+def test_expired_token_returns_401" in diff


@pytest.mark.parametrize(
    "path",
    [
        "../outside.py",
        "/tmp/x",
        "C:\\x.py",
        ".git/config",
        "a/../../x",
        ".env",
        ".env.local",
        "a/.aws/key",
    ],
)
def test_path_restrictions(copied, path):
    with pytest.raises(ValueError):
        copied.path(path, existing=False)


def test_preconditions_and_test_protection(copied):
    with pytest.raises(ValueError, match="immutable"):
        copied.apply(
            Patch(rationale="bad", edits=[Edit(path="tests/test_auth.py", old="401", new="500")])
        )
    with pytest.raises(ValueError, match="exactly once"):
        copied.apply(Patch(rationale="bad", edits=[Edit(path="auth.py", old="zzz", new="x")]))


def test_validation_precedes_writes(copied):
    before = copied.read_file("auth.py")
    with pytest.raises(SyntaxError):
        copied.apply(
            Patch(
                rationale="bad",
                edits=[
                    Edit(path="auth.py", old="status_code=500", new="status_code=401"),
                    Edit(path="new.py", old="", new="def broken("),
                ],
            )
        )
    assert copied.read_file("auth.py") == before


def test_symlink_escape(copied, tmp_path):
    outside = tmp_path / "secret.py"
    outside.write_text("secret", encoding="utf8")
    try:
        (copied.root / "link.py").symlink_to(outside)
    except OSError:
        pytest.skip("OS does not permit symlinks")
    with pytest.raises(ValueError):
        copied.read_file("link.py")


@pytest.mark.parametrize(
    "path",
    [
        ".GIT/config",
        ".ENV",
        "nul.py",
        "aux.py",
        "x:stream.py",
        "folder./file.py",
        "folder /file.py",
    ],
)
def test_windows_aliases_rejected(copied, path):
    with pytest.raises(ValueError):
        copied.path(path, existing=False)
