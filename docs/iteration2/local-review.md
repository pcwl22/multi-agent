# Local functional review

Reviewed runtime implementation: `7abd716`, relative to the prior local delivery
`b806f9c`. Later changes in this iteration are evidence, packaging and documentation.
This is a functional review, not a security audit or human merge approval.

- Coder receives the original issue, explicit literal inputs, existing test paths
  and refreshed generated-file context. The syntax gate reads through Repository
  boundaries and does not evaluate target code. Existing tests can satisfy the
  coverage requirement during a source-only retry; they remain immutable.
- Reviewer receives bounded current source, diff and actual test evidence. An
  explicitly unsatisfied contract overrides an inconsistent approval flag.
  Optional checklist fields retain compatibility with old task data; a missing
  checklist is not evidence that a contract was checked.
- Test recognition is shared by edit protection, context selection and holdout
  exclusion, including legacy root `tests.py` and `test.py` layouts. Frozen
  upstream tests and original project tests are checked byte-for-byte.
- Provider failure resumes occur only after an explicit request and cooldown,
  resume the failed node and have a separate finite budget. Permanent errors and
  exhausted budgets terminate. Missing token usage stays unknown.
- Synchronous checkpoints precede subsequent nodes. The filesystem/SQLite crash
  window is handled by refusing unrecorded diffs even before the first attempt,
  preserving the baseline/workspace rather than applying a repair twice.
- Real process termination was tested before Docker testing and immediately after
  file writes. Isolated-wheel tests also verify that the child process imports
  the same installed application as its parent.

Validation: source and isolated wheel each passed 129 tests, with one existing
Windows link-permission skip; Ruff and dependency consistency checks passed.
The original 35 test files and frozen expanded corpus/oracles are unchanged.

Remaining limits: literal coverage checks support only short constructor
expressions and simple bindings, not arbitrary dataflow or semantics. Model
checklists can omit or misjudge requirements. Generated tests can themselves be
wrong; once saved, they are immutable under the present task policy, so adding
another correct test cannot make a wrong one pass. Such tasks terminate within
budget and remain failures in benchmark accounting. None of these checks alone
establishes general repair accuracy or makes approval/publication automatic.

A future design can evaluate preserving every attempt in its own directory while
rebuilding later attempts from the original immutable-test baseline; that change
is not part of this candidate and requires its own behavioral validation.

All latest checks are local (Windows Python 3.13.5 and Linux Docker execution).
No new GitHub CI run covers this candidate because no push was performed. PR #2
was read back as OPEN, draft, head `edb60e0a180efeed9a18fb5086cb1daea121ad17`.
No remote push, merge, PR creation, tag, release or trace upload occurred.
