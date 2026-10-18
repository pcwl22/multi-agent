import pytest

from app.agents.contracts import literal_input_examples, validate_literal_inputs
from app.models.schemas import Edit, Patch


@pytest.mark.parametrize("expression", [
    "list(range(3))", "tuple(list(range(3)))", "list([range(3), range(4)])",
])
def test_nested_constructor_is_one_unchanged_input(expression):
    issue = f"Pass {expression} unchanged to target."
    assert literal_input_examples(issue) == [expression]
    proposal = Patch(rationale="controlled syntax test", edits=[Edit(
        path="tests/test_new.py", old="",
        new=f"def test_example():\n    assert target({expression}) == 3\n",
    )])
    validate_literal_inputs(issue, proposal)


def test_nested_and_separate_constructor_examples_remain_distinct():
    issue = "Pass list(range(3)) to target; also support range(3) directly."
    assert literal_input_examples(issue) == ["list(range(3))", "range(3)"]
    proposal = Patch(rationale="controlled syntax test", edits=[Edit(
        path="tests/test_new.py", old="",
        new="def test_example():\n    assert target(list(range(3))) == 3\n",
    )])
    with pytest.raises(ValueError, match="unchanged"):
        validate_literal_inputs(issue, proposal)


def test_outer_type_conversion_still_cannot_replace_nested_example():
    proposal = Patch(rationale="controlled syntax test", edits=[Edit(
        path="tests/test_new.py", old="",
        new="def test_example():\n    assert target(tuple(list(range(3)))) == 3\n",
    )])
    with pytest.raises(ValueError, match="unchanged"):
        validate_literal_inputs("Pass list(range(3)) unchanged.", proposal)
