from inventory import available_units


def test_repeated():
    stock = {"A": 10, "B": 4}
    reservations = [("A", 2), ("A", 3), ("B", 8), ("unknown", 1)]
    assert available_units(stock, reservations) == {"A": 5, "B": 0}
    assert stock == {"A": 10, "B": 4}
    assert len(reservations) == 4


def test_empty():
    assert available_units({"A": 3}, []) == {"A": 3}
