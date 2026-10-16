# Changelog

## 0.1.0 — release candidate, unpublished

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
