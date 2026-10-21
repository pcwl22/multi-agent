from auth import authenticate


def test_existing_contract():
    assert authenticate("valid") == (200, "alice")
    assert authenticate(None) == (401, "missing")
