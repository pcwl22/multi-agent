# Historical real-repository pilot

These are fixed historical bugs from two public projects, not injected bugs and
not claims about their current releases. No upstream or user GitHub writes occur.

| Project | Buggy revision | Upstream reference fix | Scope |
|---|---|---|---|
| [python-json-pointer](https://github.com/stefankoegl/python-json-pointer) | `8c0bfdd3b9b3c42c1cfec7334ab6bcaf8cad1353` | [b8fbae3](https://github.com/stefankoegl/python-json-pointer/commit/b8fbae380c74795b42de3e5a569519ab2dc8e8a8) | Oversized integer indices must retain public exception/default contracts. |
| [itsdangerous](https://github.com/pallets/itsdangerous) | `85b1e3b76e0e37473dc286450ada725cd02981b4` | [37f0997](https://github.com/pallets/itsdangerous/commit/37f09970fa32a330a6660ded3abdb264086531b5) | Invalid-signature timestamp overflow must retain the public signature-error contract. |

The controlled export preserves original Git files byte-for-byte. Task snapshots
then follow the normal bounded-text policy (unsupported docs/binaries are omitted);
all original Python tests remain present and unchanged. The jsonpointer project
keeps its suite in `tests.py`; a new collection
adapter exposes its existing unittest classes to our fixed `pytest tests` entry
point. No original test is edited. The itsdangerous baseline already includes its
upstream failing test. The source layout is `src/`; the Docker runner includes
both `/workspace` and `/workspace/src` on its Python path.

Both projects have no third-party runtime dependencies at these revisions.
itsdangerous's original tests require freezegun. Its locked test dependency
closure is `freezegun==1.5.5`, `python-dateutil==2.9.0.post0`, `six==1.17.0`.
Dependency installation happens while building a separate image, never during
network-disabled repair tests and never by executing target code on the host.
This pilot does not establish arbitrary dependency/build-system support.

Acceptance sources are stored as `.py.txt` to preserve the exact frozen bytes
without making documentation files part of repository test collection. Preparation
copies them to `.py` outside the repair source root. Tests exercise related public
APIs across modules, original preservation behavior and independent holdouts.
The reference source is evaluator-only, outside the allowed repair root too.
The pilot is not a benchmark requiring multi-file edits to solve each bug.

Reproduce from the source distribution in PowerShell 7:

```powershell
git clone https://github.com/stefankoegl/python-json-pointer.git .repopilot/pilots/upstream/jsonpointer
git clone https://github.com/pallets/itsdangerous.git .repopilot/pilots/upstream/itsdangerous
python scripts/prepare_real_pilots.py --upstream .repopilot/pilots/upstream --output .repopilot/pilots/fresh
python -m pip download --only-binary=:all: --dest sandbox/pilot-wheels freezegun==1.5.5 python-dateutil==2.9.0.post0 six==1.17.0
docker build --network=none -t repopilot-pilots:local -f sandbox/Dockerfile.pilots sandbox
$env:REPOPILOT_REPOSITORY_ROOT = '.repopilot/pilots/fresh/repos'
$env:REPOPILOT_DATA_DIR = '.repopilot/pilots/fresh-data'
$env:REPOPILOT_SANDBOX_IMAGE = 'repopilot-pilots:local'
$env:REPOPILOT_MODEL_MODE = 'live'
$env:REPOPILOT_MODEL_NAME = 'deepseek-v4.1-flash'
$env:REPOPILOT_MODEL_BASE_URL = 'https://muyuan.do/v1'
$env:REPOPILOT_MODEL_MIN_INTERVAL = '7.5'
$env:REPOPILOT_MODEL_TIMEOUT = '120'
$env:OPENAI_API_KEY = Read-Host 'Provider key' -MaskInput
python -m app.evaluation.runner --dataset .repopilot/pilots/fresh/dataset.json --repeats 1 --workers 2 --output .repopilot/pilots/fresh-results
Remove-Item Env:OPENAI_API_KEY
```

Use a fresh output/data directory for every run. Availability of that provider's
model ID is service-dependent; do not infer the actual upstream model identity.
Coordinate other key-using processes; request pacing is process-local.

The preparation script was verified to recreate all 82 files in the actual
controlled sources and holdouts exactly. Original/reference Docker evidence and
live results are recorded separately; reference fixes never count as model repairs.
