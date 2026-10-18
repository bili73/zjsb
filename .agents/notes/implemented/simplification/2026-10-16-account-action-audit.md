# Agent Note: Keep audit focused on concise account actions

Status: implemented
Scope: backend/ocr_app, frontend/src, frontend/public/help, tests, frontend/tests, scripts/probe_operation_audit_browser.cjs, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, RUNTIME.md
Last-verified: 2026-10-16

## Problem

The user finds the newly activated audit too noisy: worker lifecycle, previews and field comparisons obscure who uploaded, exported or changed administration settings. The user approved the explicit simplification plan on 2026-10-16.

## Decision

Keep account login/logout and account management, upload/append, completed or failed export, batch deletion, explicit rerun/cancel, and global settings. Stop new worker/maintenance, preview/reveal/region OCR, person confirmation and review audit events. Preserve encrypted recognition/review/access history and all existing audit rows. Apply the same allowed event/actor policy before pagination, options, detail lookup and Excel export, including old records. Login failures remain identifiable as unverified attempts, never as the claimed account.

New upload/append/delete/export actions produce one audit row per submitted operation, with counts and batch IDs. Successful exports record completion only after generation and permission revalidation; failures record one failure, never successful generation. Keep legacy request outcomes unknown. Fold session replacement into the login row. Human-readable summaries describe settings and targets; remove the frontend technical/detail drawer and material before/after comparisons. Keep the detail endpoint compatible but no longer read review artifacts. No schema change, historical deletion or new external service.

Upload and export filter choices include their historical event aliases, avoiding duplicate options that return incomplete subsets. A combined export remains discoverable under any selected batch. The original task/run/version evidence remains in encrypted access history. Batch label snapshots use observed document types and UTC+8 creation time; no OCR values or source filenames enter permanent summaries.

## Related decisions

Partially supersedes [broad account-operation audit](../../implemented/feature/2026-10-16-account-operation-audit.md): transaction integrity, account identity snapshots, admin-only permission rechecks, safe storage and migration remain; event scope, granularity and presentation change. The existing diagnosis/retention/account notes remain applicable. Scope query and proposed/rejected inspection found no competing account-audit proposal; hosted-auth and model-deployment proposals are unrelated.

## Alternatives considered

- Frontend-only filtering is smallest and preserves every detail, but database growth and Excel would remain noisy. Filter at storage and query boundaries.
- Delete old noisy rows reduces disk usage immediately, but is unnecessary irreversible history loss. Preserve them and exclude them from product audit.
- Retain detailed field diffs helps forensic review, but conflicts with the explicitly requested concise action view. Preserve original version artifacts independently.

## Testing

The focused 49-test audit/deletion/session/settings suite passes. After the final event aliases and upload rollback regression, all 24 audit tests pass. Coverage includes excluded writes, legacy filtering before pagination/options/detail/export without deleting records, multi-file/multi-batch aggregation, failed export honesty, settings summaries, immutable identity, transactional failures, permissions and retained review artifacts. Frontend 231 tests, typecheck and isolated production build pass (existing large-chunk warning). Four isolated Edge groups pass under output/operation-audit/attempt-goxyVi/ with zero business API calls; the UI shows Chinese summaries and no technical/review drawer. A read-only production count finds 453 visible account actions among 3004 existing rows, with no data mutations (output/operation-audit/simplified-scope-check.json). No production restart, Git publication or Mac activation is implied by these checks.

The full backend regression passes 881 tests in 374.253 seconds (tmp/audit-simple-backend-full.log); the final audit-only suite above covers the subsequently added alias/rollback cases (tmp/audit-simple-final-focused.log). Earlier failed compatibility expectations and the repaired test syntax error remain in separate logs. DDE tree/link/index verification and git diff checks pass.

## Consequences

Old uploads without a shared request ID cannot be safely merged and stay as historical individual records. Audit cannot certify browser downloads. Filtered history remains in backups/database. Serious diagnostic logs are unchanged.

The [bounded HTTP write refinement](../bug-fix/2026-10-16-bounded-http-writes.md) commits generated-export audit and prepared access-history references in the same final version-checked transaction. Controlled overload responses do not recursively write audit failures into an already busy database; genuine unexpected operation failures keep existing diagnostic handling.

## Windows activation

At the user's restart request on 2026-10-16, published the tested tmp/audit-simple-final-dist and restarted the owned launcher tree in dual_resident mode after verifying no queued, active or expired tasks. The consistent snapshot and verification are in output/simple-audit-activation-20261016-110646/. Schema remains 0011; all 13 existing business tables, 272 tasks, 2 accounts, 1 session, 3016 audit rows and 2991 material/key files were preserved. All 16 served static files match the tested build; public health is ok and anonymous protected/audit endpoints return 401. Both model process trees are present; authenticated model readiness and a fresh OCR request were not tested, and no account/session was created or replaced for verification. No Git publication or Mac activation occurred.
