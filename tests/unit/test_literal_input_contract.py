import pytest

from app.agents.contracts import literal_input_examples, validate_literal_inputs
from app.models.schemas import Edit, Patch


def patch(code):
    return Patch(rationale="test", edits=[Edit(path="tests/test_new.py", old="", new=code)])


def test_literal_input_cannot_be_hidden_behind_type_conversion():
    issue = "For range(1,8), page 2 size 2 must return [3,4]."
    with pytest.raises(ValueError, match="unchanged"):
        validate_literal_inputs(issue, patch(
            "def test_example():\n    assert paginate(list(range(1,8)), 2, 2) == [3,4]\n"))
    validate_literal_inputs(issue, patch(
        "def test_example():\n    assert paginate(range(1,8), 2, 2) == [3,4]\n"))


def test_generic_constructor_example_supports_local_binding_and_keywords():
    issue = "Call process with tuple([1, 2]) as the input."
    validate_literal_inputs(issue, patch(
        "def test_example():\n    items = tuple([1, 2])\n    assert process(items=items) == 3\n"))
    with pytest.raises(ValueError, match="unchanged"):
        validate_literal_inputs(issue, patch(
            "def test_example():\n    assert process(list(tuple([1, 2]))) == 3\n"))


def test_repository_code_is_never_executed_or_evaluated():
    assert literal_input_examples("range(__import__('os').system('command'))") == []
    assert literal_input_examples("range(1, 8); then bytes([1,2])") == [
        "range(1, 8)", "bytes([1,2])"]
    validate_literal_inputs("A normal prose issue", patch("invalid syntax is handled by apply"))


def test_source_only_retry_reuses_existing_literal_coverage_without_editing_tests():
    existing = {"tests/test_previous_attempt.py":
                "def test_example():\n    assert paginate(range(1, 8), 2, 2) == [3, 4]\n"}
    source_patch = Patch(rationale="source correction after a real failure", edits=[
        Edit(path="pagination.py", old="return items[start:end]", new="return list(items[start:end])")
    ])
    validate_literal_inputs("For range(1,8), return [3,4]", source_patch, existing)
    with pytest.raises(ValueError, match="unchanged"):
        validate_literal_inputs("For range(1,8), return [3,4]", source_patch, {
            "tests/test_previous_attempt.py":
                "def test_example():\n    assert paginate(list(range(1,8)), 2, 2) == [3,4]\n"
        })
