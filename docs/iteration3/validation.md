# Isolated-candidate validation and local release candidate

Runtime: `3b4247f60dd36b031dbaa2c31f70940bc31fba9b`. Plan preregistered in
`9ba73fa21bfe46c99b3e0d6ab7a3c95424ea0db5` before requests. All later changes are
local evidence, documentation and packaging. The default remains `preserve`;
`isolated` is opt-in and persisted per task. See [lifecycle and usage](isolated-attempts.md).

## Verification

Source and exact installed wheel each passed **143 tests, 1 skipped**. Source
run took 150.18 seconds; fresh isolated-wheel run took 155.87 seconds. The one
existing Windows link-permission skip remains. Eleven existing Starlette timeout
deprecation warnings remain. Ruff, dependency consistency and diff whitespace
checks passed. All **45 pre-existing test files** from `da8b02d`, the synthetic
corpus and strict holdouts are byte-for-byte unchanged.

The wheel was installed with `--no-deps` into a new venv populated from
`requirements.lock`, without system-site-packages. `python -I` verified application
imports from site-packages; process-recovery workers verify the same installation
as their parent. Host: Windows Python 3.13.5, bundled pwsh 7.6.5; target execution:
Linux Docker Python 3.12.14. PowerShell 7.6.3 was not separately verified.

Tests cover wrong pagination-tail tests, unjustified discount result type tests,
and unsigned timestamp fixture failures; finite retries; current/stale candidate
approval; legacy stored-task compatibility; provider resume after service reopen;
and real process termination after candidate preparation, after writes and before
Docker testing. Recovery adapters are controlled fixtures, not live provider
outages. Unrecorded writes are preserved and refused rather than replayed.

[UI component evidence](ui-component.json) uses Streamlit AppTest, local FastAPI
and actual Docker with the explicitly limited demo Mock. It checks task policy,
candidate display and approval digest/UUID forwarding. This is not a live-model
benchmark or a separate actual browser session.

## Controlled replay

Three actual prior bad proposals were replayed, then followed by evaluator-authored
complete corrected candidates. **3/3** reached passing Docker tests and independent
holdouts. Original tests and prior bad tests remained intact in separate candidate
directories. There were **zero live LLM calls**. This demonstrates candidate
isolation/recovery mechanics, not model accuracy. See [report](controlled-replay/report.json),
[fixtures](replay-fixtures.json) and `scripts/replay_isolated_failures.py`.

## Frozen live-model evaluation

The fixed plan is 30 synthetic tasks, 9 targeted pagination tasks and 6 historical
runs across **two distinct upstream bugs** (jsonpointer and itsdangerous). All use
`isolated`, DeepSeek-compatible service `https://muyuan.do/v1`, requested model
`deepseek-v4.1-flash`, temperature 0, repair budget 2, provider manual resume budget
2, 120-second model/test timeouts and process-local 7.5-second pacing. No prompt,
repair code, dataset, reference implementation or acceptance file was adjusted
from the frozen plan during these runs. Reported model IDs are service metadata,
not independently verified underlying model weights.

| Scope | Independent accepted | Ready and accepted | Prior independent reference | Tasks with later candidate | Preserved candidates | Recovered after failed Docker |
|---|---:|---:|---:|---:|---:|---:|
| Frozen synthetic strict | 29/30 | 29/30 | 28/30 | 6 | 38 | 4 |
| Pagination targeted repeats | 5/9 | 5/9 | 9/9 | 9 | 23 | 6 |
| Historical real-project bugs | 5/6 | 4/6 | 5/6 | 3 | 11 | 2 |

“Recovered after failed Docker” counts a later workspace-test pass; it does not
require independent acceptance or reviewer approval.

The previous results are historical comparisons, not randomized paired causal
evidence. Synthetic examples are small and repeated historical calls are not
independent projects. A higher observed score does not establish general repair
accuracy or prove isolation caused any difference.

### Infrastructure interruption and continuation

After 25 completed strict records, Windows rejected an initial staging-directory
rename (`WinError 5`) before that task was registered or sent to the model. The
controller exited and cleared its key. The unregistered task directory, completed
records and failure details remain preserved. Its cause was not independently
attributed. This is an observed infrastructure failure, separate from the 45
registered-task repair denominator; these results do not establish uninterrupted
end-to-end availability.

An explicit continuation harness reused prior records/baselines and skipped only
completed case/repeat/mode cells, then executed the remaining five strict cells
and the two untouched groups with the same settings. It did not request a new
candidate for any completed task. The original 25 JSONL records remain unchanged.
The harness is retained as [reproducible text](continue-validation.py.txt), with
[exact operational changes and incident](infrastructure-interruption.json).
Runtime modules and prompts remained frozen. No silently discarded failures or
model reruns were used to improve the repair scores.

### Mode breakdown

| Group | Mode | Tasks | Independent acceptance rate | Workflow completion rate | Mean calls | Mean reported tokens |
|---|---|---:|---:|---:|---:|---:|
| strict | single | 10 | 1.0000 | 1.0000 | 1.20 | 2628.7 |
| strict | multi_no_review | 10 | 1.0000 | 1.0000 | 2.20 | 4797.1 |
| strict | multi_full | 10 | 0.9000 | 0.9000 | 3.40 | 10042.5 |
| pagination | single | 3 | 0.6667 | 0.6667 | 2.67 | 8175.333333333333 |
| pagination | multi_no_review | 3 | 0.3333 | 0.6667 | 3.67 | 10742 |
| pagination | multi_full | 3 | 0.6667 | 0.6667 | 4.00 | 12217 |
| historical | single | 2 | 0.5000 | 0.5000 | 2.00 | 17865 |
| historical | multi_no_review | 2 | 1.0000 | 1.0000 | 2.50 | 16521 |
| historical | multi_full | 2 | 1.0000 | 0.5000 | 4.00 | 34762 |

Total logical model calls: **116**. Reported tokens: **406382**;
runs with unknown total usage: **0**. Candidate evidence counters are
cumulative task totals and must not be summed across candidate files.

Failures remaining within the 45 registered-task benchmark:

- strict: `recursive-config` / `multi_full` / `228ccf19-e883-46cb-a00b-580242aa740b`: failed; holdout=None; Test retry budget exhausted
- pagination: `one-based-page` / `multi_no_review` / `94e80636-8ad9-42fd-91d3-82b5fe7fe1c0`: failed; holdout=None; Test retry budget exhausted
- pagination: `one-based-page` / `multi_full` / `e7d74d3f-797e-446b-b9c9-82be4fdc5cec`: failed; holdout=None; Test retry budget exhausted
- pagination: `one-based-page` / `multi_no_review` / `838c3b39-eb6e-4150-aca7-272d32e68120`: awaiting_approval; holdout=failed; None
- pagination: `one-based-page` / `single` / `2b975054-a6dc-4301-a1e3-c42020aab68f`: failed; holdout=None; Test retry budget exhausted
- historical: `itsdangerous-date-overflow` / `single` / `d4d06fd8-ded1-413a-9630-067f656cafbf`: failed; holdout=None; Test retry budget exhausted
- historical: `itsdangerous-date-overflow` / `multi_full` / `c600f622-423b-4fb6-a506-3a2d4c833761`: failed; holdout=passed; Review retry budget exhausted

Raw evidence: [strict](strict/report.md), [pagination](pagination/report.md),
[historical](historical/report.md), [machine-readable summary](summary.json).
Each directory keeps every raw record, final patch, candidate manifest, candidate
patch, tests/rejections and immutable evidence hash. Original-test bytes, original
and per-candidate baselines, archived workspace manifests, candidate IDs, actual
patch digests and active-candidate test association were verified during export.
All independent baselines failed in Docker before repair. Local full task states
and workspaces remain under `.repopilot/` and are not packaged as product files.

## Failure interpretation

The failed recursive-config full-mode task repeatedly retained default leaf values
instead of honoring overrides. Its original contract test failed in every fresh
candidate; it is counted as failure and was never approved. See
[strict failure analysis](strict-failure-analysis.json). Full candidate evidence
also distinguishes pagination range/list source errors from incorrect tail-page
expectations in generated tests. An isolated workspace permits a new complete
proposal; it does not ensure that the model changes its reasoning or fixes tests.
The pagination group includes three retry-budget failures and one candidate that
passed workspace tests but failed four independent range/list assertions. This
last candidate was awaiting human approval, never approved or published. Passing
model-written tests is insufficient evidence of issue correctness. The historical group has five independent holdout passes, but only four tasks
reached awaiting human approval: one full-mode candidate passed Docker and
independent holdout while its reviewer kept rejecting it until budget exhaustion.
See [historical failure analysis](historical-failure-analysis.json). A separate
single-mode timestamp task failed an original upstream assertion requiring the
malformed-signature exception message to contain `Malformed`. The default
workspace policy remains unchanged.

## Local delivery and limits

Candidate wheel/source archives and SHA256SUMS are in
`dist/iteration3-3b4247f/`; [companion checksums](release-artifacts.json) identify
the exact clean-tested wheel. The source archive includes scripts, docs, frontend,
container files, new tests and all candidate evidence, and excludes credentials,
local task stores and companion checksum JSON files to avoid circular hashes.
Earlier artifacts and evaluation evidence remain intact.

[Functional review](local-review.md), [clean install](clean-install.json) and
[remote readback](remote-status.json) document the scope. **No push, PR creation,
merge, tag, release or trace upload occurred. PR #2 remains draft at
`edb60e0a180efeed9a18fb5086cb1daea121ad17`.** Its old CI does not cover this local
candidate. This phase does not approve publication.

Generated tests can still be wrong and a fresh candidate can omit a previous fix.
Copies increase storage and model work. Exactly-once provider billing, hard-power
loss durability, arbitrary build systems, dynamic dependencies, public multi-user
serving and distributed queues remain unverified. Target repository code executes
only in the restricted Docker runner; all original and failed generated tests
remain preserved.
