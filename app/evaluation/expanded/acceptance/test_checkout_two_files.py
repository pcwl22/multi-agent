import pytest
from checkout import invoice_total
from money import discounted


@pytest.mark.parametrize(
    "amount,discount,tax,expected",
    [(100, 20, 0.1, 88), (25, 100, 0.2, 0), (100, 0, 0.1, 110), (80, 25, 0, 60)],
)
def test_invoice(amount, discount, tax, expected):
    assert invoice_total(amount, discount, tax) == expected


def test_public_discount():
    assert discounted(100, 20) == 80
    assert discounted(25, 100) == 0
