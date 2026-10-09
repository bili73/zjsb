# Agent Note: Local diagnostics that survive model reloads

Status: implemented
Scope: backend, scripts, tests, collect-diagnostics.cmd, SPEC.md, openapi.yaml, RUNTIME.md
Last-verified: 2026-10-08

## Problem

Model reloads overwrite current stderr files. Caught errors lack stack locations and the UI cannot correlate failures to a persisted record. The user needs to identify which step failed and share bounded diagnostic evidence even when the service will not start.

## Decision

Diagnostics initialize before launcher configuration and business imports. One structured JSONL writer per process instance rotates at 10 MiB across five files; startup/export enforce seven-day retention. Records associate session, request, error and optional task/run/page/region IDs. Safe exception types, bounded codes and code-frame locations exclude locals, source text and raw exception/request bodies. First failure and cleanup failure remain distinct. Unreviewed third-party stderr is drained rather than exported; parser stdout is redirected away from the private JSON protocol.

A standalone collector exports only revalidated diagnostic records and a safe runtime manifest, independently of HTTP and model dependencies. Frontend HTTP, network and render failures have safe copy/download summaries; their backend error/request IDs correlate to persisted records. Screenshots are auxiliary: no continuous desktop capture; document evidence stays in encrypted business storage outside diagnostic bundles. Logging failure prints DIAGNOSTICS_UNAVAILABLE and never prevents process cleanup.

[Bounded medical recognition](../bug-fix/2026-10-08-bounded-medical-recognition.md) adds time_limit to the bounded termination vocabulary and records actual generation_timeout_seconds/max_new_tokens. Soft normal return remains distinct from hard transport failure; private attempt records distinguish physical inference from cache reuse, without copying the original GPU timings into a reused attempt.

## Decision audit

The [runtime decision](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) owns model lifecycle and is updated only for diagnostic integration. The [durable task proposal](2026-09-30-durable-document-tasks.md) supplies task context and owns business storage. No earlier diagnostic decision exists; the DDE process and layout test notes are not superseded.

## Alternatives considered

- Plain raw stderr is convenient but may expose material and is difficult to correlate, rotate or share safely.
- Centralized ELK/telemetry provides fleet search but introduces services and external data transfer for a local tool.
- Automatic desktop screenshots show UI state but cannot identify backend stack locations and may include unrelated personal data.

## Testing

- Early startup failure, protocol corruption, model reload, timeout and cleanup failure retain distinguishable records.
- Repeated model starts do not overwrite prior logs; export works without the API.
- Injected secrets, document text and sensitive paths do not appear in exported diagnostics.
- Frontend network/HTTP/render errors have safe copyable summaries and IDs when available.
- Rotation and retention affect only new owned diagnostic files; failure to log cannot block cleanup.

CPU tests inject sensitive values and paths, protocol/cleanup failures, model reloads and rotation/retention boundaries. Real Edge downloads the unauthorized-error card; its error ID exists in the offline-exported bundle. Export after API shutdown succeeds. A deliberately invalid launch port produces an early bootstrap_failed event without starting models. Bundle checks confirm the current key, selected sample path and selected report subject name are absent. These checks do not claim arbitrary operating-system crash dumps or user screenshots are sanitized.

Evidence and limitations are linked in the [acceptance report](../../../../output/phase2-acceptance-20260930/REPORT.md); failed probes are retained separately rather than overwritten.

The [v2 bounded-recognition verification](../bug-fix/2026-10-08-bounded-medical-recognition.md) retains eight soft stops and one repetition stop despite successful alternate EOS results. Independent inspection of its six public CSV/JSON files finds no scanned sensitive reference/actual field values, material text or current API key. This explicit public-artifact check does not extend the older diagnostic-bundle claim to arbitrary screenshots or crash dumps.

## Consequences

The [independent queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) add allowlisted stop_task and numeric queue_wait_seconds without logging private images/text. The [temporary workbench](../../archived/feature/2026-10-08-temporary-recognition-workbench.md) only captures synthetic browser screenshots in acceptance; local personal originals never enter default diagnostics.

A sudden power loss cannot guarantee the final buffered event. Safe structured records omit arbitrary exception prose; error types, codes and frame locations must remain sufficient for investigation. Material screenshots require explicit controlled access and are not automatically exported.

The [HDR JPEG admission repair](../bug-fix/2026-10-08-hdr-jpeg-upload-admission.md) shares upload/worker image validation, preserves encrypted original bytes and replaces generic unsupported-image errors with actionable safe format rejection. Its actual-route browser acceptance supplements the earlier synthetic mock API checks; admission success is separate from OCR accuracy.

The former frontend portion is retired by the [frontend retirement](../../implemented/simplification/2026-10-08-retire-temporary-frontend.md); current Scope covers surviving code. Old UI checks describe historical acceptance.

The [HR field profile](2026-10-08-hr-document-field-profile.md) keeps added personal/diagnosis values in encrypted business evidence and out of safe diagnostics; anonymous native replay counts are separate from diagnostic logs.
