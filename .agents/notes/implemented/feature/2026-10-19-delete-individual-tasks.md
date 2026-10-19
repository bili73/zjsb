# Agent Note: Delete one stopped task without deleting its peers

Status: implemented
Scope: backend/ocr_app, frontend/src, frontend/tests, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-19

## Problem

The workbench can delete a complete stopped batch, but cannot remove an unwanted file from a batch. The user approves individual deletion by the owning operator or an administrator, while preserving other materials, on 2026-10-19. Windows main is the primary development target; the portable change is also synchronized into the isolated Mac test branch without importing deployment configuration into main.

## Decision

DELETE /tasks/{task_id} accepts run_id and expected_revision. In one write transaction revalidate the session/role, task ownership, stopped state and exact version; capture only task-owned artifact references; append a value-free deletion audit and cascade its runs, attempts and artifacts. NEED_REVIEW and terminal states are eligible; queued/active tasks require cancellation and a confirmed stop first. Increment the remaining batch's package revision, or remove the batch if empty. Unlink captured blobs after commit, report cleanup_pending and retain startup orphan cleanup. Never delete external source files or peer tasks.

The task row has an irreversible confirmation. Success removes selection, previews and a matching drawer, invalidates stale monitor reads and reloads batch counts, name suggestions and ID-side pairing. Failure retains the current result and requires an explicit retry after refresh. Whole-batch deletion remains administrator-only.

## Decision audit

The [batch deletion decision](../../implemented/feature/2026-10-10-delete-recognized-batches.md), [account ownership](../../implemented/feature/2026-10-10-account-owned-batches.md) and [authorization boundaries](../../implemented/bug-fix/2026-10-13-api-authorization-boundaries.md) partially overlap and remain active. This adds an owner-scoped single-task action without weakening their existing batch or transaction contracts. Proposed/implemented/rejected topic and scope searches find no competing individual-deletion decision; no note is archived.

## Alternatives considered

- Reuse whole-batch deletion: its versioned transaction is already verified, but removing useful peer documents is unacceptable for a single unwanted file.
- Hide the task: reversible and cheap, but does not remove unwanted stored documents; the user approves permanent application deletion.
- Delete active tasks immediately: fewer clicks, but races worker publication and shared inference calls; require confirmed cancellation instead.

## Verification

Eight synthetic backend tests cover owner/admin access, foreign-user and viewer denial, CSRF, session revocation, concurrent save/rerun, rollback, every historical artifact, unlink failure, active-peer independence, package revision and last-task cleanup. Frontend tests cover exact request versions, stale responses, failed deletion, cancelled/unmounted confirmations, selection and the preview cleanup notification. Windows full backend regression runs973 tests (966 passed,7 skipped); the final focused36-test group,262 frontend tests, typecheck and production build pass. The full backend run predates only an additional passing login/read-concurrency test and frontend confirmation guards. Logs stay under ignored tmp/single-task-login-*. No online Mac write or restart is used for verification.

## Consequences

Deletion is permanent application deletion, not erasure of backups. A filesystem cleanup failure can leave an unreachable encrypted orphan until maintenance; the response and Chinese diagnostic must state this explicitly.
