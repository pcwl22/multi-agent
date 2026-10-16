# Feedback and workspace-policy comparison

Runtime: `2e6b0f2d5e7619be6bce91849ea741f82a7986d1`. Protocol preregistered at
`3ad45918d44da12920763702a9c399fedf609be8` before any new live request.
This phase is local and unpublished. PR #2 stays draft; no push, PR creation,
merge, tag, release or trace upload was performed. Default remains **preserve**.

## Implemented and verified

[Implementation and recovery boundaries](implementation.md) describe structured
JUnit observations, original/generated test provenance, repeated complete-candidate
failure fingerprints, bounded model payloads, Docker baseline regression witnesses
and persistent task-creation recovery. These add evidence and recovery behavior;
they do not guarantee model reasoning or approval.

Source and exact isolated-wheel suites each passed **159 tests, 1 skipped**.
Source: 223.86 s; isolated wheel: 186.62 s.
The one pre-existing Windows link-permission skip and 11 existing Starlette
warnings remain. Ruff, dependency consistency, whitespace checks and credential
scan passed. All **52 pre-existing test files** from `15c53ee`, the synthetic corpus
and frozen holdouts are unchanged.

The wheel was installed without dependencies into a new venv populated from
`requirements.lock`; no system-site-packages. `python -I` verifies site-packages
imports. Source and wheel suites include actual process exits after creation
intent, after initial candidate activation and prior isolated-repair crash windows;
parent/worker application imports match. Copy/activation tests simulate Windows
access and sharing errors; this does not attribute the original OS denial's cause.
Partial or unrecorded writes are retained and refused, never reset. New preparation
and model-repair budgets remain separate and finite.

[UI component evidence](ui-component.json) uses AppTest + local API + actual Docker
with the explicitly limited auth demo Mock and controlled Windows denial. It
verifies queryable creation failure, explicit resume with the same UUID, regression
witness and digest/UUID approval forwarding. This is not an actual browser session
or a live-model accuracy result.

Host: Windows Python 3.13.5 and bundled pwsh 7.6.5; target code: Linux Docker
Python 3.12.14. PowerShell 7.6.3, hard power loss, distributed queues, arbitrary
build systems and dynamic network dependencies were not separately verified.

## Separate live diagnostic

Nine fixed diagnostic tasks cover pagination, recursive configuration and the
historical timestamp bug, each in three modes. Diagnostic independent acceptance:
**9/9**; ready and accepted: **9/9**.
It observed 7 structured feedback records and
3 demonstrated Docker regression witnesses.
[Recorded gate](diagnostic-gate.json) passed. Diagnostic results are excluded from
the 90-task comparison and were not used to change prompts/runtime/holdouts.
Fresh-wheel regression finished before formal comparison requests began.

## Preregistered 90-task comparison

Same runtime, issue texts, corpora, hidden oracles, provider, temperature, budgets,
timeouts and pacing were used for both policies. Each policy ran 30 strict
synthetic tasks, 9 pagination repeats and 6 historical runs across **two upstream
bugs**, not six independent projects. The strict set has ten synthetic cases;
targeted pagination repeats a case already in that set. The 45 runs per policy are
not 45 independent bugs. Diagnostic cases also overlap the formal cases and are
not an out-of-sample estimate. Order: strict preserve then isolated;
pagination isolated then preserve; historical preserve then isolated. Workers are
3/1/2 by group. Repair budget 2; model/test timeout 120 s; process-local minimum
request interval 7.5 s. Endpoint `https://muyuan.do/v1`, requested model
`deepseek-v4.1-flash`. Reported model identity is service metadata, not independent
verification of underlying weights.

| Group | Policy | Independent accepted | Ready and accepted | Logical calls | Reported tokens | Mean task seconds |
|---|---|---:|---:|---:|---:|---:|
| strict | preserve | 26/30 | 26/30 | 70 | 213394 | 49.12 |
| strict | isolated | 28/30 | 28/30 | 66 | 208643 | 47.35 |
| pagination | isolated | 7/9 | 7/9 | 29 | 109665 | 31.52 |
| pagination | preserve | 9/9 | 9/9 | 28 | 102151 | 29.58 |
| historical | preserve | 6/6 | 5/6 | 17 | 148324 | 40.90 |
| historical | isolated | 6/6 | 6/6 | 15 | 144638 | 46.77 |

Formal totals: preserve **41/45** independent passes,
**40/45** ready and accepted;
isolated **41/45** independent passes,
**41/45** ready and accepted.
Formal logical calls: **225**; reported tokens: **926815**.
Observed formal feedback records: preserve **21**,
isolated **17**; exact repeated-candidate
failure matches: preserve **0**, isolated
**0**. Demonstrated witness records:
preserve **12**, isolated
**15**. These observations do not isolate the
effect of any one implementation change.

Diagnostic calls/tokens remain separate in [summary](summary.json). Unknown usage
is retained as null; candidate snapshots contain cumulative counters and are never
summed for model costs. Logical calls do not count opaque SDK-internal retries as
separate HTTP billing events.

[Comparison JSON](comparison.json) includes paired case/mode/repeat acceptance
outcomes. Small synthetic samples, repeated calls, fixed block order and provider
variation do not establish causal gains or real-project generalization. Durations
include pacing, provider load and shared host resources; they are not intrinsic
algorithm speed. No performance conclusion changes the default automatically.

## Reviewer and feedback interpretation

The remaining preserve timestamp rejection has a directly checkable reason: the
Issue explicitly requests NEW regression tests, but the candidate added none.
Its witness is `no_new_tests`. Independent holdout acceptance measures source
behavior and does not satisfy that separate deliverable. The record remains
failed rather than overriding Reviewer; not every passing-test rejection is an
incorrect rejection. See [residual review evidence](reviewer-residual.json).

Neither formal policy group triggered an exact duplicate complete-diff/failure
fingerprint. That branch was verified by the controlled real-Docker test, but
this live batch provides no evidence that the exact-duplicate marker reduced
loops. Structured observations and witnesses were used; causal attribution of
quality changes to them is not established.

Exact datasets/oracle copies and the executed hidden-input controller are
preserved with [reproduction limits and instructions](reproduce.md). Relocating
absolute diagnostic paths changes the dataset byte hash and requires a new plan.

## Failures retained

Every registered task remains in its group's denominator. Passing workspace tests
and passing independent holdouts are separate from reviewer completion and human
approval. Evaluation holdouts are never sent to Coder or Reviewer. A regression
witness proves only that the identical added testcase failed on baseline and passed
on the candidate; tests passing both versions, collection errors, truncated output,
unavailable Docker and test doubles are not proof. Existing tests remain immutable
under both policies. Isolation can permit corrected new tests in a separate folder,
but can still regenerate wrong tests or omit a prior source fix.

- `strict-preserve` / `one-based-page` / `multi_no_review` / repeat 0: workflow `failed`, workspace `failed`, holdout `None`; Patch retry budget exhausted: Existing tests are immutable (`160df8f4-9cc0-462c-9f03-9b4665c80957`).
- `strict-preserve` / `percent-discount` / `multi_full` / repeat 0: workflow `failed`, workspace `failed`, holdout `None`; Test retry budget exhausted (`4a53cc2e-c5bf-4257-989c-8cefc9f7fd72`).
- `strict-preserve` / `one-based-page` / `multi_full` / repeat 0: workflow `failed`, workspace `failed`, holdout `None`; Patch retry budget exhausted: Existing tests are immutable (`02a5a5a4-c9b6-42d8-861d-e82d8fa3e10b`).
- `strict-preserve` / `recursive-config` / `single` / repeat 0: workflow `awaiting_approval`, workspace `passed`, holdout `failed`; independent holdout failed (`fd55c61e-31f9-450d-a8f7-a05e207a40d2`).
- `strict-isolated` / `one-based-page` / `single` / repeat 0: workflow `awaiting_approval`, workspace `passed`, holdout `failed`; independent holdout failed (`165fa358-d996-4426-9d0a-caf863343c0d`).
- `strict-isolated` / `recursive-config` / `single` / repeat 0: workflow `awaiting_approval`, workspace `passed`, holdout `failed`; independent holdout failed (`7a81d915-0e96-4147-9b86-1fbfacea8751`).
- `pagination-isolated` / `one-based-page` / `single` / repeat 2: workflow `awaiting_approval`, workspace `passed`, holdout `failed`; independent holdout failed (`9c291350-021d-49f9-82e8-3c24ed94219c`).
- `pagination-isolated` / `one-based-page` / `multi_no_review` / repeat 2: workflow `awaiting_approval`, workspace `passed`, holdout `failed`; independent holdout failed (`622461b9-48df-43e8-9cdb-086182b4ff3f`).
- `historical-preserve` / `itsdangerous-date-overflow` / `multi_full` / repeat 0: workflow `failed`, workspace `passed`, holdout `passed`; Review retry budget exhausted (`34158c43-f402-4def-8489-27544eb830a3`).

Raw records, parsed proposals, every recorded test/review/rejection/feedback event, witness
JSON and final patches are retained under each group directory. Isolated groups
also include every candidate manifest, patch and sealed evidence. Export verifies
original file fingerprints, archived manifests, test bytes, actual diff digests,
witness copied-test bytes and same-test fail-to-pass identity. Local snapshots,
SQLite states and any partial preparation directories stay under `.repopilot/`.
No target code is imported or executed on the host.

## Local artifacts

The clean-tested wheel, source distribution and SHA256SUMS are in
`dist/iteration4-2e6b0f2/`; [companion hashes](release-artifacts.json) identify them.
The source archive includes frontend, scripts, containers, tests and all public
evidence. Credentials, local task stores and companion checksum files are excluded.
Prior iteration artifacts and reports remain unchanged.

[Clean install](clean-install.json), [local functional review](local-review.md) and
[read-only remote status](remote-status.json) document delivery. Existing PR #2 CI
covers its original remote head, not this unpushed local candidate. Publication
still requires explicit human approval of concrete content; this phase grants none.
