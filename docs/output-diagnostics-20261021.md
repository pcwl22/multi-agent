# Structured output limits and diagnostics

Budgeted model calls keep the existing 4096-token per-response ceiling when no
explicit setting is supplied. A deployment can opt into a different bounded
ceiling for new requests:

```dotenv
REPOPILOT_MODEL_MAX_OUTPUT_TOKENS=8192
```

The setting accepts 1 through 32768. The remaining observed-token task allowance
can lower it. Unbudgeted calls retain the previous provider default when the
setting is unset. This ceiling is not a monetary cap: input tokens, reasoning
tokens and provider accounting can affect actual usage. SDK retries remain
disabled for budgeted or circuit-gated calls.

Each returned response records a bounded structured-output observation: schema
category, allowlisted finish reason, parsed/invalid/missing status, and applied
output ceiling. Raw response content, tool arguments, parser exception messages,
provider messages and arbitrary finish-reason strings are excluded.

A provider-reported `finish_reason=length` stops the generation immediately with
`output_failure.kind=output_truncated`, including when a partial result parses.
It does not automatically resend the same request or open the provider connection
circuit. Usage already received is retained; absent usage remains unknown and
continues to block further dispatch under the task budget. Other invalid schema
responses retain the existing maximum of two explicit attempts, both charged to
the same task budget, and report `schema_invalid` if exhausted.

The first live calibration on the new channel observed failed schema validation
and responses consuming the full 4096 output-token allowance, but the previous
runtime did not save a finish reason. Those observations alone do not establish
truncation. New diagnostics are needed before attributing that historical failure
to a token limit. Controlled HTTP/SSE tests are not evidence of live repair gains.

Use short task-storage paths for Windows calibration. The first new-channel
controller used a long descriptive path and encountered WinError 206 before a
task workspace was created. Keep that failed batch sealed, record creation
failure even without a workspace, and use a separately frozen new batch rather
than resuming it. This change does not add general Windows long-path support.
