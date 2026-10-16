# Reproducing the frozen local comparison

Use a fresh copy of this local candidate or its source distribution, Python 3.11+,
locked dependencies and the sandbox images. The controller's Git guard requires
this local repository and runtime commit `2e6b0f2`; remote PR #2 does not contain
that unpushed commit. The executed controller is preserved as
[reproduce-controller.py.txt](reproduce-controller.py.txt), with hidden key input,
fixed settings and no publication entry point. Copy it to a `.py` file to review
or run it; do not paste credentials into a source file.

The strict dataset/corpus/oracles are already packaged under
`app/evaluation/expanded`. Historical repositories and their dependency image are
prepared from pinned Git objects using
[historical pilot instructions](../iteration2/pilots/README.md). They are not
replaced by model-generated stand-ins.

Exact input JSON and oracle bytes for diagnostic, pagination and historical jobs
are preserved under `inputs/`; the `.py.txt` suffix keeps evaluation files outside
pytest discovery. `inputs/manifest.json` lists original workspace-relative restore
directories and SHA-256 values. In a fresh workspace, copy each dataset back to its
listed directory and each oracle to `acceptance/` after removing only `.txt`.
Verify hashes and refuse to overwrite an existing different file. Prepared source
repositories must match the preregistered corpus hashes.

Diagnostic JSON records absolute repository paths on the original Windows host.
A relocated workspace requires rebuilding those paths. That changes the dataset
byte hash and must be recorded as a new protocol rather than claimed as identical
input. Repository/oracle content hashes can still be compared separately. Original
input files and results remain the immutable record of this run.

Both output and task-data directories must be fresh. The controller runs nine
diagnostic tasks, pauses, then accepts `CONTINUE` only after reviewing the fixed
gate and installation checks. The six formal jobs total 90 tasks; no completed
cell is rerun, no failed repair is dropped, and no holdout is sent to a model.
The initial controller requires the existing local Git freeze; a source archive
alone is sufficient for running the documented evaluator CLI, but does not supply
Git history for that guard. For a separately reconstructed experiment use a new
plan and output directories and preserve any changed path/hash metadata.

Raw records, all parsed proposals, tests, reviews, feedback, regression witnesses
and per-candidate evidence are exported under each report group. Local full
workspaces and SQLite checkpoints remain excluded from product archives. The
comparison is a bounded local experiment, not a public benchmark/generalization
claim or permission to publish.
