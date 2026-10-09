# Agent Note: Let a named administrator create workbench accounts

Status: implemented
Scope: backend/ocr_app/auth.py, backend/ocr_app/routes.py, backend/ocr_app/api.py, backend/ocr_app/launcher.py, backend/manage_account.py, frontend/src, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, ARCHITECTURE.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user explicitly supplies an initial HRSSC credential and requests an administrator who can create further accounts. The earlier [password-session decision](2026-10-09-web-password-sessions.md) supports named roles but permits account setup only through a local CLI. The supplied password has eight characters, below the earlier ten-character policy. Its plaintext must not be copied into source files, notes, diagnostics or command arguments. Excel stays pending the business template with a separately authorized manual-opinion placeholder.

## Decision

Provision HRSSC as admin using hidden terminal input and the existing Argon2id account store. Account names remain case-insensitive. Change the creation/reset minimum to eight characters; preserve the 128-character maximum and login throttling. This follows the user's specified credential rather than silently substituting one.

Add admin-only GET and POST /api/v1/admin/users and an account-management tab visible only to admin. Return only user_id, username, display_name, role and enabled. New users default to operator; admin may select viewer or admin. POST creates a user atomically and rejects case-insensitive duplicates with USERNAME_EXISTS/409, without resetting the existing account, revoking its sessions or modifying its role. The CLI retains its deliberate reset/disable behavior. No schema change is necessary.

Every management request verifies current session/role; writes also use existing same-origin and CSRF protections. Account management never exposes password hashes or tokens. Request bodies are bounded and invalid values have safe errors. Clear password inputs after a submitted attempt; do not store credentials in frontend storage. The user authorizes current Windows account setup and management, not an unqualified Mac/network migration.

## Decision audit

The [frontend rebuild](2026-10-08-frontend-rebuild-element-plus.md) retains its task monitoring, expiry handling and saved-result UI. This decision adds only the admin account tab and public account DTOs; no browser self-registration, reset or disabling page is added.

The password-session decision partially overlaps: revoke/expire/cookie/CSRF and named task actors stay; the CLI-only administration choice is superseded only for listing and creating users, and the minimum length changes to eight. Its previous rationale remains recorded. [Hosted deployment](../../proposed/architecture/2026-10-09-hosted-web-session-auth.md) retains Mac/TLS/migration qualification. [Business Excel](2026-10-09-business-xlsx-layout.md) keeps its layout pending the business template, apart from its separately authorized manual-opinion placeholder. No decision is wholly superseded or archived. Related proposed/implemented/rejected notes and auth scope were searched before this decision.

## Alternatives considered

- Keep CLI-only setup: least code and an adequate small-team deployment tool; it does not satisfy the user's explicit in-application administrator requirement.
- Let create behave like the existing CLI upsert: reuses all SQL, but a typo/repeated submission can change another account's credential and permissions. Use atomic create-only behavior for the web route.
- Keep the ten-character rule and invent a longer initial password: retains the prior policy, but contradicts the exact user-provided credential. Adopt eight characters explicitly.
- Build full self-service registration/reset/deletion: handles larger teams; the user asks only for administrator-created accounts, so preserve the CLI for resets/disabling and add only listing/creation.

## Verification

Five real-HTTP/concurrency regressions pass: admin creation and new-user login, unauthorized roles, origin/CSRF, malformed/oversized inputs and case-insensitive/concurrent duplicate preservation. All 452 backend tests pass in 109.138 seconds; the final frontend passes 64 tests and typecheck/build. [Owned Edge acceptance](../../../../output/repairs-20261009-v1/admin-browser-2/summary.json) qualifies that final build with five checks for admin UI, viewer creation, password-field clearing, duplicate rejection, new-user login/permissions and refresh restoration, with zero browser errors, model calls or production writes. The earlier 63-test/browser-1 evidence remains preserved. The later manual Excel placeholder passes all three workbook tests without changing export gates.

Production activation confirms zero queued/active tasks, saves a consistent pre-migration SQLite snapshot and the previous frontend build, provisions HRSSC through hidden terminal input, confirms the old owned launcher/model trees exit and starts version1.15.0. Real HTTP verifies the supplied admin login, admin listing, identity restoration, logout and subsequent401 without writing passwords/tokens into artifacts. Both recognition models report ready; no accuracy benchmark or Mac claim is inferred from this startup. Account setup deliberately resets only the user-authorized initial HRSSC account. Activation evidence is in [report](../../../../output/admin-activation-20261009-v1/REPORT.md).

## Consequences

An eight-character minimum is weaker than the previous ten-character floor; bounded login attempts remain enforced. Admin can grant admin privilege, so server-side role checks are necessary on every request. Account creation may be retried after a network failure and return a duplicate; the UI must display that outcome rather than treat it as a reset. Real Mac/proxy deployment remains unqualified.
