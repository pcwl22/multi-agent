# Explicit provider request compatibility

The default remains ChatOpenAI's `max_completion_tokens` dialect and the
provider's default thinking behavior. The deployed alias does not select or prove
provider capabilities. Two settings are opt-in:

```dotenv
REPOPILOT_MODEL_OUTPUT_TOKEN_PARAMETER=max_tokens
REPOPILOT_MODEL_THINKING=disabled
```

The first setting uses the SDK's `extra_body` root merge to send the legacy
`max_tokens` field without also sending `max_completion_tokens`. The same
per-response ceiling and remaining observed-token task allowance apply. Unset
unbudgeted ceilings stay unset. The second setting sends only the explicit
`thinking: {type: disabled}` object; use it only when the configured endpoint
supports that option. No alias inference, automatic fallback, or unsupported
option retry is added. Structured tool selection and schema remain unchanged.

Controlled HTTP/SSE tests inspect the actual serialized request, not just client
attributes. Live experiments must distinguish configured policy from HTTP wire
observations, and local serialization from what a proxy ultimately forwards.

Each returned response records SDK-visible text-character and tool-call counts,
with explicit measurement caps, and a validated reasoning-token breakdown when
reported. Absent reasoning usage remains `missing`, invalid or out-of-range
values remain `invalid`, and neither becomes an inferred zero. Character counts
are not token counts. Other output tokens can include formatting and tool-call
structure, so a difference from reasoning tokens is not necessarily visible text.
Generic ChatOpenAI can discard provider-specific reasoning content; this code
does not capture or reconstruct that content.

No message text, tool names/arguments, reasoning text, headers, or raw provider
errors enter the new shape diagnostics. The previous `length` rejection and
unknown-usage protections remain in force. The new fields supplement, rather
than rewrite, old observations.

Evidence and scope:

- Local inspected runtime: langchain-openai 1.7.2 and openai 2.45.0. Its
  ChatOpenAI payload builder explicitly rewrites `max_tokens` and its structured
  adapter binds a named tool with `parallel_tool_calls=False`.
- [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
  documents `max_completion_tokens` and the deprecated `max_tokens` field.
- [OpenAI token accounting](https://developers.openai.com/api/docs/guides/token-counting)
  explains that output allowance includes non-visible tokens; reasoning and
  visible text are not interchangeable totals.
- [DeepSeek Chat Completions reference](https://api-docs.deepseek.com/api/create-chat-completion/)
  documents its vendor options. These public requirements do not establish what
  the configured third-party gateway accepts, honors, or forwards.

Until a separately frozen live experiment passes complete-output checks, no
claim is made that either switch fixes the configured channel or improves repair
quality. Root private `.env` values are not changed by this implementation.
