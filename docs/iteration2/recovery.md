# Failure recovery behavior

Model request failures persist safe metadata: failure kind, failed node, whether
manual retry is permitted, cooldown deadline and budget exhaustion. Provider
response bodies and credentials are not written to task state. Missing usage is
kept unknown even after a later successful retry.

| Failure | Result | Operator action |
|---|---|---|
| HTTP 429 | `retryable`, at least 300-second cooldown (longer Retry-After honored up to one day) | Refresh, wait, explicitly retry the failed node. |
| Timeout | `retryable`, at least 5-second cooldown | Explicit retry after cooldown. |
| Connection error / HTTP 5xx | `retryable`, 10 / 30 seconds minimum | Restore service, then explicit retry. |
| HTTP 401/403, invalid request, invalid structured output | `failed` | Correct configuration/output cause, create a new task. |
| Repeated transient failure | `failed` after provider resume budget | Inspect records, create a new task. |
| Docker unavailable | `blocked` | Restore Docker/image, continue testing existing patch. |
| Process loss with recorded patch | Preserved checkpoint | Resume pending node without reapplying the patch. |
| Process loss after an unrecorded file write | Resume denied | Preserve baseline/workspace/diff for inspection; create a new task. |

The provider resume budget is separate from repair-test/review retries; each uses
`max_retries` as its limit. SDK internal HTTP retries remain bounded separately
and are not counted as logical model calls. There is no automatic retry loop or
automatic publication. CLI exits 2 on resumable provider/Docker failure, 1 on
terminal repair failure. API rejects premature retries with HTTP 409.

LangGraph invocation and approval use `durability="sync"`, persisting each
checkpoint before the next node starts. This does not make filesystem edits and
SQLite commits one transaction. A process can still die during/after file writes;
the diff consistency guard now checks even tasks with zero recorded attempts and
refuses that uncertain replay. We retain the files rather than discarding them.

Validation includes real SDK calls over a controlled HTTP transport for 429,
503, 401 and read timeout; service reopen and all three model-node retries;
cooldown/budget/API checks; Streamlit button states; and actual `os._exit` process
loss before testing and immediately after writes. The latter uses the explicit
mock repair adapter and real Docker tests. These controlled failures are not
real-provider availability measurements and are excluded from live benchmarks.

Not verified: machine power loss, filesystem corruption, distributed scheduling,
multi-process model quota coordination, or host failures during GitHub publication.
Uncertain external publication continues to require manual inspection.
