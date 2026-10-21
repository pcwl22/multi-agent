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
