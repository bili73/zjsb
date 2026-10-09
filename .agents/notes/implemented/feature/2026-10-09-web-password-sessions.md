# Agent Note: Restore browser login through named password sessions

Status: implemented
Scope: backend/ocr_app/auth.py, backend/ocr_app/routes.py, backend/ocr_app/business.py, backend/ocr_app/api.py, backend/ocr_app/launcher.py, backend/migrations, backend/manage_account.py, frontend/src, tests, requirements-app.lock.txt, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user approves small-team username/password login for the centralized deployment and rejects entering a local API key after every refresh. The running Windows service remains loopback-only and Mac access is unavailable. This note implements the authorized authentication subset of the [hosted deployment proposal](../../proposed/architecture/2026-10-09-hosted-web-session-auth.md), not its unqualified Mac/network migration.

## Decision

Add an additive SQLite migration for named users, hashed opaque sessions and login throttling. Deployment operators create/change/disable accounts with a masked-password CLI; no default password, registration or browser account administration. Passwords use the pinned Argon2id library's recommended defaults, following its [official guide](https://argon2-cffi.readthedocs.io/en/stable/howto.html). Session tokens contain 256 random bits, only their SHA-256 digest is stored, and they expire absolutely after 12 hours. Logout revokes the current session; password changes and disabling revoke every session atomically. Credential verification must recheck the password hash and enabled flag inside the session-creation transaction so a simultaneous reset cannot create a valid obsolete session.

Return the identity and session-derived CSRF token from auth/me. HttpOnly, SameSite=Strict, host-only cookies restore identity after refresh; HTTPS cookies add Secure. Only the currently restricted loopback HTTP test mode may omit Secure. Unsafe session requests require the actual same origin and a constant-time checked CSRF header. Login requires same origin and bounded JSON input; five attempts per direct client address in five minutes are allowed, the next returns 429; unknown/disabled accounts share the same error and dummy verification. Do not trust forwarded identity/address headers.

Replace the browser key form with username/password, identity restoration and server logout. Tokens/passwords never enter URLs, browser storage or diagnostics. Persisted task actors use named user UUIDs. All task/review/export conditions and evidence remain unchanged.

Until a deployment-created user exists, the old local key remains available to existing CLI probes/tests; the browser no longer asks for it. Once any named account exists (even disabled), key authentication is permanently unavailable for that database, so a disabled user cannot reopen a legacy bypass. Account setup must be completed locally before switching the running workbench. This compatibility transition supports the current test harness; it is not the hosted authentication mode. The existing loopback/host boundary is not relaxed here.

## Decision audit

The implemented [administrator creation](2026-10-09-admin-account-creation.md) partially replaces CLI-only administration with admin-only listing/creation and the ten-character floor with eight, preserving sessions, CLI reset/disable and every-request authorization. Excel stays pending the business template with its separately authorized manual-opinion placeholder. The initial credential is supplied directly by the user and never recorded in repository files.

[Hosted authentication](../../proposed/architecture/2026-10-09-hosted-web-session-auth.md) remains partly proposed for Mac container/model qualification, TLS topology and secret migration. [Durable tasks](2026-09-30-durable-document-tasks.md) and [frontend rebuild](2026-10-08-frontend-rebuild-element-plus.md) retain their task/UI contracts, with the browser credential mechanism replaced. [Internal full values](2026-10-08-internal-unmasking-and-review-friction.md) retains every-request authorization. No whole decision is superseded or archived.

## Alternatives considered

- Proxy Basic Auth is small and mature; it cannot provide the requested predictable application logout/restoration and named task actors without a separate identity contract.
- JWT/OIDC is useful for distributed services; one SQLite-backed business service and two users need immediate revocation without extra token infrastructure.
- Persist an API key in localStorage: removes re-entry but leaves the rejected credential interface and makes the long-lived secret script-readable.
- Remove the key code immediately: cleaner, but breaks existing local probes before account setup. Disable it once any user is provisioned and keep it out of the browser.

## Verified invariants

Synthetic regressions check login/failure/throttle, refresh restoration, cookie attributes, expiry, logout, reset/disable revocation, legacy-bypass closure, concurrent reset protection, safe errors, origin/CSRF rejection and protected business routes. Browser refresh/logout and unchanged task/export revisions are verified separately from full backend/frontend regression and DDE verification. Actual Mac/HTTPS proxy deployment stays unqualified until tested there.

## Verification

Eight real-HTTP auth tests pass, covering sessions, Cookie attributes, origin/CSRF, throttling, expiry, reset/disable revocation, concurrent reset and legacy-key closure. A HTTPS request checks Secure; a reloaded Accounts instance checks persisted sessions and viewer permissions. Login plus manual review/export keeps original recognition evidence and named actor history. Full backend regression passes 447 tests; frontend passes 61 tests and typecheck/build. Independent [owned browser acceptance](../../../../output/repairs-20261009-v1/browser-4/summary.json) verifies seven login/restoration/logout/medical-link/export behaviors with no browser errors, real model calls or production writes. The build remains in output/repairs-20261009-v1/auth-dist, separate from the running frontend; no production password is provisioned.

## Consequences

First-account creation uses the user's explicitly supplied password through hidden local input; do not invent or commit one. The later administrator decision qualifies actual HRSSC provisioning and version1.15.0 activation; the earlier447-test/isolated-build measurement above remains historical. Production HTTP/tunnel exposure is not enabled by this change. Account/session data persist in SQLite but Windows encryption key portability remains the separate migration proposal. A long open workbench still requires login again after absolute expiration; accepted server tasks continue independently.
