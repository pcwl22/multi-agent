"""Allowlisted structured-output observations, without response or parser text."""
from typing import Literal

from pydantic import Field

from app.models.schemas import StrictModel


class StructuredOutputObservation(StrictModel):
    schema_name: Literal['Plan', 'Patch', 'Review', 'other']
    finish_reason: Literal['stop', 'length', 'tool_calls', 'function_call', 'content_filter', 'other', 'unknown']
    parse_status: Literal['parsed', 'invalid', 'missing']
    output_limit: int | None = Field(default=None, ge=1, le=32768)


def observe_output(schema_name: str, metadata: dict, parse_status: str,
                   output_limit: int | None) -> dict:
    reason = metadata.get('finish_reason')
    return StructuredOutputObservation(
        schema_name=schema_name if schema_name in {'Plan', 'Patch', 'Review'} else 'other',
        finish_reason=(reason if isinstance(reason, str) and reason in {
            'stop', 'length', 'tool_calls', 'function_call', 'content_filter'
        } else 'unknown' if reason is None else 'other'),
        parse_status=parse_status, output_limit=output_limit,
    ).model_dump()


class ResponseShape(StrictModel):
    text_characters: int = Field(ge=0, le=10000000)
    text_measurement: Literal['complete', 'capped', 'unavailable']
    tool_calls: int = Field(ge=0, le=128)
    invalid_tool_calls: int = Field(ge=0, le=128)
    tool_count_capped: bool
    reasoning_tokens: int | None = Field(default=None, ge=0)
    reasoning_status: Literal['reported', 'missing', 'invalid']


def response_shape(raw) -> dict:
    """Count SDK-visible fields only; provider-specific reasoning text is not read."""
    content = getattr(raw, 'content', None)
    chars, measurement = 0, 'unavailable'
    if isinstance(content, str):
        chars, measurement = len(content), 'complete'
    elif isinstance(content, list):
        measurement = 'complete' if len(content) <= 128 else 'capped'
        for block in content[:128]:
            if isinstance(block, str):
                chars += len(block)
            elif isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str):
                chars += len(block['text'])
            else:
                measurement = 'capped'  # Other block kinds are not interpreted.
    if chars > 10000000:
        chars, measurement = 10000000, 'capped'
    tools, invalid = getattr(raw, 'tool_calls', []), getattr(raw, 'invalid_tool_calls', [])
    n_tools = len(tools) if isinstance(tools, list) else 0
    n_invalid = len(invalid) if isinstance(invalid, list) else 0
    usage = getattr(raw, 'usage_metadata', None)
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get('output_token_details')
    details = details if isinstance(details, dict) else {}
    reasoning = details.get('reasoning')
    total = usage.get('output_tokens')
    status = 'missing'
    if reasoning is not None:
        if type(reasoning) is int and type(total) is int and 0 <= reasoning <= total:
            status = 'reported'
        else:
            reasoning, status = None, 'invalid'
    return ResponseShape(text_characters=chars, text_measurement=measurement,
        tool_calls=min(n_tools, 128), invalid_tool_calls=min(n_invalid, 128),
        tool_count_capped=n_tools > 128 or n_invalid > 128,
        reasoning_tokens=reasoning, reasoning_status=status).model_dump()
