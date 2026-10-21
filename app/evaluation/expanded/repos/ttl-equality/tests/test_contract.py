from cache import is_expired


def test_existing_contract():
    assert not is_expired(10, 5, 14)
    assert is_expired(10, 5, 16)
