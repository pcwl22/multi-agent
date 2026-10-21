import pytest
from cache import is_expired


@pytest.mark.parametrize(
    "created,ttl,now,expected",
    [
        (10, 5, 15, True),
        (10, 0, 10, True),
        (10, 5, 14.999, False),
        (10, 5, 15.001, True),
        (0, 0.5, 0.5, True),
    ],
)
def test_expiry(created, ttl, now, expected):
    assert is_expired(created, ttl, now) is expected
