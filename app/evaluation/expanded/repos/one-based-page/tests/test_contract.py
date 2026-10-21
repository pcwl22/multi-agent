from pagination import paginate


def test_existing_contract():
    assert paginate([], 1, 2) == []
    assert paginate([1, 2], 0, 2) == []
