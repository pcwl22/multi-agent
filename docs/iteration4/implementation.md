# Repair feedback, regression witnesses and creation recovery

The implementation extends the optional isolated-candidate work from iteration 3.
Default policy remains `preserve`; prior task records remain readable. The 52 test
files at `15c53ee` are retained unchanged. Target code executes only in Docker.

## Structured feedback

Docker keeps the same fixed pytest command and adds xunit1 JUnit metadata. Full
suite counts are separate from a bounded list of testcase observations (512 max,
failures first, truncation explicit). Each failed testcase records its path, line,
name, message and bounded traceback. Repository checks classify the path as an
original test, generated test or unknown. Equality assertions can expose literal
actual/expected expressions using AST parsing, never evaluation. Unsupported
assertions retain raw text without invented values.

Failure fingerprints use observed test identity/assertion/message and normalize
memory addresses. Repeating the same complete diff and fingerprint adds a specific
instruction to reconsider the diagnosis. It does not allocate extra calls or
reset budgets, and it never rejects identical source alone: the source can already
be correct while a new generated test needs correction. Full on-disk evidence is
retained; model payloads contain bounded failure cases rather than every passed
upstream testcase. This is feedback, not a correctness guarantee.

## Reviewer regression witness

After a passing workspace run in multi_full, the workflow snapshots original
source and original tests into a separate retained directory and copies added
test files there verbatim. It executes the same fixed Docker command. An identical
added testcase that fails on the original source and passes on the candidate is
recorded as fail-to-pass evidence bound to attempt, candidate ID and diff digest.
Original files and current candidate bytes are checked before and after replay.
No independent evaluator holdouts are supplied to the model.

Smoke tests passing on both versions are not regression evidence. Collection
errors, absent testcases, test doubles, truncated reports and Docker unavailability
are explicitly not proof. A witnessed regression supports only that tested
behavior, not every contract. Reviewer still independently checks the original
issue and can reject; human approval and separate explicit publication remain.

## Task creation recovery

Creation intent, source fingerprint and zero model counters are stored in SQLite
before snapshot writes. Persistent copy/activation failure returns a queryable
`creation_failed` task; API does not start a repair in the background. Diff remains
non-approvable. The UI can explicitly request preparation resume. A `creating`
record interrupted by process exit can also resume.

Candidate activation retries at most three times, only for Windows error codes
5, 32 or 33, with 50/100 ms bounded delays. Every retry rechecks absolute paths and
refuses replacement. A complete pristine staging candidate is reused with the
same UUID on explicit resume. Partial staging remains; unknown writes or ambiguous
prepared candidates are refused. Partial original snapshots are preserved and
require diagnosis/new task, rather than being silently reset. A failed preparation
can be manually attempted at most `max_retries + 1` times; resuming an interrupted
in-flight preparation retains its count. Model repair budget is unchanged.

The original Windows failure's root cause remains unattributed. Controlled
PermissionError injection validates finite retries and persistence, not a claim
that every filesystem denial is transient. Actual process exits validate intent
recovery and UUID reuse after activation. Hard power loss/distributed concurrency
are outside these checks.

## Verification before live evaluation

Targeted checks passed: structured observations and Docker feedback (8 tests),
regression-witness/legacy route checks (4 tests), creation recovery and actual
process termination (9 tests). These controlled adapters are not live LLM metrics.
Full-suite and fresh-install results are recorded separately in the final report.
All generated failures, witnesses, raw benchmark records and prior artifacts are
kept. No push, PR creation, merge, tag or release is part of this phase.
