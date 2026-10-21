from events import parse_event_time


def test_existing_contract():
    assert parse_event_time("2026-04-01T12:00:00Z").isoformat() == "2026-04-01T12:00:00+00:00"
    assert parse_event_time("2026-04-01T12:00:00").hour == 12
