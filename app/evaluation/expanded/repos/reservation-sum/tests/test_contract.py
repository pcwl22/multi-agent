from inventory import available_units


def test_existing_contract():
    assert available_units({"A": 10}, [("A", 2)]) == {"A": 8}
    assert available_units({}, []) == {}
