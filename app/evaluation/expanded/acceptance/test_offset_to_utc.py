import pytest
from events import parse_event_time


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-04-01T12:00:00+02:00", "2026-04-01T10:00:00+00:00"),
        ("2026-04-01T00:15:00+05:30", "2026-03-31T18:45:00+00:00"),
        ("2026-04-01T12:00:00-04:00", "2026-04-01T16:00:00+00:00"),
        ("2026-04-01T12:00:00", "2026-04-01T12:00:00+00:00"),
    ],
)
def test_offsets(value, expected):
    assert parse_event_time(value).isoformat() == expected
