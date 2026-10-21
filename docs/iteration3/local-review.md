# Local functional review

Runtime reviewed: `3b4247f60dd36b031dbaa2c31f70940bc31fba9b`, relative to prior
local delivery `da8b02d`. This is a functional review, not a security audit or
human merge approval. The live plan was recorded at `9ba73fa` before requests.

- The legacy workspace policy remains the default, and old stored tasks missing
  policy fields use that policy even when the server default changes. New tasks
  can explicitly select isolated candidates through API, CLI or UI.
- Every isolated retry starts from the original baseline and retains the prior
  candidate directory, including wrong generated tests. Coder receives previous
  feedback and must produce a complete candidate. No existing test is deleted or
  changed; the same filename can occur in separate candidate directories.
- Candidate staging and activation check repository boundaries, baseline hashes
  and UUID manifests. Preparation failure exits without invoking Coder against
  the prior workspace. An uncheckpointed pristine candidate can be reused with
  its UUID. Partial staging and unrecorded writes remain preserved for diagnosis.
- Test, review, patch and rejection records carry candidate identity. Evaluation
  uses the active candidate's test evidence, and exports all candidates. Archived
  evidence/workspace hashes, original tests and baseline bytes are verified.
- API and direct publisher approval bind the diff digest and active candidate
  UUID. Missing/stale identities and prior-candidate test evidence are rejected
  before publication. Publication remains separate and explicitly requested.
- Sync checkpoints retain finite task-wide repair budgets. Provider resume uses
  the same candidate and separate manual resume budget; unknown usage stays
  unknown. Exactly-once provider billing is not claimed.

Validation includes actual process termination after candidate preparation,
after file writes and before Docker testing; the restart behavior is checked in
both source and installed-wheel test runs. Recovery adapters are controlled test
fixtures; they do not demonstrate a live provider outage. Three previous real
bad proposals were also replayed with evaluator-authored corrected candidates
and real Docker, independently from live model metrics.

All 45 pre-existing test files from `da8b02d` and the frozen expanded corpus/oracles
remain unchanged. Current validation is local; PR #2's old CI does not verify this
candidate. No push, PR creation, merge, tag, release or trace upload is authorized
by this local validation phase.

Remaining limits: regenerated wrong tests and incomplete fresh candidates can
still fail. Snapshots consume storage; restarting from baseline may increase
model work. Small synthetic and two-bug historical samples cannot establish
causal or general repair improvements. Hard power loss, distributed scheduling,
arbitrary build systems and networked target tests are unverified. Target code
continues to execute only in Docker.
