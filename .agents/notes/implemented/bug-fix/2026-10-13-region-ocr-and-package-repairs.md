# Agent Note: Fence OCR process cleanup and preserve package edit/delete contracts

Status: implemented
Scope: backend/ocr_app, frontend/src, frontend/tests, tests, openapi.yaml, SPEC.md, RUNTIME.md, README.md, frontend/public/help/index.html
Last-verified: 2026-10-13

## Problem

Review of c576c85 reproduces three failures with synthetic inputs. Windows virtualenv Python redirects into a child process: subprocess.run's timeout reaps only the redirector while actual CPU work survives and the single OCR slot is released. A person-name draft takes the live package revision at save time, accepting a concurrent administrator's newer revision without reviewing that name. A legal 100-file package plus one-file append cannot be deleted because the delete request caps version entries at 100.

## Decision

Region OCR reuses the native JobProcess supervisor for the short-lived binary protocol. The ten-second execution budget, bounded output and one in-flight request remain; whole-job cleanup precedes slot release. Job cleanup has its existing five-second confirmation budget. Unconfirmed cleanup blocks subsequent local region OCR until restart. The client allows twenty seconds to receive execution/cleanup outcomes and shows manual fallback plus administrator check/restart guidance on persistent unavailability. The resident GLM/Paddle queues are unchanged.

Name editing captures a shallow package snapshot and submits its revision. A conflict retains the draft and asks the operator to cancel/reopen and review current information. Deletion request validation has no 100-entry ceiling; upload limits, complete task membership, administrator authorization, every run/revision check and atomic deletion remain.

## Related decision audit

- Partial overlap: [CPU region OCR](../../implemented/feature/2026-10-13-field-region-ocr.md) and [source text copying](../../implemented/feature/2026-10-13-source-region-ocr-copy.md) retain their UX, security and binary-worker decisions; correct their process cleanup fact and link this repair.
- Partial overlap: [Windows process lifecycle](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) retains atomic Job creation and whole-job exit confirmation; this repair reuses that supervisor for an additional CPU worker.
- Partial overlap: [person-name confirmation](../../implemented/feature/2026-10-12-person-package-name-suggestions-and-export.md) and [material packages](../../implemented/feature/2026-10-12-person-material-packages.md) retain shared package revisions and per-request upload limits; this repair fixes the editor snapshot.
- Partial overlap: [batch deletion](../../implemented/feature/2026-10-10-delete-recognized-batches.md) retains full-set version checks and atomic deletion; this repair aligns request validation with appendable package sizes.
- Relevant scope/topic searches also cover proposed and rejected decisions; unrelated platform/auth/clinical proposals are not superseded. No decision is fully absorbed or archived.

## Alternatives considered

- Keep subprocess.run: smallest portable transport with built-in communicate/timeout, but Windows redirector descendants outlive its kill and violate the one-worker invariant. Enumerating descendants with psutil is convenient but races new children; atomic Job membership already exists in this project.
- Use the latest revision at save: avoids conflicts after refresh, but applies an old draft to new information without operator review. Capturing the edit version preserves the existing optimistic concurrency contract.
- Cap whole packages at 100 files: preserves the old request validator, but contradicts per-request upload limits and leaves existing larger packages undeletable. Chunking deletion reduces each payload but breaks whole-package membership/version atomicity.

## Validation

Regression tests first fail on the old implementation for surviving timeout descendants, stale name edits, oversized deletion snapshots and the insufficient client timeout. The repaired implementation passes 690 backend tests in235.406 seconds and156 frontend tests, plus vue-tsc and an isolated Vite build. Logs: [backend](../../../../tmp/review-fixes-20261013/backend-tests.log), [frontend](../../../../tmp/review-fixes-20261013/frontend-tests.log), [typecheck](../../../../tmp/review-fixes-20261013/typecheck.log), [build](../../../../tmp/review-fixes-20261013/build.log).

Real lightweight Windows workers exercise timeout descendant cleanup, binary input, fragmented output, stderr backpressure and oversized stdout. Injected cleanup-confirmation failure reclaims the real test worker then proves subsequent requests cannot spawn. A legal100-file HTTP upload and one-file append delete all101 tasks with a complete current snapshot; partial/stale snapshots reject atomically without changing rows/files, and OpenAPI accepts the full request. Actual Vue component tests cover replaced and in-place mutated props, retained conflict drafts, deliberate reopen, unrelated metadata refresh, request budget and visible recovery guidance.

The [native Job probe](../../../../tmp/region-job-probe/report.json) confirms all five redirector/worker/descendant processes belong to the owned Job. Job accounting reaches zero before some terminated process objects become signaled; the test waits for actual exit within five seconds instead of treating immediate PID visibility as running CPU work. This preserves the existing supervisor's termination semantics and changes no shared native supervision code.

## Consequences

Regression verification uses isolated stores, synthetic files and lightweight subprocesses, with no production writes, model inference or backend restart during the repair phase. The subsequent user-authorized activation is recorded below. Job supervision is Windows-specific; no Mac or low-memory hardware support is claimed. Client disconnect does not cancel the server worker; execution and cleanup budgets still bound its lifetime.

The TaskResultDrawer.vue backdrop-close edit predates this repair and is preserved. DDE tree/link checks and the regenerated asset index accompany delivery.


## Activation

The user authorizes publication and backend restart on2026-10-13. The owned launcher tree is stopped only after empty queue/active/expired checks, a consistent integrity-checked SQLite backup, and an unchanged snapshot under a write lock. Previous frontend files and both secret files are backed up. A fresh candidate publishes13 static files and starts the unchanged dual_resident launcher without a browser. GLM and Paddle readiness is confirmed from current-launch successful load/warmup diagnostics and live owned model processes.

The [activation report](../../../../output/review-fixes-activation-20261013-144921/verified.json) confirms identical hashes/counts for all11 database tables,262 tasks,2 accounts and2727 owned material/key files, plus exact HTTP static content. Anonymous region OCR and full health remain401; public health exposes only status. No recognition benchmark or production document mutation is used for activation verification.


## Release 1.22.3

The user requests service version1.22.3 and authorizes committing and pushing the current repair set. FastAPI metadata, authenticated health, OpenAPI, current README/SPEC descriptions and the help-page version agree on1.22.3. Historical version records and the private frontend package version remain unchanged. The version-only update passes26 runtime API/contract tests; the full690 backend/156 frontend repair results above remain the behavioral validation. A fresh frontend candidate matches all13 published files.

An idle, backed-up restart activates the version. The [release verification](../../../../output/release-1.22.3-20261013-150130/verified.json) confirms both models ready, unchanged262 tasks/2 accounts and2734 owned material/key files against this release backup, exact static responses and anonymous401 fences. The full-health version is validated in isolated HTTP tests; production verification uses current-launch API source hashes without creating or replacing a login session.
