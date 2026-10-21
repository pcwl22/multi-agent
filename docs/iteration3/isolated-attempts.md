# Optional isolated repair attempts

Default policy remains `preserve`: later repairs continue in the current task
workspace. `isolated` is an explicit opt-in for newly created tasks. The selected
policy is persisted per task; changing server defaults does not migrate history.

```powershell
python -m app.cli --repo demo_repository --issue "expired token should return 401" --retry-workspace-policy isolated
python scripts/start_demo.py --retry-workspace-policy isolated
```

For API creation use `"retry_workspace_policy": "isolated"`; the Streamlit form
also offers this choice. An omitted/null choice uses the server setting:

```powershell
$env:REPOPILOT_RETRY_WORKSPACE_POLICY = 'isolated'
```

Each task keeps its original baseline plus `attempts/0001`, `0002`, ... . Each
candidate directory has its own baseline, workspace, UUID manifest and evidence
JSON. A failed candidate's files, including wrong generated tests, are preserved.
The next candidate is copied from the original baseline, so a previously generated
filename may be used in a different directory without editing or deleting any
existing test. Original repository tests remain immutable in every candidate.

Coder receives original source context, prior diff/test feedback and an explicit
instruction to produce the complete fix plus new regression tests. A source-only
increment against a prior candidate is not a complete isolated repair. This is
part of the model contract, not an automatic patch transformation.

Preparation uses a fresh staging directory, checks both resolved paths stay
inside task storage, then renames it to the numbered candidate directory. An
already prepared but uncheckpointed pristine candidate is reused with the same
UUID. Partial staging directories remain as diagnostic evidence. Unrecorded
candidate file writes block replay; they are never reset or overwritten.

Task invocation uses synchronous LangGraph checkpoints. Repair/test/review retry
budget remains shared and finite. A transient provider error resumes the same
candidate after manual cooldown, using the separate provider resume budget;
Docker unavailability resumes testing that candidate. Neither creates an extra
candidate or clears the existing attempt count.

GET diff includes `candidate_id`. Isolated-mode approve/reject/PR requests require
both current fields; legacy tasks continue to use only the original digest:

```json
{"diff_digest": "<64-character current digest>", "candidate_id": "<current candidate UUID>"}
```

Missing/stale UUIDs are rejected before approval/publication. The last Docker test
evidence must belong to the active candidate. Original and per-candidate baselines,
original tests, prior workspace manifests and sealed evidence hashes are checked.
Approval also rechecks the actual final diff. Publication remains a separate,
explicit action and is disabled without fixed repository configuration/credentials.

Evidence JSON `model_calls_total` and `retry_count` are task-wide counters at
capture time; do not sum them across candidate files. A candidate can be archived
while overall task status is still `running`; its tests/rejections show why it
was replaced. Final evaluator records count current-candidate test evidence only,
and export every candidate manifest, patch and test record separately.

Validated: three wrong-test classes with real Docker, finite failure, stale/current
approval IDs, old registry records, service reopen, provider resume and actual
process termination before checkpoint, after writes and before testing. Controlled
replay fixtures include prior real bad proposals plus evaluator-authored corrected
candidates; they are not live model performance results.

```powershell
python scripts/replay_isolated_failures.py --output .repopilot/fresh-controlled-replay
```

The timestamp replay needs the historical itsdangerous corpus and pilot image
prepared using [the historical pilot instructions](../iteration2/pilots/README.md).

Limits: wrong tests can still be regenerated; complete fixes can be forgotten.
Retries stop at the configured budget. Copies increase storage use, and baseline
restarts can increase model work. This does not guarantee correctness, exactly-once
provider billing, power-loss durability, arbitrary project support or distributed
execution. Target repository code still runs only in the restricted Docker sandbox.
