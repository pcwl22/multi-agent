from pathlib import Path

import pytest

from app.models.schemas import Edit, Patch
from app.tools.repository import Repository


def test_multibyte_new_file_cannot_disappear_from_diff(tmp_path: Path):
    repo = Repository(tmp_path)
    # The schema allows this character count, but UTF-8 exceeds the repository byte budget.
    content = "# " + "中" * 34000 + "\n"
    patch = Patch(rationale="oversized fixture", edits=[Edit(path="large.py", old="", new=content)])
    with pytest.raises(ValueError, match="100000-byte"):
        repo.apply(patch)
    assert not (tmp_path / "large.py").exists()


def test_growing_existing_source_is_checked_before_any_write(tmp_path: Path):
    (tmp_path / "small.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "large.py").write_text("# " + "a" * 90000 + "\nx = 1\n", encoding="utf-8")
    repo = Repository(tmp_path)
    patch = Patch(
        rationale="size limit fixture",
        edits=[
            Edit(path="small.py", old="value = 1", new="value = 2"),
            Edit(path="large.py", old="x = 1", new="x = 1\n# " + "b" * 15000),
        ],
    )
    with pytest.raises(ValueError, match="100000-byte"):
        repo.apply(patch)
    assert repo.read_file("small.py") == "value = 1\n"
    assert (tmp_path / "large.py").stat().st_size < 100000
