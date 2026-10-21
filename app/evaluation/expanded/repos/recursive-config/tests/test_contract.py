from config import merge_config


def test_existing_contract():
    assert merge_config({"a": 1}, {"a": 2, "b": 3}) == {"a": 2, "b": 3}
    assert merge_config({}, {}) == {}
