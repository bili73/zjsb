# Agent Note: Isolate recognition batches by immutable uploading account

Status: implemented
Scope: backend/ocr_app, backend/migrations, frontend/src, frontend/tests, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, frontend/public/help
Last-verified: 2026-10-10

## Problem

The application now serves a department. Authentication and role checks currently permit every signed-in account to list and read every batch. Operators must see and operate only their own material; administrators retain access to all batches. Batch attribution and editing an account's display name are missing.

## Decision

Persist an immutable owner ID on each batch, inherited by every task. New ownership comes only from the authenticated uploader. Backfill existing batches only when every surviving task has creation audit evidence with one shared actor; ambiguous or missing evidence stays unassigned and administrator-only. Keep historical actor IDs even when no current login matches them. Do not assign legacy batches to the current administrator.

Scope list queries before pagination and totals. Check batch ownership before reading task/result/page content or attempting review, rerun, cancellation, preview, reveal or export. Explicit mixed-account exports fail as a whole before decoding results or writing access history. Non-administrators receive the same 404 for foreign and missing IDs. The existing viewer role is similarly scoped and remains read-only. Administrator-only deletion and required-field configuration stay unchanged. Worker operations remain trusted internal operations without browser principals; every HTTP business entry supplies a verified principal. Cross-batch duplicate warnings are limited to the same owner's material.

Expose an owner descriptor with current account name/username when present. Preserve an encrypted attribution snapshot when creating a batch and immediately before deleting a login. Deleted-account batches remain administrator-only; recreating the same username gets a different UUID and cannot inherit them. Unrecoverable historical names are explicitly labeled as historical/unknown rather than invented. Display name edits do not change ownership, username, role, password, enabled status or sessions. Administrators edit names, including their own, through the existing guarded account API. Switching identities clears results, preview URLs and in-flight monitor responses.

## Decision audit

- [Password sessions](../../implemented/feature/2026-10-09-web-password-sessions.md): partial overlap; retain session restoration, CSRF and every-request account validity.
- [Account lifecycle](../../implemented/feature/2026-10-10-account-lifecycle-management.md): partial overlap; add name editing and preserved deleted-account attribution without changing password/state protections.
- [Durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md): partial overlap; retain immutable task/run versions, audit, retention and processing, add batch ownership.
- [Batch deletion](../../implemented/feature/2026-10-10-delete-recognized-batches.md): partial overlap; retain administrator-only deletion and transactional session checks.
- [Hosted authentication](../../proposed/architecture/2026-10-09-hosted-web-session-auth.md): partial overlap; local multi-user isolation does not qualify Mac deployment, proxy or network exposure.
- Searches of proposed, implemented and rejected notes find no prior implemented batch-isolation contract. Unrelated rejected medical and certificate decisions remain unchanged; no note is archived.

## Alternatives considered

- Filter only the frontend: the smallest visible change, but direct task/result/image/export API calls would still expose colleagues' material. Enforce ownership on the server as well.
- Reconstruct ownership from audit on every request: avoids a schema change and uses existing evidence, but makes hot authorization depend on mutable history joins and cannot retain display names after login deletion. Backfill once and persist owner identity instead.
- Assign all legacy batches to the initial administrator: makes old data immediately appear under a named account, but invents ownership and could transfer another person's material. Preserve original IDs and administrator-only access when unmatched.

## Verification

Eleven isolated regressions cover administrator/all versus operator/own and viewer/own lists, date/pagination totals, direct foreign IDs for every available read/write route, atomic mixed exports, duplicate-warning isolation, immutable ownership after administrator actions, deletion/recreation, safe migration of missing/conflicting evidence, name-edit validation and revoked-administrator checks. The [full backend regression](../../../../output/account-ownership-backend-full-v3.txt) passes 561 tests. The [frontend regression](../../../../output/account-ownership-frontend-v3.txt) passes 103 tests, including delayed old-session writes. [Typecheck/build](../../../../output/account-ownership-build-v3.txt) passes. The [final real-HTTP browser report](../../../../output/account-ownership/browser-f13f08c71415447b988f254a78d1efe4/report.json) qualifies twelve multi-account display, access, name-edit, deletion/recreation and session-switch checks with zero browser errors, model calls or production writes. The extended browser run first exposes stale deleted-account attribution when monitoring has stopped; account deletion and enabled-state changes now request the same metadata refresh as name edits. The failed report and earlier ten-group passing report remain preserved. Production materials and credentials are never modified for testing.

Prior failing measurements are preserved. Older HTTP fixtures registered material under arbitrary actor strings rather than the test's login ID; they now use the actual synthetic authenticated identity, and the named-session review fixture uploads after named login. The old migration fixture directly constructs the v0001 shape instead of calling the current writer against an outdated schema. A security test falsely matched the digits 123 inside a random UUID; its assertion now scans every textual business value and ignores only validated structural UUID fields. It still checks that the synthetic CVV digits never appear in results or attempts. DPAPI verification requires the current Windows user profile, unavailable inside the restricted test environment; the DPAPI test and full final regression pass in the authorized native-user environment. No recognition behavior, deadline or accuracy claim changes.

The user requests immediate local activation while reporting missing medical output. Activation follows zero queued/active tasks, a consistent SQLite backup and a second unchanged-state check. The [activation record](../../../../output/account-ownership/activation.json) verifies application1.21.0/schema0005, all 191 original tasks, 36 batches, one login, original database columns, encrypted files and keys preserved; historical owner IDs match the audited backfill. Both models are ready, and served frontend files match the qualified build.

Read-only diagnosis finds saved results for the two latest completed medical tasks: 63 and89 items. The old process logs 93 TypeError failures at corrected_preview calling TaskStore._row after source files change; the old in-memory two-argument method and newly imported preview's principal argument explain the mixed-version failure. The old Paddle process is also stopped when cancelling another medical task; existing dual-resident policy does not reload it automatically. Restart restores both models. An [isolated frozen-output check](../../../../output/account-ownership/medical-display-d22ac8be2d0c40fe9ff13b2116d398f5/report.json) reads both saved results and all43 corrected previews through current HTTP routes; a browser renders17 fields,89 items and the loaded corrected image without console errors. It uses a synthetic login and separately encrypted store, makes no production writes and no model calls, and does not claim new OCR accuracy or repaired cancelled tasks. Changes to shared source modules must be activated together at an idle restart; live editing does not hot-upgrade an existing Python process.

## Consequences

The [pre-push isolation repairs](../bug-fix/2026-10-12-prepush-isolation-and-migration.md) also fence browser confirmation before a request exists, preventing old selected files from being submitted through a subsequent login. Backend ownership rules remain unchanged.

The [cross-session review repairs](../bug-fix/2026-10-12-review-repairs.md) preserve ownership checks and session fences while reconciling inaccessible batch404 responses and refreshed terminal task revisions. A missing first-page ID alone never removes a cached batch.

Account isolation prevents colleague material access through both UI and direct API calls while preserving administrator oversight. It adds one indexed owner ID and one encrypted snapshot to batches, plus authorization plumbing at each public boundary; worker operations deliberately retain their internal access. Legacy creation evidence cannot recover missing historical names. Those batches remain visible to administrators with an explicit historical label. Migration is additive and requires a consistent backup before activating the local service. This change does not enable remote access, transfer ownership, edit usernames/roles or change recognition behavior. The user approves this scope on 2026-10-10 before implementation. Local activation is independently verified after the idle backup and restart; recognition accuracy and inference speed are outside this change's qualification.

[Person material packages](2026-10-12-person-material-packages.md) extend batches with explicit encrypted attribution, versioned append and presence-only identity-card pairing. Existing ownership, task versioning, deletion and recognition boundaries remain; old tasks and their expiry are not changed by append.

[API authorization boundaries](../bug-fix/2026-10-13-api-authorization-boundaries.md) extend the live transaction session check to material operations, add default route authentication and protect full health/slow responses; this note retains its remaining decisions.
