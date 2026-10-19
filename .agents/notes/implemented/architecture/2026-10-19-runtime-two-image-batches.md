# Agent Note: Dispatch bounded two-image batches with independent row ownership

Status: implemented
Scope: backend, tests, scripts, AGENTS.md, CLAUDE.md, ARCHITECTURE.md, RUNTIME.md, IMPLEMENTATION_PLAN.md, openapi.yaml, README.md, CHANGELOG.md, SPEC.md, FRONTEND_FIELDS.md, frontend/package.json, frontend/package-lock.json, frontend/src/presentation.ts, frontend/public/help
Last-verified: 2026-10-19

## Problem

The user approves Windows runtime batching after the isolated CUDA and Paddle image-isolation qualifications, starting at two images and retaining responsive pages. A model consumer currently dispatches one image, document lanes admit one file, and cancellation kills the current model process. Merely raising document concurrency neither creates true batches nor protects unrelated users sharing an inference call. The Mac online service must receive no write, restart or inference experiment.

## Decision

Expose an internal batch-size limit of1 or2, default1 for direct/benchmark RuntimeConfig callers and2 for the qualified Windows launcher. Successful dual startup enables at most three short single-page documents per existing lane and at most two compatible requests per model call. Three slots allow one executing image plus an already waiting pair; two document slots usually leave only one waiter and cannot sustain batching without an artificial gather delay. This implementation detail is explained to the user before activation. Startup-degraded and standalone serial benchmarks retain one slot and their original single-image path. A consumer drains only currently queued adjacent requests with the same recognition task and token ceiling, preserving FIFO without a collection sleep or skipping an incompatible head. Claiming each document still commits the persisted account-ring cursor.

The initial real workload invalidates the assumption that long documents can share the same three-slot admission: two long medical PDFs, each complete serially, accumulate six incomplete regions when admitted together within the unchanged180-second active budgets. The user explicitly approves narrowing this iteration to short materials. Medical reports, multi-page documents and unknown original page counts therefore run alone within their lane. When a short file is active, the next fair candidate must be a validated single-page non-medical file to claim another slot; otherwise leave it QUEUED and leave the account cursor unchanged. Do not skip it in favor of a later account or begin its active budget before it can run. Once a long file is claimed, do not claim another file in that lane until it stops. Other model lanes remain independent. Report-internal region batching is deferred; the failed medical trial is preserved rather than relabeled as successful.

Use private JSON-lines batch RPC with opaque unique row IDs, per-row task/run/context, cancellation and absolute deadlines. A worker input thread receives cancellation while generation runs; stopping criteria end only the selected row and stream its completed result before the remaining row finishes. Validate result identity/count/duplicates before publication, and keep existing task/run/revision fences and partial-result storage. A normal row cancellation does not unload the shared process. Failed cancellation confirmation or a truly dead/stuck shared process causes an explicit shared failure and verified process cleanup, never a fabricated peer success. Retain existing no-hidden-OCR-retry and no-concurrent-reload policy; OOM remains failed evidence rather than silently replaying a batch.

The control reader starts only after a successful synchronous model load/warmup. The first real probe stalls at NumPy extension import before any inference; a CPU reproduction confirms that starting a blocked stdin reader first triggers it in the installed Windows environment, including a duplicated input stream. The exact native lock is not established. An actual-worker CPU regression fails before deferring the reader and passes afterwards. Keep that startup failure and stack evidence separate from throughput measurements; no model environment or weight changes are used to work around it.

Keep API parsing, SQLite durability, required fields, human drafts and image loading outside model execution locks. No HTTP schema, public batching control, new model, dependency, database migration, Mac modification or Git push is part of runtime batching. Update the visible application version and annotate recent existing commits with retroactive tags/change notes at the user's request; do not rewrite historical commits or tag uncommitted features as released.

## Related decision audit

- [Independent model queues](2026-10-08-independent-model-queues.md) and [account-fair claiming](2026-10-16-account-fair-document-queue.md) partially overlap: replace their one-file/one-image ownership limit only in qualified Windows batch mode. Per-model exclusive execution, fairness, fallback queues and run fences remain.
- [Windows qualification](../testing/2026-10-19-windows-model-batching.md) and [Paddle isolation](../bug-fix/2026-10-19-paddle-packed-image-isolation.md) provide experimental evidence, not runtime acceptance. Keep original failures and serial accuracy protocol.
- [Bounded HTTP writes](../bug-fix/2026-10-16-bounded-http-writes.md), [detail loading](../bug-fix/2026-10-19-prioritized-detail-loading.md) and [API authorization](../bug-fix/2026-10-13-api-authorization-boundaries.md) retain their boundaries and tests.
- Scope/topic queries include proposed and rejected records. Mac/auth proposals and rejected extraction/UI choices do not own this dispatch change. No decision is wholly superseded or archived.

## Alternatives considered

- Multiple same-model processes offer simple request ownership but duplicate weights and compete for the same GPU; keep one model owner and batch its inputs.
- A fixed collection wait can fill more batches, but delays the first request and contradicts the user's loading priority. Dispatch immediately and batch only an existing backlog.
- Two document slots minimize CPU preparation but permit at most one waiting image behind a busy singleton. Use the minimum third slot needed for a queued pair; keep per-call size2 and measure HTTP/disk contention.
- Killing the model on every cancellation preserves the old single-owner cleanup rule, but interrupts an unrelated batched row. Add targeted worker controls and require confirmation.
- Returning all results only at batch end simplifies RPC, but makes a short row wait for a long peer and blocks its next CPU stage. Stream row completion with identity checks.
- Continuous batching can admit a new row at each decoding step but needs different cache ownership/backends and much broader qualification. Start with static two-row microbatches.

## Testing

CPU regressions exercise immediate singleton dispatch, compatible FIFO pairs, incompatible ordering, bounded document slots, account fairness, queued/active cancellation, per-row deadlines, early completion, malformed/duplicate results, shared failure cleanup, shutdown and old-run rejection.54 focused tests pass, including red/green admission regressions for a blocked fair head, unchanged cursor and unstarted budget. Tests do not import Torch into the application environment; exact generation tests run separately in the Paddle environment.

Final backend discovery runs957 tests in410.388s:950 pass,7 Torch-dependent tests skip in the isolated application environment. Those7 generation/attention tests pass separately in the Paddle environment. All254 frontend tests, typecheck/build,8 DDE-tool tests, notes/index verification and diff whitespace checks pass. The earlier full run's outdated mock-namespace error and red admission tests remain in the validation artifacts.

The fresh short-only comparison in output/runtime-batches-20261019-120747 passes:9 certificates31.312→17.281s,6 forms/tables23.437→11.687s,6 mixed files14.891→9.031s,21/21 field and normalized OCR agreement. Both models perform actual two-row calls; active cancellation leaves the peer complete and both model PIDs unchanged. HTTP5xx is zero and all predeclared loading P95 limits pass, although diploma preview P95 increases442.701→576.228ms. This is one synthetic concurrency comparison, not business accuracy or sustained capacity.

Final admission qualification in output/runtime-batches-20261019-121234 passes against the retained full single-image baseline: all23 field sets agree,7 actual double-row calls and one cross-model overlap are observed. Two real long medical PDFs run serially in246.875s, both with zero incomplete regions; the second recorded active start follows the first terminal update. Their89/87 parsed item rows agree on16 semantic attributes including values, reference ranges, abnormal flags, risk grades and diagnosis; exclude run-specific IDs/source references from that comparison. Their normalized raw attempt hashes may differ due timed partial generations; do not claim OCR text identity or medical accuracy. Cancel/ownership/loading checks also pass. Reports and plotting CSV are preserved, together with startup failure and the rejected six-incomplete-region medical trial. Restoration verifies all15 original database tables and3801 existing material/key/static hashes; the Windows service starts dual-resident with batch-size2. No Mac operation is performed.

## Consequences

Padding, output length imbalance and contention between resident models can reduce throughput or raise first-response latency. Three slots per lane bound but do not remove CPU/disk contention or model wait within the existing180-second active budget. GPU forward passes cannot be interrupted until a generation boundary; shared-process hard failure can affect both rows and must remain visible. Windows CUDA results do not qualify Mac MLX.
