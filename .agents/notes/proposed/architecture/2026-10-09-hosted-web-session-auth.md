# Agent Note: Replace the local API-key gate with small-team web sessions

Status: proposed
Scope: backend/ocr_app, backend/model_worker.py, frontend/src, tests, SPEC.md, openapi.yaml, ARCHITECTURE.md, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-09

## Problem

The user requests a new deployment direction: move the whole application to the M3 Ultra / 96 GB Mac Studio using Docker, with only one or two accounts, and asks whether login is necessary. The current workbench requires a local Windows user's API key on every page reload. KeyGate creates a BusinessApi containing the key; App stores both identity and client only in memory and does not restore a session. This is verified current code, not a conventional username/password login.

Central hosting does not remove the browser-to-backend HTTP API. The user-approved simplification removes user-facing API keys and an independently exposed model API, while retaining the application's existing upload, review, preview and export interfaces. Its Windows password-session subset is implemented separately; the complete Mac deployment remains proposed.

Docker packaging is a separate issue. The current launcher imports msvcrt and calls Windows APIs; storage protects its key with DPAPI; workers use Windows Job supervision and Windows virtualenv paths; model_worker.py explicitly requires CUDA. Ordinary Mac Linux containers cannot run this existing CUDA path on the Apple GPU. Docker Model Runner is a possible integration path, but its macOS inference engines run outside containers and exact OCR model support must be qualified.

## Proposal

Use a single shared HR workbench with one or two named accounts. Keep username/password login and server-side sessions. Create or reset accounts through a deployment command; omit public registration, email recovery and a user-management application. Preserve the existing operator/admin authorization checks and review/export actor identity. Shared task visibility is a proposed small-team assumption; it is not a promise of per-user isolated records.

Hash passwords using Argon2id and persist accounts and session verifiers in SQLite through an explicit migration. Issue cryptographically random opaque sessions, storing a one-way verifier rather than a reusable session secret in the database. Use an HttpOnly, Secure, SameSite cookie over same-origin HTTPS. Protect state-changing requests with CSRF tokens and validate the configured origin. Enforce bounded login attempts, server-side expiration and explicit logout revocation. Password reset or disabling an account revokes its sessions. Neither passwords nor session credentials enter diagnostics, URLs or frontend persistent storage.

The suggested user experience is a normal username/password form, a session lasting up to one working day (proposed absolute maximum 12 hours), automatic identity restoration on refresh, and a real logout. A valid session is restored after reopening the page within its lifetime. Expiration returns the user to login without cancelling already submitted tasks. Existing task run/revision protection, evidence, review rules and required-value export remain unchanged.

Keep the frontend build and business backend together in a Linux ARM64 container on the Mac, with SQLite/artifacts on a persistent volume and an HTTPS entry point. Use a native macOS model service as the initial Apple-GPU candidate, retaining independent model queues, generation budgets and confirmed cancellation. Container-to-host inference is private, reachable only by the business service through an explicitly restricted host route and service credential; do not publicly expose model ports. Docker Model Runner can be assessed as an alternative manager after the exact models and stopping behavior pass. No Apple inference engine or performance claim is approved merely by choosing Docker.

The [GLM Apple Silicon guide](https://github.com/zai-org/GLM-OCR/blob/main/examples/mlx-deploy/README.md) describes native MLX-VLM over Metal. The [Paddle Apple Silicon guide](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL-Apple-Silicon.en.md) provides another native deployment candidate. Pin versions/precision and qualify the existing samples on the actual machine before switching production. Docker's [GPU documentation](https://docs.docker.com/desktop/features/gpu/) distinguishes container GPU passthrough from Model Runner, and [Model Runner documentation](https://docs.docker.com/ai/model-runner/) explicitly states that macOS engines run outside containers. [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) and [password guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) support the proposed credential/session design.

## Assumptions and implementation order

The authorized Windows browser-authentication subset is implemented and qualified separately in [password sessions](../../implemented/feature/2026-10-09-web-password-sessions.md); this architecture proposal remains proposed for Mac, proxy and secret-migration qualification.

The user approves the login direction on 2026-10-09 and raises three recognition/export problems. The implemented [medical continuation](../../implemented/bug-fix/2026-10-09-native-medical-table-continuation.md), [business Excel](../../implemented/feature/2026-10-09-business-xlsx-layout.md) and [diploma mapping](../../implemented/bug-fix/2026-10-09-diploma-school-and-date-mapping.md) retain their separate investigation and acceptance boundaries. These Windows changes do not qualify Mac inference or remote access.

1. One business backend and at most two accounts share the same HR task workspace; independent authorization remains on every business request.
2. Users access the browser over HTTPS. The actual private-network or tunnel route, host name and trusted proxy are still undecided. Arbitrary forwarded headers cannot establish identity or client address.
3. Authentication can first be implemented and tested on Windows independently of Mac migration. Update auth.py/routes.py and the account/session migration, then replace KeyGate and in-memory key handling with a login form, session restoration and logout. Update OpenAPI, frontend DTOs and errors together.
4. Qualify the native Mac model services before adapting launcher/process supervision, host access and secret storage. Containerization must replace loopback-only middleware with a deliberate network boundary, not just remove host checks. Existing encrypted Windows data requires deliberate key migration; copying a DPAPI file is insufficient. No deletion or automatic migration of existing tasks is authorized by this proposal.
5. Authentication acceptance uses synthetic data and real HTTP/browser tests; Mac performance acceptance uses labelled serial runs with recorded model/backend revisions and separate startup timing. Do not infer Mac performance from Windows startup or RAM size.

## Decision audit

The [Mac migration proposal](2026-10-08-mac-studio-inference-service.md) partially overlaps: its qualification and platform-adaptation gates remain, while this proposal makes centralized deployment concrete. [Password sessions](../../implemented/feature/2026-10-09-web-password-sessions.md) replace only the Windows browser credential subset of the [durable-task decision](../../implemented/feature/2026-09-30-durable-document-tasks.md) and [frontend decision](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md). The [internal full-value decision](../../implemented/feature/2026-10-08-internal-unmasking-and-review-friction.md) remains active; full values stay behind authenticated business access. These notes are partly overlapping, none is wholly superseded and no archival is appropriate. Relevant proposed/implemented/rejected records were searched before writing; no existing rejected record owns this session-auth choice.

## Alternatives considered

- No login eliminates all credential interaction and is simplest on a sole-user loopback app. Shared browser access to full identity/bank/medical records and review edits needs an access boundary and identifiable actors, so it is not the recommended hosted mode.
- Reverse-proxy Basic Auth is mature and needs very little application code. It provides less predictable logout/session UX and still requires a trusted identity contract for existing review actors; the application session is the better fit for the requested daily workbench.
- JWT/OIDC or a separate identity platform provides reusable identity and distributed validation. One backend and two deployment-created accounts do not need these additional token or service lifecycles; SQLite sessions are smaller and immediately revocable.
- Keeping API keys preserves the existing client and tests. It retains the exact manual-key/reload friction the user is rejecting.
- A single ordinary container containing models and business services is operationally appealing. Current Windows/CUDA code and Mac GPU access do not qualify that topology. Prefer containerized business services with qualified native inference; assess Model Runner separately instead of claiming arbitrary OCR models work in it.

## Acceptance criteria

- Login, refresh/reopen restoration, logout, password change/disable revocation, expiration and failed-login throttling pass real HTTP/browser tests. Protected results, previews, review and export reject absent/expired/revoked sessions; CSRF and untrusted origins/proxy headers are rejected.
- Original task records, revision behavior, current medical review scope and export eligibility remain unchanged. Named actors are retained without logging credentials. No default or committed password exists.
- A persistent container restart preserves accounts/tasks and respects session expiration/revocation. HTTPS cookie behavior and host allowlists pass tests in the actual proxy topology.
- On the actual Mac, both pinned model backends, region outputs, queue independence, soft generation stop and confirmed hard cancellation are verified before the shared deployment is called ready. CPU-only execution is not reported as Apple GPU acceleration.
- The encrypted Windows originals remain recoverable; secret migration and persistent-volume backup/recovery are explicitly tested before moving historical data.

## Risks

The Mac remains inaccessible in this session. Network exposure, exact macOS version, model/backend compatibility and production throughput are unverified. A shared account would weaken actor attribution, so two named accounts are preferable when two people operate the workbench. Account count does not make cookies or every-request authorization optional. The user has approved and the Windows subset has implemented login, while actual network/proxy details and Mac qualification remain unresolved. The current running Windows service stays intact until local account provisioning and controlled restart; this complete hosted-deployment proposal stays proposed.
