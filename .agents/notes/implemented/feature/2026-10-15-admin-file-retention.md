# Agent Note: Administrator-controlled file retention

Status: implemented
Scope: backend/ocr_app/retention.py, backend/ocr_app/task_store.py, backend/ocr_app/routes.py, backend/migrations, frontend/src, frontend/tests, tests, ARCHITECTURE.md, FRONTEND_FIELDS.md, SPEC.md, RUNTIME.md, openapi.yaml, frontend/public/help/index.html
Last-verified: 2026-10-15

## Problem

The fixed seven-day business retention no longer fits shared use. The user authorizes administrators to select 7, 15, 30 days or never, applying to both existing and future files, with a warning dialog before saving. A frontend creation-plus-seven fallback would misrepresent the new policy.

## Decision

[Queued-work recovery](../bug-fix/2026-10-15-queued-retention-and-diagnostic-recovery.md) clarifies automatic expiry: QUEUED and processing states are both protected and counted as deferred. Completion, failure or cancellation restores eligibility using the original upload deadline. ACTIVE remains reserved for worker processing states; cleanup and impact counts share a separate retention protection set.

Persist one global policy and revision in an additive SQLite migration, defaulting to seven days. Finite deadlines use each task's original creation time; append and rerun never reset older uploads. Save requires administrator authorization rechecked inside BEGIN IMMEDIATE, expected_revision and explicit confirmation. Recompute finite task deadlines in that same transaction; preserve recognition data, manual edits, revisions, account data and artifact references. Never disables automatic expiry, including startup cleanup, and returns null deadlines. Existing NOT NULL expires_at is a dormant finite deadline while never is selected; it is neither exposed nor used for cleanup then. Avoid rebuilding the tasks table and its cascading dependants.

GET/PUT /admin/retention expose days (7/15/30/null), revision and advisory counts of already-aged tasks per option. Every frontend save first opens a dialog explaining new/old scope, upload-based age, original/results/history deletion, active-task deferral and no restoration of deleted data. Counts are a snapshot, not a promised deletion set. Cancel makes no request. The backend requires confirmed=true; stale administrators get 409. Saving the setting does not itself delete material: the existing periodic/startup cleanup applies the latest policy transactionally. Manual deletion and orphan removal remain available. Diagnostic logs keep their separate policy.

Batch/task DTOs show actual nullable deadlines, no seven-day client fallback. Batch metadata refreshes after save and through ordinary list polling. Settings audit records old/new days and revision, never file contents. The active policy remains seven days until an administrator chooses otherwise.

## Decision audit

- [Durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md), [expiry display](../../implemented/feature/2026-10-10-progress-detail-and-retention-display.md) and [person packages](../../implemented/feature/2026-10-12-person-material-packages.md) partially overlap: this replaces fixed seven-day policy/display, retaining ownership, original upload clock and history cleanup.
- [Required fields](../../implemented/feature/2026-10-10-configurable-required-fields.md) and [API authorization](../../implemented/bug-fix/2026-10-13-api-authorization-boundaries.md) supply existing shared-settings and transactional authorization conventions.
- Manual batch deletion, runtime/model lifecycle and proposed deployment decisions remain independently applicable. No note is wholly absorbed or archived.

## Alternatives considered

- Apply only to future uploads: avoids retrospective shortening, but the user explicitly selects existing and future files. Warn and confirm rather than silently preserving the old policy.
- Rebuild tasks to make expires_at nullable: clean physical representation, but SQLite table recreation risks cascading history/artifact loss. A singleton policy disables expiry without rewriting task schema; finite deadlines are recalculated when re-enabled.
- Reset every deadline from save time: gives old files a new grace period but silently changes the agreed upload-based age. Keep creation times and warn before shortening, including never to finite.

## Verification

Tests cover all four policies, original timestamps for old/new/appended tasks, never across restart, immutable business content, migration rollback, active-task protection, whole-history/artifact cleanup, role/session/CSRF fences, stale-save conflicts, cancel without a request, correct expiry labels and user manual. Tests use isolated synthetic files. The browser confirms cancel without change, saving 30 days, warning that two twenty-day-old files exceed 15 days, never persisting across reload and historical batch labels showing no automatic expiry. No real-model inference or production setting change is performed in these tests.

The nine new backend cases pass after correcting test-helper calls and limiting the legacy OpenAPI check to the new policy response and deadline properties. Existing store/settings/auth/cleanup tests pass; the additional 59 ownership, parallel-task, scheduler and schema regressions pass. All 200 frontend tests, typecheck and production build pass. Browser evidence is in output/admin-retention-20261015/ui-verified.json and confirmation.png; generated output is not tracked.

Local activation completes after an idle consistent snapshot and owned launcher shutdown. Migration0010 leaves all twelve pre-existing business/account tables byte-for-byte equivalent at the row level; only Alembic revision and the new default policy differ. It preserves 307 tasks, two accounts and 3,138 artifact/key files. Both models load and warm successfully, thirteen served static files match the verified build, and anonymous settings access returns401. Current policy is still days7/revision0; no production administrator setting is selected by the agent. Activation evidence and the pre-update snapshot are under output/admin-retention-20261015. This activates the Windows local copy, not the separate Mac deployment.

## Consequences

Shortening can make existing stopped files immediately eligible for the next cleanup; dialog counts can age after loading. Never retains disk usage until manual deletion or later policy change. Already deleted files cannot be recovered by extending retention. Changes commit with cleanup and upload serialized by the existing write transaction lock.

The [account operation audit](2026-10-16-account-operation-audit.md) adds administrator history. Audit summaries survive material expiry while before/after business values remain in expiring encrypted review artifacts.
