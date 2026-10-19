# Agent Note: Direct numbered pagination for batches, audit and accounts

Status: implemented
Scope: scripts/probe_numbered_pagination_browser.cjs, backend/ocr_app/audit.py, backend/ocr_app/routes.py, frontend/src, frontend/tests, tests/test_operation_audit.py, scripts/probe_operation_audit_browser.cjs, openapi.yaml, FRONTEND_FIELDS.md, SPEC.md, frontend/public/help
Last-verified: 2026-10-16

## Problem

The user approved clickable page numbers across batches, audit and accounts after a read-only assessment. Batches already expose page/page_size/total but append pages in the monitor; audit has only cursor pagination and walks intermediate pages for a forward jump; accounts already slice a complete small list locally.

## Decision

The three lists use the installed Element Plus pagination control. Keep batch/audit defaults at 50 and accounts at 20, with 20/50/100 choices. Audit accepts page/page_size and returns items/total/page/page_size; legacy cursor/limit calls and next_cursor remain compatible. Reject mixed pagination modes. Total counts the complete filtered, visible audit scope before any cursor or offset, using the same explicit SQLite read snapshot as the selected rows. Preserve admin authorization and response-time revalidation, UTC+8 filtering, stable created_at/id ordering and full-filter export with its existing 10000-record limit. No schema migration.

Batch monitor separates the current page IDs from cached task state. Page changes do not erase task versions, pending actions, expansion or in-flight task tracking; background refresh must not append other pages into the visible page. Ignore stale page/date/session responses. Failed jumps preserve the displayed page; date/size changes reset to page one. After deletion or total shrink, load the last valid page. Accounts retain full-list administrator protection checks while rendering a page slice. Pagination uses live data: concurrent new records may shift later pages; no frozen multi-request snapshot is promised.

## Related decisions

[Audit query error codes](../bug-fix/2026-10-19-audit-query-error-codes.md) makes invalid/mixed filters and pagination AUDIT_FILTER_INVALID and oversized exports AUDIT_EXPORT_TOO_LARGE, both422. Page/cursor compatibility, empty beyond-end pages and snapshot semantics remain unchanged.

Partially replaces the cursor-stack paragraph in [audit toolbar](../../implemented/feature/2026-10-16-audit-panel-toolbar-restyle.md), while keeping its presentation and concise summaries. [Account panel](../../implemented/feature/2026-10-16-accounts-panel-restyle.md) retains local pagination. [Account action audit](../../implemented/simplification/2026-10-16-account-action-audit.md), [batch isolation](../../implemented/feature/2026-10-10-account-owned-batches.md) and [refresh retry](../../implemented/bug-fix/2026-10-12-qualified-normal-and-refresh-retry.md) remain constraints. Scope/topic inspection found no competing numbered-pagination proposal.

## Alternatives considered

- Add only total: smallest response change, but arbitrary jumps still require every intermediate cursor. Add direct page access instead.
- Keep cursor-stack jumps: stable continuation for growing logs, but latency and requests grow with distance, and empty terminal cursors can restart the list. Retain the legacy API only for compatibility.
- Load all audit rows into the browser: trivial slicing, but transfers/decrypts irrelevant history. Count in SQL and fetch one page.
- Server-page accounts: scales to huge directories, but this department's small list already supports paging and last-administrator checks. Retain the existing full-list endpoint.

## Verification

Direct page jumps make one immediate list request (except one bounded out-of-range correction). Count/list share visibility, aliases, batch membership, date and actor filters, with deterministic ties. Tests cover invalid/mixed modes, empty/deep pages, concurrent inserts, old cursor compatibility and revocation. Frontend tests cover batch date reset, stale requests, hidden active tasks, task revisions, failed jumps, deletion of the last item, account page-size reset and session clearing. Focused backend tests, the frontend suite/typecheck/build and isolated browser checks pass; no production records, accounts or sessions are mutated by tests.

Final evidence: 49 backend audit/ownership/authorization tests pass in 61.626s (tmp/numbered-backend-v2.log), 238 frontend tests pass (tmp/numbered-frontend-v4.log), and typecheck/build pass into tmp/numbered-pagination-dist-v2 (tmp/numbered-build-v2.log; existing large-chunk warning). Four audit browser checks pass in output/operation-audit/attempt-9XjgP5 and four account/batch checks pass in output/numbered-pagination/attempt-JdegBt, with zero business API requests and no browser errors. Tests include an accepted upload invalidating an older pending page request. Earlier failed test/selector attempts remain separate. No production static files were published and no service was restarted.

## Consequences

Exact counts and deep offsets cost more as history grows. Current local count-only measurement on 3022 audit rows was below 2 ms; this is not an end-to-end or large-scale benchmark. Do not introduce caching/index migrations without evidence. Existing uncommitted toolbar/account changes are preserved. Service activation and Git publication are separate from implementation validation.

## Windows activation — 2026-10-16

The user separately authorized restart. Activation evidence is in output/numbered-pagination-activation-20261016-143026. With no active or expired tasks, a write-locked SQLite snapshot and verified material/key/static copies were created before stopping only the owned launcher tree. Current HEAD was 2a358cd839f3492fa80c15bef807496cb182ba4d plus the existing working changes. AuditPanel.vue had changed after the earlier validation manifest; the current frontend passed a fresh typecheck/build into tmp/numbered-pagination-restart-dist and four isolated audit browser checks (output/operation-audit/attempt-uDZoev). A concurrent static build appeared during backup; both the original static snapshot and that intervening build (previous-dist) are preserved. Source hashes remained unchanged after backup.

Published the freshly verified frontend and restarted in dual_resident mode. Public health returns OK, seven protected paths including numbered audit requests reject anonymous access, and all 16 served static files match the activation manifest. All previous rows across 13 business/settings/session tables remain intact: 275 tasks, 2 accounts, 1 session, 3022 audit rows; all 3008 material/key files retain their hashes and retention remains 15 days/revision 1. Initial startup diagnostic checks found no owned-process ERROR/CRITICAL entries. Model processes are observed separately; authenticated model readiness was not tested and no account session was created or replaced for verification. No Git publication or Mac deployment was performed.
