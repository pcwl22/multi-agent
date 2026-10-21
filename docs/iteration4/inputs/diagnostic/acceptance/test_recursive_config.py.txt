from config import merge_config


def test_nested():
    defaults = {"db": {"host": "local", "pool": {"min": 1, "max": 8}}, "tags": ["a"]}
    overrides = {"db": {"pool": {"max": 4}}}
    actual = merge_config(defaults, overrides)
    assert actual == {"db": {"host": "local", "pool": {"min": 1, "max": 4}}, "tags": ["a"]}
    actual["db"]["pool"]["max"] = 99
    actual["tags"].append("b")
    assert defaults == {"db": {"host": "local", "pool": {"min": 1, "max": 8}}, "tags": ["a"]}
    assert overrides == {"db": {"pool": {"max": 4}}}


def test_lists_replaced_and_copied():
    overrides = {"tags": ["new"]}
    actual = merge_config({"tags": ["old"]}, overrides)
    actual["tags"].append("x")
    assert overrides == {"tags": ["new"]}
