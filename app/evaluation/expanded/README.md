# Expanded synthetic pilot corpus

Ten independent repositories cover status codes, pagination, percentages, timezone
offsets, CSV round trips, two-file checkout arithmetic, duplicate reservations,
TTL boundaries, Unicode accents and recursive configuration merging.

Each repository has passing pre-existing tests, one intentionally buggy behavior,
and an unused historical module that adds retrieval noise. `acceptance/` and
`references.json` are evaluator-owned and outside every repair snapshot.
References validate that each case is solvable; they are never model responses.
The two-file checkout case requires changes to both public functions.

This remains a synthetic corpus, not ten independent real-world projects.
Repeated calls are useful for measuring run variability, not independent samples
of software projects. Latency with multiple workers includes shared resource and
provider load; do not infer intrinsic mode speed from it.

The default three-case dataset is unchanged. To run this corpus with a temporary
live credential already present in the process environment:

```powershell
$env:REPOPILOT_REPOSITORY_ROOT = 'app/evaluation/expanded/repos'
$env:REPOPILOT_MODEL_MIN_INTERVAL = '7.5'
python -m app.evaluation.runner --dataset app/evaluation/expanded/dataset.json --repeats 3 --workers 3
```
