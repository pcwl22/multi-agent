from checkout import invoice_total
from money import discounted


def test_existing_contract():
    assert discounted(100, 0) == 100
    assert invoice_total(100, 0, 0.1) == 110
    assert invoice_total(0, 20, 0.1) == 0
