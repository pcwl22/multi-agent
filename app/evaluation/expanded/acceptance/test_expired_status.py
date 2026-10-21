import pytest
from auth import authenticate


@pytest.mark.parametrize(
    "token,expected",
    [
        ("expired", (401, "expired")),
        ("valid", (200, "alice")),
        (None, (401, "missing")),
        ("", (401, "missing")),
    ],
)
def test_auth(token, expected):
    assert authenticate(token) == expected
