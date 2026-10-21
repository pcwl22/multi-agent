"""Explicit opt-in wire dialect; never infer capabilities from a model alias."""
from typing import Literal

TokenParameter = Literal['max_completion_tokens', 'max_tokens']
ThinkingMode = Literal['provider_default', 'disabled']


def output_options(limit: int | None, parameter: TokenParameter, thinking: ThinkingMode) -> dict:
    extra = {}
    if parameter == 'max_tokens' and limit is not None:
        # ChatOpenAI rewrites its own max_tokens field. SDK extra_body merges this
        # legacy key at the HTTP JSON root without sending BOTH limit parameters.
        extra['max_tokens'] = limit
    if thinking == 'disabled':
        extra['thinking'] = {'type': 'disabled'}
    options = {}
    if limit is not None or parameter == 'max_tokens':
        options['max_tokens'] = limit if parameter == 'max_completion_tokens' else None
    if extra:
        options['extra_body'] = extra
    return options
