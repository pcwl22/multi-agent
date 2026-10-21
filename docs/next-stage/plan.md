# Next delivery stages

2026-10-16, Asia/Shanghai. Work builds on reviewed PR #2 head `edb60e0`.

1. Review PR #2. Completed locally; evidence in `pr2-review.json` and
   `pr2-review.md`. Merge remains subject to digest-bound human approval.
   User selected keeping the PR draft and continuing local validation; external
   publication is deferred for this delivery.
2. Expand to ten isolated cases and run three modes three times with a frozen
   corpus and independent holdouts. Preserve provider failures in original data.
3. Extract natural feedback recoveries. Supplement finite-failure behavior with
   explicitly labeled live fault injection, excluded from benchmark metrics.
4. Exercise the actual browser, HTTP API, live model, Docker, approval and PR
   publication path. Capture screenshots and video; preserve baseline/source.
5. Build wheel and source packages, verify packaged corpus, clean-environment
   instructions, changelog and release checklist. Prepare v0.1.0; publication and
   merging are separate final actions bound to the reviewed content.

The original three-case dataset and its tests remain unchanged. The expanded
dataset is synthetic and cannot establish general real-world repair performance.
Optional LangSmith upload is outside this delivery and remains unverified.
