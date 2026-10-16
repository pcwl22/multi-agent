import pytest
from pagination import paginate


@pytest.mark.parametrize(
    "page,size,expected",
    [(1, 2, [1, 2]), (2, 2, [3, 4]), (4, 2, [7]), (5, 2, []), (0, 2, []), (1, 0, [])],
)
def test_pages(page, size, expected):
    assert paginate(list(range(1, 8)), page, size) == expected


@pytest.mark.parametrize("page,size,expected", [(1,2,[1,2]),(2,2,[3,4]),(4,2,[7]),(5,2,[])])
def test_range_input_returns_list(page, size, expected):
    assert paginate(range(1,8), page, size) == expected
