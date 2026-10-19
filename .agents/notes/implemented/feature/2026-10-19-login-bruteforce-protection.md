# Agent Note: Bound account and source login attempts before password verification

Status: implemented
Scope: backend/ocr_app, frontend/src/components/LoginGate.vue, frontend/src/diagnostics.ts, frontend/tests, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-19

## Problem

Existing throttling allows five attempts per direct peer in five minutes and clears that peer's counter on any successful login. It cannot protect an account against rotating sources, and a shared office/proxy peer makes the five-attempt allowance unsuitable for a team. The user approves account and source limits and bounded password-verification concurrency on 2026-10-19, for both Windows main and the isolated Mac branch.

## Decision

Reuse login_attempts with domain-separated hashed account/source keys. Atomically reserve attempts before Argon2: five attempts per normalized username per 300-second window, sixty per direct peer per 300-second window. A successful login clears only the matching account window, never the source allowance or a newer account window. Denials do not extend the window. Counters persist across Accounts/service recreation. Unknown/disabled accounts share the same outward credential error and throttling behavior. Expired counters are reclaimed and old peer-only counters are retained conservatively during their active window.

At most two login verifications run concurrently in the application process; excess requests fail promptly with 429 and Retry-After: 1, without taking a DB connection or starting expensive hashing. Account/source throttling returns the remaining window via Retry-After. Do not trust X-Forwarded-* or change the thirty-day single-session contract. Avoid repeated throttled-request audit/ERROR writes; preserve one failed-login limit event per blocked counter window and ordinary admitted login failures. The browser displays a countdown and does not automatically submit credentials.

## Decision audit

The [password-session decision](../../implemented/feature/2026-10-09-web-password-sessions.md) partially overlaps: retain Argon2, same-origin/CSRF and revocation behavior, replace peer-only throttling. [Thirty-day single session](../../implemented/feature/2026-10-12-thirty-day-single-session.md) remains unchanged. [Bounded HTTP writes](../../implemented/bug-fix/2026-10-16-bounded-http-writes.md) supplies the prompt rejection and short transaction constraints, not a password-processing queue. The hosted-auth proposal remains a separate deployment/HTTPS decision; no rejected note owns this change.

## Alternatives considered

- Keep only peer throttling: already persisted and simple, but rotating sources bypass account protection and shared peers penalize unrelated users.
- Permanent account lock or CAPTCHA: stronger escalation options, but add recovery or external dependencies; use expiring limits first and retain existing active sessions.
- Sleep or queue all password attempts: superficially slows guessing, but occupies workers and can make the rest of the application unresponsive; reject excess verification promptly.

## Verification

Nine synthetic backend tests cover exact thresholds, cross-source account protection, shared-source aggregate protection, no successful-login source reset, persistent windows, expiry, normalized/unknown users, forged forwarding headers, two-verification cap, slot release, retry headers, bounded audit volume and old/new-window races. Twelve parallel reservations admit exactly five. A HTTP test holds two password checks and verifies a third receives429/Retry-After:1 while a logged-in batch read still succeeds within a two-second test bound; this is a functional isolation check, not production capacity certification. Frontend tests verify countdown, password clearing and no automatic submission. Windows full backend regression runs973 tests (966 passed,7 skipped); final focused36 tests and262 frontend tests pass. No production account, container or model service is used.

## Consequences

Account throttling can temporarily deny a targeted legitimate user, and NAT/proxy peer throttling is shared. Windows expire automatically rather than permanently disabling users; the source allowance is deliberately larger for the small team. This is application login protection, not volumetric DDoS protection or a substitute for HTTPS.
