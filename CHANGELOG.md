# Changelog

## 0.1.0 — release candidate, unpublished

- Optional per-task isolated attempts: complete candidates start from the original
  baseline; every prior workspace, wrong generated test, diff and evidence remains.
- Candidate identity joins the diff digest for isolated-mode approval/publication;
  old tasks retain their original workspace policy when server defaults change.
- Candidate preparation crash recovery, stale approval rejection, legacy task
  compatibility and three controlled wrong-test replays; full suite 143 passed,
  1 skipped. Replays are separate from actual live model benchmarks.
- Original-issue acceptance contracts and reviewer source context; a conservative
  AST coverage gate rejects constructor-input substitutions in new tests.
- Provider cooldown/manual retry with a finite budget, safe error categories and
  retained unknown usage; synchronous checkpoints and unrecorded-write detection.
- Fixed historical jsonpointer/itsdangerous pilots with frozen external holdouts,
  dependency wheel hashes and original upstream tests preserved.
- Actual process-loss recovery tests, real SDK controlled-transport failures and
  Streamlit recovery controls; prior local suite recorded 129 passed, 1 skipped.
- LangGraph planning, retrieval, coding, Docker testing, review and digest-bound
  human approval, with SQLite recovery and a finite shared retry budget.
- Read-only MCP tools, FastAPI, Streamlit, and explicit draft PR publication with
  remote baseline checks.
- Actual DeepSeek provider calls, a published draft repair PR, independent Docker
  acceptance and preserved failures; original three-case pilot remains available.
- Ten separate synthetic cases, including cross-file changes and retrieval noise;
  per-attempt evidence, corpus hashes and bounded parallel evaluation.
- Added range contract checks expose six incomplete repairs; preserve the original
  90/90 and report the stricter 84/90 without changing saved patches.
- Readable API rejection details in the UI, covered by a component test.
- Process-local endpoint request pacing; controlled live fault-injection
  experiments are labeled separately from benchmark results.
- Combined local demo launcher with hidden credential input and owned-child
  shutdown. Keys are never passed on command lines or written to configuration.

This is a local development prototype. Supported repairs are Python source and
new Python tests with a prebuilt pytest sandbox. General projects, distributed
workers and public multi-user hosting are outside the verified scope.
