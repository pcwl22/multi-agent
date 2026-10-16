from app.agents.pacing import RequestPacer, endpoint_pacer


def test_endpoint_registry_coordinates_instances_without_credentials():
    assert endpoint_pacer("https://example.test/v1/") is endpoint_pacer("https://example.test/v1")
    assert endpoint_pacer("https://other.test/v1") is not endpoint_pacer("https://example.test/v1")


def test_spacing_reserves_starts_and_zero_interval_does_not_sleep(monkeypatch):
    clock = [100.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("app.agents.pacing.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.agents.pacing.time.sleep", sleep)
    pacer = RequestPacer()
    assert pacer.wait(7.5) == 0
    clock[0] += 2
    assert pacer.wait(7.5) == 5.5
    assert pacer.wait(7.5) == 7.5
    assert pacer.wait(0) == 0
    assert waits == [5.5, 7.5]


def test_calls_after_idle_do_not_accumulate_a_burst(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("app.agents.pacing.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.agents.pacing.time.sleep", lambda seconds: None)
    pacer = RequestPacer()
    assert pacer.wait(7.5) == 0
    clock[0] = 1000
    assert pacer.wait(7.5) == 0
    assert pacer.next_start == 1007.5
