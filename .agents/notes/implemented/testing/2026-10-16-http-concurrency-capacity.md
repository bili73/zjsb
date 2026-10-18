# Agent Note: Isolated Windows HTTP concurrency measurement

Status: implemented
Scope: scripts/probe_http_load.py
Last-verified: 2026-10-16

## Problem

The expected audience is about 20 concurrent users; the user requests a 50-user stress test on an independent Windows instance. Real model concurrency is bounded by independent model queues, so HTTP throughput cannot establish OCR throughput. Current uncommitted pagination and audit changes must be included without modifying the live deployment or its records.

## Decision

Freeze backend source and migrations into a unique ignored output directory. Start one loopback Uvicorn process with real authentication, encrypted storage, SQLite, diagnostics and audit, but a runtime stub that never claims queued work or loads models. Seed synthetic accounts and completed materials; use real HTTP requests for login, polling, upload, review and XLSX export. Measure paced 20/50-user polling and synchronized 20/50-user write/export bursts separately from a closed-loop saturation test. Keep per-request timings, resource samples, source hashes, unsuccessful attempts and integrity checks. Use independent accounts; sequential setup login avoids conflating the shared-IP login security throttle with business capacity.

## Decision audit

The [independent model queues](../../implemented/architecture/2026-10-08-independent-model-queues.md), [operation audit](../../implemented/feature/2026-10-16-account-operation-audit.md) and its [account-action simplification](../../implemented/simplification/2026-10-16-account-action-audit.md) provide runtime context; their decisions remain authoritative and have no overlapping ownership of this HTTP tooling. The scripts scope and pressure/load topic queries found no existing HTTP capacity owner or competing proposed/rejected measurement. This note owns only HTTP measurement tooling and makes no accuracy, Mac, GPU throughput or long-duration stability claim. Existing scripts/probe_concurrent_pipeline.py measures real model execution and is not reused for HTTP load.

## Alternatives considered

- Stress the live instance: most representative of deployment state, but creates synthetic records and competes with actual recognition. Use the explicitly selected independent instance.
- Use the in-process ASGI test client: quick and deterministic, but omits TCP, independent process scheduling and production thread-pool behavior. Use a real loopback HTTP server.
- Load actual OCR models in the second instance: covers end-to-end completion, but duplicates GPU weights and interferes with the running production model owners. Keep OCR throughput outside this run.
- Only hit /health: easy to automate, but cannot reveal encrypted write/audit/export contention. Exercise authenticated business routes.

## Testing

The complete Windows run is retained at [REPORT.md](../../../../output/http-load-20261016-150126-557610/REPORT.md), with source snapshots, source hashes, raw requests, resources, diagnostics, database and validation. Base commit is 2a358cd839f3492fa80c15bef807496cb182ba4d plus captured uncommitted changes; no frozen backend file differs from the workspace at verification. No application behavior is changed by this probe.

The fixture contains 50 operators plus one administrator, 500 batches and 1000 completed tasks. Each seeded batch has two different images: identical images are correctly deduplicated by upload admission. Sequential HTTP login precedes measured load. Polling has four sequential reads per two-second user cycle, with staggered starts; 20/50-user phases each run approximately 60 seconds, and a separate 50-user unpaced closed-loop phase runs approximately 30 seconds. Upload and save have three synchronized rounds per concurrency; two-row XLSX export has two. Resource samples include the Windows venv launcher descendants, not only its lightweight parent process.

Across 14409 recorded requests, 20-user scenarios have no unexpected failures. At 50-user burst load, 4/150 uploads and 23/100 exports return HTTP 500; all 27 diagnostics identify SQLite code 5 (busy) at BEGIN IMMEDIATE. This is a completed measurement with a failed 50-user write/export acceptance result, not a passing capacity certification. Upload/save/export P95 at 20 users is 2234/1978/5383 ms; at 50 users it is 6052/4439/12175 ms. Paced 20/50-user reads have P95 305/150 ms and no failures; the differing order/cache/host conditions do not establish that higher concurrency is faster. The unpaced read phase reaches 167 requests/s with P95 624 ms and no errors, which is observed closed-loop throughput, not a fixed-arrival-rate limit.

All 207 acknowledged uploads retain unique identities, ownership and QUEUED state. All 50 review targets retain the expected final revision/value; 50 submissions of one version yield exactly one success and 49 conflicts. SQLite integrity and foreign keys pass. All 1661 encrypted blobs decrypt; none are missing, unreferenced or corrupt. Failed upload/export audit outcomes remain failures, and only 118 successful exports have export_generated success events. The test process exits normally and its port closes; original service public health remains ok, without implying production model readiness.

Two earlier smoke attempts remain separate: http-load-20261016-145734-213989 failed because the probe login URL omitted /api/v1; http-load-20261016-145903-108114 failed because duplicate fixture images produced one task instead of two. Both are corrected harness assumptions and excluded from capacity statistics. Python compile, DDE and whitespace checks accompany delivery; full application regressions are not rerun for this probe-only change.

## Consequences

Loopback omits LAN/browser rendering cost. Synthetic small documents omit large medical/table payloads. Runtime stubbing omits inference and its database writes. The generator shares the host with the server and live deployment; resource measurements and provenance must accompany results. Short runs do not establish long-term capacity.

The observed busy failures justify the separate [bounded HTTP write refinement](../bug-fix/2026-10-16-bounded-http-writes.md). At baseline, upload and export access-history call fsync-backed Storage.put while holding a write transaction. The refinement moves those preparations outside writer locks, preserves five-second busy_timeout, and adds bounded asynchronous admission. Retain the baseline as failed evidence rather than replacing its results with later passing runs.

## Follow-up measurement protocol

The [comparison report](../../../../output/backpressure-20261016/REPORT.md) retains two further full runs and two focused connection investigations. They eliminate SQLite busy/500 failures but expose idle TCP reuse races. Numeric-only optional connection tracing matches failed request ports to the server's five-second idle close, with no ASGI arrival. The probe defaults to a four-second client idle expiry, records both limits, and supports --client-keepalive 5 --trace-connections to investigate the original condition. The request timeout remains thirty seconds and writes are never automatically replayed. Final full protocol http-load-20261016-160052-837652 has 14,315 requests and no unexpected failures; fifty-user upload/review/export succeeds 150/150, 150/150 and 100/100. This protocol adjustment is explicit and does not certify every browser/proxy's connection behavior.

Acceptance now checks background/preflight requests as well as named phases; one historical focused outcome incorrectly omitted a failed health read, so final-verification.json records failure without changing its original outcome.json. Shutdown verification also decrypts all artifact references and compares missing/orphaned files. Request headers carry safe numeric queue/DB wait/DB hold/file-write timing; overload rejection remains separate from success. Focused --writes-only runs omit sustained reading and are not substitutes for the full protocol. Connection instrumentation uses probe-process-only hooks and never modifies installed libraries or production code.
