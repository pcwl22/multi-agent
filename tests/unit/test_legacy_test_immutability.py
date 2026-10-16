import pytest

from app.models.schemas import Edit, Patch
from app.tools.repository import Repository, is_test_file


@pytest.mark.parametrize("name", ["tests.py", "test.py", "example_test.py", "tests/example.py"])
def test_nonstandard_existing_tests_cannot_be_modified(tmp_path, name):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("assert False\n", encoding="utf8")
    assert is_test_file(name)
    with pytest.raises(ValueError, match="immutable"):
        Repository(tmp_path).apply(Patch(rationale="must reject", edits=[
            Edit(path=name, old="assert False", new="assert True")
        ]))
    assert path.read_text(encoding="utf8") == "assert False\n"
