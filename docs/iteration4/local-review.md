# Local functional review

Reviewed runtime: `2e6b0f2d5e7619be6bce91849ea741f82a7986d1` relative to prior
local delivery `15c53ee`. This is a functional review, not a security audit or
human approval to publish. Runtime and prompts remained frozen after live
pre-registration `3ad45918d44da12920763702a9c399fedf609be8`.

- JUnit testcase observations preserve original suite counts and explicitly mark
  missing/truncated detail. File provenance uses Repository checks; AST inspection
  extracts equality expressions without executing target code. Full evidence is
  kept locally while model payloads use bounded observations.
- Duplicate feedback binds complete diff digest and normalized observed failure
  fingerprint. It changes retry instructions, not the number of permitted calls.
  Identical source alone is not rejected, allowing a wrong generated test to be
  corrected in a later isolated directory while preserving every earlier file.
- The regression node runs only after the current multi_full candidate passes.
  It creates a separate original-source snapshot plus verbatim generated tests,
  executes only the fixed Docker command, and records same-test fail-to-pass
  witnesses with candidate/attempt/diff identity. Original/current bytes are
  rechecked. Holdouts remain exclusively evaluator inputs. Missing evidence,
  smoke tests and collection errors are not promoted into demonstrated proof.
- Reviewer receives observed witnesses plus current issue/source/diff evidence.
  Passing tests never force approval; reviewer rejection, independent acceptance
  and human readiness are distinct report outcomes.
- Creation intent and original-file hashes are persisted before copies. Continued
  failures are queryable and do not schedule Coder. Explicit preparation resume
  has a finite counter independent of model repair counters. Interrupted pristine
  candidate directories retain UUIDs; partial/ambiguous/unknown writes remain and
  are refused. Activation retries only Windows errors 5/32/33 three times with
  bounded delays, rechecking both move paths and refusing replacement each time.
- Old stored tasks, the preserve default, digest-only legacy decisions, isolated
  UUID decisions and explicit separate publication remain compatible. No remote
  write operation was invoked in this phase.

Validation: source and the exact fresh-installed wheel each passed 159 tests,
with one existing Windows permission skip. The process-loss workers verify the
same application installation as their parent. Ruff and pip consistency passed;
all 52 previous test files and the strict corpus/oracles are unchanged. UI checks
use controlled demo adapters and actual Docker, not actual browser navigation or
live model performance.

Limits: snapshot comparison is not a semantic proof, generated tests can still
be wrong, and baseline witnesses need not cover every contract. Failed-source
helper imports can prevent baseline reproduction. Partial copies are preserved
rather than repaired automatically. Windows denial's original cause, hard power
loss, arbitrary project/dependency systems and distributed execution remain
unverified. No current GitHub CI covers this candidate because it was not pushed.
