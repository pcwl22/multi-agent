def merge_config(defaults, overrides):
    result = dict(defaults)
    result.update(overrides)
    return result
