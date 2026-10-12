# Agent Note: Fence pending upload confirmations, pagination and SQLite schema changes

Status: implemented
Scope: frontend/src/components/UploadPanel.vue, frontend/src/monitor.ts, frontend/tests, backend/ocr_app/db.py, tests
Last-verified: 2026-10-12

## Problem

The user requests review of all pending code before committing and pushing. Three independent reviewers reproduce two release-blocking defects and one metadata regression. An upload confirmation can resolve after its component is unmounted and the shared monitor changes accounts, sending the former account's selected files through the new account. An interrupted SQLite0006 migration can permanently add its first column without advancing the version because legacy SQLite transaction mode does not begin a real transaction for DDL; restart then fails on a duplicate column. A delayed page-two response can overwrite newer package metadata after terminal polling has stopped, restoring an old revision and pairing/name data.

## Decision

Lock the complete upload/confirmation operation against reentry, capture the client, target/version, mode, files and types before asking the attribution question, and cancel its continuation after unmount, abort, identity change or selection changes. Preserve existing accepted/unknown upload outcome handling. Pending UI confirmation is not authorization to submit through a later login. Actual Vue component lifecycle tests exercise the SFC rather than testing only the monitor helper. Unmounting before any request starts does not display an unknown-upload-outcome warning.

Keep pagination results from downgrading already loaded batches by comparing the batch object captured before the page request with the current reference. A batch refreshed during that request keeps its newer metadata. Reconcile applied new/changed pagination data through the existing fenced refresh path, waking the read loop only when the accepted page needs task reads. Retain list/session generation and abort guards; do not infer deletion from page membership or add a persistent cache.

Explicitly begin the SQLite migration transaction before any Alembic DDL so schema statements and version updates commit or roll back together. Dispose the newly created engine on migration failure. Preserve the numbered migration chain and existing data; no new migration or destructive repair is required for the production database. Interrupted0006/0007 fixtures must roll back and restart cleanly.

## Decision audit

- [Atomic mixed upload](../../implemented/feature/2026-10-12-person-package-single-submit.md) and [account ownership](../../implemented/feature/2026-10-10-account-owned-batches.md): partial overlap; extend browser confirmation lifetime guards without changing backend atomicity or ownership.
- [Refresh reconciliation](../../implemented/bug-fix/2026-10-12-qualified-normal-and-refresh-retry.md) and [package name updates](../../implemented/feature/2026-10-12-person-package-name-suggestions-and-export.md): partial overlap; prevent late pagination from reversing reconciled metadata.
- [Durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md): partial overlap; enforce SQLite's actual migration atomicity rather than relying on a SQLAlchemy transaction label.
- Other proposed deployments and rejected clinical/location features concern different decisions. No note is wholly superseded or archived.

## Alternatives considered

- Check authentication only when the request starts: protects ordinary requests, but the old files can be captured before any request exists and then submitted using a new client. Fence the confirmation itself.
- Disable the upload button only after confirmation: avoids showing a busy state during the dialog, but allows multiple pending confirmations and stale continuations. Lock the entire action.
- Apply all pagination responses and wait for manual refresh: preserves simple upsert behavior, but can roll package revisions backward while polling is stopped. Reconcile through the guarded current-data path.
- Add duplicate-column suppression to each migration: can restart a partly applied schema, but does not prove all DDL and version/data changes committed together. Use a real transaction and explicit failure cleanup.

## Verification

The original independent failed probes remain under output/prepush-review-20261012/. Seven actual-SFC lifecycle regressions cover unmount/client replacement, reentry, successful append and single-type submit, cancellation/retry, abort and changed selection/permission/package revisions. The original cross-account reproduction is rerun against the fix.

Pagination regressions cover an old overlapping page released after a completed refresh, plus new or changed page entries arriving after the loop stops. Name, pairing, package and task revisions retain their latest values; pending task reads are consumed. Unchanged or skipped old pages do not force unrelated terminal tasks to refresh.

Fault injection after the first DDL of0006 and0007 proves that schema, version, business/account/session rows all roll back, the failed engine is disposed, and two subsequent startups succeed through0008. Full backend662 and frontend135 tests pass; original auth/storage73 targeted checks and independent migration restart probe pass. Frontend typecheck/build pass with the existing chunk-size advisory. Independent SFC probes additionally cover mode/abnormal/target changes, preview-time unmount/client replacement, optional preview failure and new-task-only binding; the original late-pagination probes and the stopped-loop variants pass. No blocking finding remains in the three reviewed scopes. Source and DDE gates are recorded in the pre-push review evidence directory.

## Consequences

Locking during confirmation also disables classification/type edits until the dialog finishes; cancellation releases the lock and retains the user's files. SQLite startup obtains its write lock before schema changes and keeps the existing bounded busy timeout. These repairs do not qualify Mac/HTTPS deployment or change extraction rules. No real recognition, source materials, credentials or runtime outputs enter Git. The user explicitly authorizes pre-push review and repairs; no production database or account is modified by these tests.
