from pricing import discounted_total


def test_existing_contract():
    assert discounted_total(0, 20) == 0
    assert discounted_total(12.5, 0) == 12.5
