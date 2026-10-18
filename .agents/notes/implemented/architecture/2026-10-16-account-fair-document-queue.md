# Agent Note: Rotate document lanes fairly between uploading accounts

Status: implemented
Scope: backend/ocr_app/task_store.py, backend/ocr_app/task_scheduler.py, backend/migrations, tests, frontend/src, frontend/tests, frontend/public/help, openapi.yaml, SPEC.md, ARCHITECTURE.md, RUNTIME.md, FRONTEND_FIELDS.md
Last-verified: 2026-10-16

## Problem

Global document FIFO lets an account with a large batch block other accounts using the same model lane. Reruns retain the original task creation date and can also jump ahead of newer work. HTTP backpressure does not change inference scheduling or improve this fairness.

## Decision

Keep one active document per lane and one in-flight request per model. At each document boundary select the next waiting account on a stable ring of immutable batch owner IDs, using a persisted cursor per lane. An empty cursor starts at the account with the oldest queued task; subsequent claims advance through the sorted owner ring, wrapping when needed. Accounts without eligible queued tasks are skipped. Historical NULL owners share one separate legacy bucket; deleted accounts retain their original batch owner identity. This promises account turns, not global arrival order between accounts or equal processing time per account. With only A and B waiting, A's current document is followed by B regardless of A's backlog. The cursor update and exact task claim commit together.

Each task has a durable enqueue sequence and a nullable queued_at timestamp. New and appended files receive sequences in accepted input order; reruns receive a new sequence at the tail; duplicate reuse retains its existing position. Migration preserves existing task/result/blob content and deterministically seeds legacy order from the last QUEUED update or original creation time, but leaves unknown queued_at NULL instead of pretending the inferred time was observed. Sequences order currently retained tasks, not a permanent audit counter: assigning max(existing)+1 within the writer transaction also works after deletion. A committed claim consumes a turn even if its worker subsequently fails. No in-flight file is preempted. The two production lanes have independent cursors; the serial fallback has its own cursor. Model request FIFO, fallback and cancellation fences, and the existing 180-second active budget remain unchanged.

The task API adds queued_at and active_started_at. The UI explains account rotation and displays these observed timestamps, without exposing other accounts or inventing queue positions/ETAs. No new queue limits, inference replicas, batch inference, model changes, or production restart/deployment are included.

## Related decision audit

- [Independent model queues](../../implemented/architecture/2026-10-08-independent-model-queues.md): partial supersession of document FIFO only; model queues and execution ownership remain valid. Both notes link to this boundary.
- [Durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md): overlap in enqueue/recovery; retained and cross-linked.
- [Account-owned batches](../../implemented/feature/2026-10-10-account-owned-batches.md): reuse immutable ownership and existing visibility rules.
- [HTTP backpressure](../../implemented/bug-fix/2026-10-16-bounded-http-writes.md): complementary, retain short SQLite transactions and do not claim OCR throughput from HTTP tests.
- Topic/scope queries found no existing fairness proposal; unrelated medical/OCR proposals and rejected extraction decisions remain untouched.

## Alternatives considered

- Global FIFO is simplest and preserves submission order, but lets a single account monopolize a lane.
- Batch rotation requires little account state, but splitting an upload into many batches multiplies that account's turns.
- Least-recently-served account counters preserve intuitive historic service order, but new accounts with no service history always overtake previously served waiting accounts and require a row per account/lane. A stable ring needs only one cursor per lane and naturally skips absent owners.
- More workers or removing model locks appears to allow overlap, but inference remains serialized and claimed tasks would spend their active deadline waiting. Real batching needs separate Mac qualification and cancellation ownership changes.
- Page-level preemption can reduce long-report blocking, but requires resumable processing and a different budget contract; defer it.

## Testing

A100/B1, three-account rounds, split batches, input order despite tied/backward timestamps, reruns, append/deduplication, cancellation, deletion, legacy owners, independent lanes and reopened database recovery pass in 16 new isolated SQLite tests. Concurrent claims cannot claim one task twice or lose cursor updates, and a failed commit rolls back both claim and cursor. An actual TaskScheduler with synthetic child processes rotates to the new account without interrupting the other lane; tests also assert explicit certificate/medical/all scope propagation. Migration interruption rolls back; successful legacy migration preserves existing encrypted values, respects the saved rerun ordering hint, leaves unknown queued_at NULL and is restart-safe.

The final targeted backend suite passes 182 tests (187.368 seconds): fairness, scheduler/store/model queues, migrations, account ownership, packages, authorization, HTTP backpressure, deletion, mixed upload, web sessions and audit. All 246 frontend tests and typecheck/build pass, including nullable/missing scheduling timestamps, UTC+8 rendering and honest waiting explanation. The first broader run exposed an old migration test comparing all columns after an additive migration; it now compares the captured original columns and retains data preservation checks. Independent read-only code review found no blocking defect; its two suggested integration/migration coverage gaps have tests. Fixtures use temporary stores and synthetic encrypted files, without recognition models or production data.

The separately authorized [Windows activation and three-account live probe](../../implemented/testing/2026-10-16-live-account-fairness.md) verifies schema0012, original data preservation and real GLM account rotation with nine synthetic diplomas. It does not qualify Mac throughput or general recognition accuracy.

## Consequences

File-based fairness does not increase total throughput or make a long report interruptible. Stable ring order between accounts is intentionally independent of upload order. Exact pre-migration enqueue history is unavailable: legacy queued rows use their last update only as an ordering hint, with public queued_at NULL. Production Mac activation and real-model throughput are outside this change's verification.

The change adds two task columns, one enqueue index and one cursor row per scheduler lane, retaining short transactions and the existing model/request ownership. Queued work survives restart without a large earlier batch monopolizing later turns. No current service restart, Git publication or Mac deployment occurs in this implementation turn.
