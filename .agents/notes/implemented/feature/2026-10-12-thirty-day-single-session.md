# Agent Note: Thirty-day login with one active browser session per account

Status: implemented
Scope: backend/ocr_app/auth.py, backend/ocr_app/routes.py, backend/migrations, frontend/src/App.vue, frontend/public/help/index.html, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, README.md, ARCHITECTURE.md
Last-verified: 2026-10-12

## Problem

The user requests thirty-day token validity and only one simultaneous device login per account, explicitly selecting that a successful new login invalidates the old login. Current opaque SQLite sessions expire after twelve hours and rotate only the supplied previous cookie; another browser can remain logged in. This is authentication behavior and persistent schema, not a UI-only change.

## Decision

New successful logins issue a random token with thirty-day absolute validity (30*24*3600 seconds), with matching Cookie Max-Age. Polling/restoration does not extend expiry. Keep hashed server-side tokens, HttpOnly/SameSite/CSRF, secure HTTPS cookies, rate limiting and transaction-time password/enabled recheck. After credentials are verified, delete all sessions for that account and insert the new one atomically. Failed credentials and rejected concurrent password changes do not revoke the valid session. Concurrent successful logins may respond out of commit order, but only the last committed token is valid; no automatic login retries.

Migration0008 reduces existing duplicate account sessions deterministically to the greatest expires_at, then token_hash tie-break, and adds a unique web_sessions(user_id) index. Retained existing tokens keep their original expiry; do not silently extend issued tokens. No account, password, task, encrypted material, ownership or review data is rewritten. The schema constraint and BEGIN IMMEDIATE protect concurrent login. Logout of an already displaced token does not delete its replacement. Existing disabled/deleted/password-changed account revocation stays immediate.

Single-device means one browser cookie session, not hardware fingerprinting. Tabs in the same browser profile share it; another browser/profile, even on the same physical device, replaces it. Existing401 behavior returns the displaced browser to login at its next protected request; accepted recognition tasks continue. Do not add WebSockets/heartbeat polling solely for logout, device registries or fingerprinting.

## Decision audit

[Password sessions](2026-10-09-web-password-sessions.md) partially overlaps: replace only twelve-hour lifetime and multi-browser sessions, retaining its credential, CSRF, restoration, migration and network-boundary decisions. [Account lifecycle](2026-10-10-account-lifecycle-management.md) and [account ownership](2026-10-10-account-owned-batches.md) remain active. Hosted Mac/TLS qualification remains separate. No note is wholly superseded or archived.

## Alternatives considered

- Reject new logins while an old device is active: avoids displacing a working user but can strand an account after losing the old device. The user explicitly selects new-login displacement.
- Identify the physical device by fingerprint/IP: appears closer to hardware exclusivity, but browsers cannot reliably prove a physical device and changing addresses/profiles produce false matches. Enforce one opaque browser session.
- Only delete previous sessions in application code: the one login writer already serializes transactions, but pre-existing duplicates remain and the database would not enforce the invariant. Add a small deterministic deduplication and unique index.
- Extend existing tokens to thirty days during migration: convenient, but increases validity of already-issued credentials without login. Only new successful logins receive the longer lifetime.

## Verification

Four isolated tests cover thirty-day Cookie/server expiry, non-sliding reads and restart restoration, successful second login/failed login/stale logout/protected reads and writes, concurrent single-row winner and another account isolation, and deterministic restart-safe migration with enforced uniqueness. Existing account lifecycle tests keep a displaced token as historical evidence while running the password-change request under the latest valid session. Full backend655/frontend125 and build pass. Independent session review runs36 existing tests and four additional failure-injection checks: failed replacement insertion rolls back revocation; new login during upload admission, person confirmation and account creation hashing prevents old-session commits. Real-HTTP isolated dual-browser validation checks the actual thirty-day cookie and old-page401 return to login. Evidence is under output/person-package-names-20261012-v1/; no real credentials or source materials are used.

Local backed-up activation verifies schema0008 and its unique session index. Two legacy sessions belonged to one account before restart. One real user successfully logs in after restart, replacing the retained legacy session; the new single session belongs to a baseline enabled account and has a valid thirty-day expiry bounded by activation time. The initial strict unchanged-session comparison is preserved in activation-initial-check.json; final activation.json distinguishes that expected login transition from data preservation. Original business/account rows,255 tasks,2 accounts and2509 encrypted/key files pass preservation checks. Both local recognition models are ready. No production account/password/recognition mutations were performed for testing, and no Mac/TLS deployment is claimed.

## Consequences

Longer unattended browser validity is explicitly requested; immediate revocation and logout remain available. This does not qualify online HTTPS/proxy deployment or permit sending credentials to logs. A browser only notices displacement on its next protected request, rather than receiving a push. Existing retained sessions may expire earlier than thirty days until the next successful login.

[API authorization boundaries](../bug-fix/2026-10-13-api-authorization-boundaries.md) extend the live transaction session check to material operations, add default route authentication and protect full health/slow responses; this note retains its remaining decisions.
