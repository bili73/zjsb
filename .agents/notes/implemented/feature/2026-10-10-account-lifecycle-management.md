# Agent Note: Complete browser account lifecycle and password management

Status: implemented
Scope: backend/ocr_app/auth.py, backend/ocr_app/routes.py, backend/ocr_app/api.py, frontend/src, frontend/public/help, tests, frontend/tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-10

## Problem

The user requests basic account-management actions missing from the creation-only browser page: disabling, deleting and changing passwords. The existing CLI can disable or reset an account, while browser APIs only list and create. Existing sessions must stop working after account removal, disabling or password changes, without deleting historical recognition material.

## Decision

Extend administrator management with enable/disable, deletion and password reset for other accounts. Add a self-service change-password dialog to the logged-in user menu for all roles, requiring the current password and confirmation of the new one. Retain the established eight-to-128-character password policy, Argon2 hashing, same-origin/CSRF checks, bounded bodies and secret-free diagnostics. Reject incorrect current passwords without misclassifying them as an expired login. Clear password inputs on submission completion, close and unmount.

Deletion removes only the web_users row and its web_sessions, preserving task data, encrypted results and audit entries with their immutable actor IDs. Recreating a deleted username produces a new UUID; it never becomes the actor of historical records. No schema migration or task cascade is needed: the only account foreign key is web_sessions.user_id. Every mutation and its session revocations commit atomically. Recheck the acting administrator and target state inside the write transaction; reject self-disable/deletion and prevent concurrent requests from disabling or deleting the final enabled administrator. Re-enabling never restores old sessions; resetting a disabled account never implicitly enables it. Self-password change revokes every session and clears the requesting browser cookie after success.

The endpoints are PATCH /admin/users/{user_id} with enabled only, DELETE /admin/users/{user_id}, POST /admin/users/{user_id}/password with new_password, and POST /auth/password with current_password/new_password. Frontend forms confirm disable/delete and password reset explicitly and expose precise safe errors. Existing account creation remains create-only and rechecks the acting administrator session inside its final transaction after hashing. The local CLI remains an explicit recovery tool with its established reset semantics. No real account is disabled, deleted or assigned a new password during verification. Application/OpenAPI version is 1.18.0 and SPEC is v1.24.

## Decision audit

The [administrator creation](2026-10-09-admin-account-creation.md) decision partly overlaps; duplicate safety, initial provisioning and roles remain active, while this decision replaces its creation-only browser limit. [Password sessions](2026-10-09-web-password-sessions.md) continue to own Cookie/CSRF/expiry and legacy-key closure. [Web documentation](2026-10-10-web-user-manual.md) reflects the implemented management controls. The hosted Mac/auth proposal remains separate; rejected medical/localization proposals do not own this behavior. Scope and topic searches reveal no rejected account-lifecycle proposal or completely superseded implemented note; no note is archived.

## Alternatives considered

- Expose the CLI set_user upsert as a reset API: reuses hashing and revocation, but implicitly changes enabled status/name/role and confuses password reset with account reactivation.
- Introduce soft deletion and a new deleted_at column: retains a directory identity for future historical-name lookups, but requires migration and new username-reuse semantics for a feature whose current task/audit records already retain immutable actor IDs. Preserve existing history and delete only the login row instead.
- Administrator-only password resets: smaller interface, but makes every normal password change an administrator operation; self-service with current-password verification covers the basic change-password request without widening administrator access.

## Verification

Eleven isolated API/database regressions cover all roles, malformed/oversized bodies, origin/CSRF, missing targets, correct and incorrect current passwords, immediate revocation across multiple sessions, disabled-user resets, self/last-admin protection, concurrent administrator actions, transactional deletion rollback and unchanged historical task/audit/input bytes. The final 24-test auth/creation/session regression additionally proves that a creation in progress cannot commit after its administrator session is revoked. The preceding full 529-test backend regression passes; the original version-assertion failures and old 40ms pipeline timing failure are preserved separately, and the latter passes both focused and full rechecks without changing production budgets or weakening its assertion.

All 87 frontend tests and typecheck/build pass. [Real-HTTP isolated browser acceptance](../../../../output/account-lifecycle-20261010-v1/browser-report.json) covers seven groups: role visibility/current-account protection, disable cancellation and remote-session expiry, disabled-account reset/enable and secret clearing, viewer/operator self-change with incorrect and correct current passwords, delete cancellation/confirmation, and administrator self-change through the guarded form. It records zero page errors, model calls or production writes and empty browser local/session storage. A separate final [help probe](../../../../output/web-manual-20261010-v3/report.json) verifies stable help navigation, preserved pending upload, all chapter anchors/images and mobile layout. Earlier selector failures caused by the current-account badge and concurrent header styling remain in output; unrelated frontend styling is preserved. The neutral Word manual has eleven visually checked rendered pages, with updated login/account instructions.

The later [embedded-help integration](2026-10-10-embedded-help-integration.md) preserves concurrent frontend work; a fresh [final browser run](../../../../output/account-lifecycle-20261010-v2/browser-report.json) repeats all seven account groups and qualifies the drawer as an eighth group, recording its exact build index hash. Production [activation](../../../../output/account-lifecycle-20261010-v1/activation.json) follows an idle consistent SQLite backup and owned-process-tree restart: 123 tasks, one account, all business/policy table hashes and key hashes remain unchanged. Both models are ready; four new mutation endpoints return401 anonymously. No real account credentials are changed.

## Consequences

The [cross-session review repairs](../bug-fix/2026-10-12-review-repairs.md) extend transactional live-session revalidation to required-field settings, including a request whose streamed body completes after account disabling or logout. Account lifecycle and historical-material preservation remain unchanged.

The [account-owned batches](2026-10-10-account-owned-batches.md) refinement adds administrator display-name editing and encrypted batch attribution snapshots on login deletion. It retains UUID-based history and state/password protections, and restricts non-administrators to their own material. Deletion of a login still preserves tasks and results; recreating its username cannot inherit them.

The separate [batch deletion feature](2026-10-10-delete-recognized-batches.md) reuses transactional administrator session checks and permanently removes selected stopped business batches. This does not alter account deletion: deleting a login account still preserves its historical business tasks.

Account deletion is irreversible through the browser; historical material remains and an explicit confirmation is required. Recreated names have new identities. A password reset does not reveal or recover the old password. Password hashing is performed outside the SQLite write lock with a final state/hash check before committing, so concurrent resets cannot silently apply an obsolete self-change. The user approves this complete plan on 2026-10-10; implementation and isolated verification follow that authorization. The CLI remains a deliberate local recovery tool; network/Mac deployment qualification is separate.
