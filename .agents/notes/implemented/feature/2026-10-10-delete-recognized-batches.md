# Agent Note: Delete stopped recognition batches and their owned data

Status: implemented
Scope: backend/ocr_app/task_store.py, backend/ocr_app/routes.py, backend/ocr_app/api.py, backend/ocr_app/diagnostics.py, frontend/src, frontend/tests, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, frontend/public/help/index.html, RUNTIME.md
Last-verified: 2026-10-10

## Problem

Recognized batches cannot be removed from the workbench. The existing SPEC and future OpenAPI deletion contract require all tasks to be terminal, excluding NEED_REVIEW even though its machine processing has stopped. The user approves administrator-only permanent batch deletion, including NEED_REVIEW, on 2026-10-10 after reviewing the scope.

## Decision

DELETE /batches/{batch_id} accepts a complete task/run/revision snapshot. Within the same BEGIN IMMEDIATE transaction, recheck the current administrator session, batch membership, allowed states and each version. Only NEED_REVIEW, COMPLETED, FAILED, REJECTED and CANCELLED are deletable; QUEUED and active states reject the entire request. A rerun or review accepted since confirmation produces a conflict, never a partial deletion. Missing batches return404; requests are not automatically retried.

Cascade task-owned runs, attempts and artifact metadata, remove the batch and retain value-free task/batch deletion audit events. After commit, unlink only the captured owned encrypted blob references. Never touch supplied external originals, independent batches, downloaded workbooks, diagnostics or backups. File unlink failures are logged and explicitly returned as cleanup_pending; existing startup orphan cleanup retries them. Database failure rolls back everything and does not unlink files. This is application deletion, not secure erasure of SQLite pages or backups.

The administrator sees a batch deletion button and an irreversible confirmation listing the batch and task count. Unloaded or running batches cannot be deleted. Successful deletion removes cached rows, selection and local object URLs, closes a corresponding result drawer and invalidates stale list/task reads before resuming monitoring. Date filters remain selected and pagination restarts safely. There is no bulk deletion or recycle bin.

## Decision audit

- [Durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md): partial overlap; retain transaction, retention, audit and artifact ownership rules, add explicit user deletion.
- [Calendar browsing](../../implemented/feature/2026-10-09-batch-calendar-browser.md): partial overlap; retain date filtering and hidden running jobs while removing deleted cache entries.
- [Account lifecycle](../../implemented/feature/2026-10-10-account-lifecycle-management.md): partial overlap in transactional session revalidation, but account deletion continues to preserve business tasks.
- [Human review/export](../../implemented/feature/2026-10-08-human-review-and-xlsx-export.md): partial overlap in encrypted review/access history; delete all task-owned artifacts, not just the current run.
- Existing architecture proposals and rejected recognition strategies are unrelated; none is superseded or archived.

## Alternatives considered

- Hide records only: reversible and less disruptive, but retains unwanted documents and disk use. Follow the approved permanent deletion scope instead.
- Restrict deletion to existing terminal states: reuses the published classification, but forces artificial review completion before removing stopped records. Add NEED_REVIEW to deletion eligibility without redefining it as reviewed.
- Delete files before committing SQL: immediately frees disk space, but a database rollback could retain tasks whose sources are gone. Commit logical deletion first and report incomplete physical cleanup explicitly.

## Verification

Nine isolated backend deletion tests cover roles, Origin/CSRF, revoked administrator sessions, whole-batch version coverage, all allowed and blocked states, concurrent rerun/review, transaction rollback, all historical artifacts and cross-batch independence. The complete540-test backend regression passes. The first full run exposes an existing ordering test that assumes two uploads cannot share a wall-clock tick; its deterministic fixture now supplies two explicit timestamps without changing production sorting. The original failed log remains at output/batch-deletion-backend-full-v1.txt and the passing run at output/batch-deletion-backend-full-v2.txt.

All92 frontend tests pass, including late list/task reads, calendar pagination, failure-preserved results and preview revocation with an in-flight matching fence. Typecheck/production build pass. The [real-HTTP browser probe](../../../../output/batch-deletion/browser-53d1c64d9e5d45cbb6a1e748d849f541/report.json) passes6 checks: queued blocking, confirmation cancellation with no DELETE, NEED_REVIEW deletion and peer isolation, persistence after reload, rerun conflict and operator visibility. It records zero page errors, model calls or production writes; browser/server resources close. No production batch is deleted to test this feature. Application/OpenAPI1.19.0 and SPEC v1.25 describe the implemented contract; the web help includes deletion steps.

The idle Windows service is backed up and restarted as1.19.0. [Activation evidence](../../../../output/batch-deletion/activation.json) verifies identical fingerprints for all database tables, owned encrypted blobs and secrets:123 tasks and1 account remain, both models are ready. The new anonymous DELETE returns401 without touching a batch, and served help matches the qualified build. The initial static verification catches the one-off publication script skipping nested help/index.html alongside the root index; the old help is preserved, the script is corrected and final full-file verification passes. Old frontend assets and the preceding index remain recoverable. DDE tree verification passes52 notes.

## Consequences

The [cross-session review repairs](../bug-fix/2026-10-12-review-repairs.md) also remove a batch confirmed inaccessible by its own task-list404, clear its pending actions/previews and close its drawer, while other jobs keep polling. Pagination resets and totals reconcile from the server. A batch omitted by pagination or filtering is retained.

Permanent deletion is not recoverable through the application. A filesystem failure after SQL commit leaves inaccessible encrypted orphan files until maintenance/startup cleanup; the UI does not claim complete cleanup. Already-issued downloads or in-flight read snapshots cannot be recalled. Deployment uses a backed-up idle backend restart; no queued or active tasks are interrupted.

[Person material packages](2026-10-12-person-material-packages.md) extend batches with explicit encrypted attribution, versioned append and presence-only identity-card pairing. Existing ownership, task versioning, deletion and recognition boundaries remain; old tasks and their expiry are not changed by append.
