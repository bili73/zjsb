# Agent Note: Guard every business route and revalidate authorization at operation boundaries

Status: implemented
Scope: backend/ocr_app/auth.py, backend/ocr_app/routes.py, backend/ocr_app/api.py, backend/ocr_app/task_store.py, backend/ocr_app/preview.py, backend/ocr_app/exporting.py, backend/ocr_app/region_ocr.py, frontend/src/App.vue, frontend/src/engine.ts, frontend/tests, tests, scripts, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-13

## Problem

The user approves server-side authorization for every business endpoint without a frontend routing rewrite. All thirty existing business method/path pairs already check a principal, with role and ownership checks downstream. However, cancelling a synthetic queued task after revoking its session between route dependency evaluation and the store transaction returns202 and changes the task to CANCELLED. Review and rerun share this stale-principal boundary. Export/preview processing also needs fresh checks before emitting full content. Both health paths currently expose engine and queue details anonymously.

## Decision

Business endpoints inherit a protected APIRouter default principal dependency, separate from the explicitly public login route. Keep administrator/operator/viewer and immutable batch ownership semantics. Reuse the existing session/legacy-key mechanism through one request authentication function; optional database connections let transaction callbacks read live session and role from the same BEGIN IMMEDIATE transaction. Only trusted non-HTTP callers may omit authorization callbacks. Before protected writes, reject invalid sessions, changed identities or roles and unauthorized ownership; maintain existing version checks. Do not hold write locks during OCR, workbook construction or process waits. Recheck authorization before returning slow full-content responses. Already-delivered bytes cannot be recalled, and an operation committed before later revocation remains committed.

The approved public exception is GET /health returning only status, alongside login and static frontend/help assets. GET /api/v1/health returns the existing full health schema only to authenticated users. With no business service there is no authenticated health access. Update the frontend engine client to use the minimal probe while signed out and the protected snapshot while signed in, resetting and fencing requests across session changes. Existing CPU OCR and per-model queues are unchanged. Local benchmark launchers must authenticate before waiting on the protected health snapshot; they must not silently wait for now-redacted runtime data. Legacy keys remain accepted only before any named account has ever been configured in that database.

## Decision audit

- [Password sessions](../../implemented/feature/2026-10-09-web-password-sessions.md) and [single-session policy](../../implemented/feature/2026-10-12-thirty-day-single-session.md): partial overlap; retain credential, expiry, CSRF and revocation rules and extend the operation boundary.
- [Account-owned batches](../../implemented/feature/2026-10-10-account-owned-batches.md): partial overlap; preserve role/ownership and foreign404 semantics, including all-or-nothing exports.
- [Settings transaction repair](../../implemented/bug-fix/2026-10-12-review-repairs.md): partial overlap; apply its live transaction check to remaining material operations rather than replace its UI fixes.
- [Source-region copying](../../implemented/feature/2026-10-13-source-region-ocr-copy.md): partial overlap; retain OCR response/version fences and use the common transaction authentication helper.
- Proposed hosted authentication/Mac work remains unqualified and is not absorbed. Rejected clinical/localization records do not govern authorization. No note is wholly superseded or archived.

## Alternatives considered

- Rely on hidden tabs or frontend route guards: useful for navigation, but a direct HTTP client bypasses them. Enforce server-side login, role and object access on every route.
- Keep only per-endpoint principal declarations: explicit and already present, but a newly added route can accidentally omit them. Add a router-level default and a route/role regression matrix.
- Check sessions only when a request arrives: conventional and inexpensive for short reads, but the reproduced revoked request can still mutate state. Recheck inside each protected write transaction and after slow response preparation.
- Require login for every asset and health check: hides service metadata, but prevents initial login-page loading and operational liveness probes. Keep status-only health and static assets public; protect full engine information.
- Introduce JWT or an authorization framework: supports distributed services, but duplicates the current small SQLite session service and complicates immediate revocation. Reuse its live database checks without schema changes.

## Verification

All31 protected method/path pairs have an explicit regression inventory. Tests cover absent/expired/disabled/revoked/superseded sessions, forged identity/role headers, Cookie-write CSRF and foreign origins, administrator/viewer restrictions, and a newly injected business endpoint without an endpoint dependency. Existing foreign-object404, mixed-export atomicity and region-OCR version/revocation tests remain passing. Deterministic races reject cancelled sessions before review/cancel/rerun/preview/reveal/export transactions without business-state changes; preview pixels, workbook construction and classification also reject revocation after slow preparation. Demotion cannot retain captured administrator ownership.

The final full backend suite passes687 tests; frontend145 tests and typecheck/build pass. An isolated real Edge/API probe passes3 login/private-health/logout scenarios without real vision inference. Earlier expected failures and the first full regression's two obsolete health/viewer expectations remain recorded separately. These checks do not measure OCR accuracy or qualify remote deployments.

An idle integrity-checked backup precedes an owned-tree restart. All business-table fingerprints,262 tasks,2 accounts and2,611 material/key files match before/after;13 served static files match the build. Public health has only status; anonymous private health and region OCR return401. Current-launch successful load/warmup diagnostics plus still-live owned model processes confirm both models ready without creating a production session or changing credentials. Full authenticated health is exercised in the isolated API/browser tests, not by bypassing production login. Details: [verification report](../../../../output/api-authorization-20261013/REPORT.md).

## Risks

Revocation does not undo committed operations or already-sent content. Internal worker APIs deliberately have no browser session and retain trusted-call defaults; HTTP must always supply verified identity and authorization callbacks. The network remains loopback/host restricted; this change does not qualify Mac, proxy headers, tunnels or TLS deployment. Preserve prior changes, samples, outputs and failed measurements. No real OCR benchmark or production account/material edits are part of this verification.

## Consequences

Each protected write adds a live session read on its existing connection; slow exports/previews/classification add one check after preparation. No write lock spans image encoding, OCR, workbook construction or process waiting. Revocation is effective at the next protected boundary, not retroactive. The login screen exposes connectivity only; engine details require login. Existing standalone launch probes authenticate before waiting on full runtime health and report401 as AUTH_FAILED rather than a false startup timeout. No schema, model queues or browser-routing framework is added.
