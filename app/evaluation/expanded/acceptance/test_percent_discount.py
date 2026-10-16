import pytest
from pricing import discounted_total


@pytest.mark.parametrize(
    "amount,discount,expected",
    [(100, 20, 80), (25, 100, 0), (12.5, 10, 11.25), (0, 75, 0), (100, 0, 100)],
)
def test_discount(amount, discount, expected):
    assert discounted_total(amount, discount) == expected
