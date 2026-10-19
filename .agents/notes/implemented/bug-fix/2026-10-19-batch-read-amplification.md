# Agent Note: Avoid repeated full-result work while loading batch summaries

Status: implemented
Scope: backend/ocr_app/task_store.py, frontend/src/monitor.ts, tests, frontend/tests, ARCHITECTURE.md, RUNTIME.md
Last-verified: 2026-10-19

## Problem

The user reports slower loading. Read-only Windows profiling finds that listing50 batches reconstructs293 public tasks and decrypts1537 values, spending463.87ms under cProfile, including222.99ms recalculating export eligibility that the batch summary does not expose. The20-batch call reconstructs108 tasks and takes205.12ms. The host has15.15GiB available RAM and4.5percent sampled CPU; public health and homepage are milliseconds. This establishes unnecessary work, not the full cause of any remote or browser delay.

The frontend additionally reloads task details whenever a batch has status PROCESSING. That state intentionally includes NEED_REVIEW, so one running batch can cause every old review-pending batch to reload on each polling cycle. Existing explicit refresh, version-change tracking, active task tracking and policy revisions already provide narrower invalidation.

## Decision

Build batch summaries from status, type, expiry and update metadata without calling public task projection or export validation. Keep source-result reads only where person-package name suggestions require them. Preserve owner checks, pairing, warnings, counts, dates and public response shape. Remove PROCESSING alone as a reason to reload already-loaded task details; retain explicit refresh, metadata/revision invalidation, active tasks, unloaded tasks and required-policy changes. No cache, schema, model, budget or export rule changes.

Older responses without updated_at retain conservative PROCESSING refresh, and pending user actions always reconcile their task batch. This preserves compatibility and removal/error recovery without repeatedly projecting stable history from current responses. Initial task loading and explicit cross-session refresh remain unchanged.

## Related decisions

The [numbered pagination](../../implemented/feature/2026-10-16-numbered-list-pagination.md) and [account-owned batches](../../implemented/feature/2026-10-10-account-owned-batches.md) retain visibility and task-version reconciliation. [HTTP admission](../../implemented/bug-fix/2026-10-16-bounded-http-writes.md) governs writes; ordinary reads stay outside that queue. [Preview scroll work](../../implemented/bug-fix/2026-10-18-source-preview-scroll-performance.md) concerns rendering and is not proof of this read-path improvement. These decisions are complementary and remain active.

## Alternatives considered

- Increasing HTTP workers or adding a response cache could hide repeated work but complicates session/version invalidation and does not remove wasted projection.
- Ignoring all completed/review-pending batches avoids traffic but loses explicit cross-session refresh and policy updates. Retain the existing invalidation fences.
- Returning fewer public fields or skipping missing-field calculation in task responses reduces payloads but changes frontend contracts. Keep task responses intact and optimize only summary construction and redundant calls.

## Testing

New tests reproduce summary projection and repeated polling before the change. Afterward22 batch/ownership/deletion tests,14 business HTTP tests,22 person-package/name tests,247 frontend tests and typecheck pass. The frontend regression checks stable history, active tasks, metadata change, explicit refresh and pending actions. Existing pagination/cross-session tests preserve late-response fences, policy refresh, deletion and off-page records. An older test that mocked tasks() is converted to real synthetic mixed/empty batch rows, so summary implementation no longer dictates the fixture.

Read-only comparisons of all returned fields over340 tasks and72 batches match both versions. Five interleaved unprofiled runs show20-batch median91.624→4.674ms and50-batch median322.383→28.529ms. Results, individual timings and response hashes are retained in output/batch-read-profile-20261019-094259/report.json. These are store-call timings, not HTTP, rendering or WAN latency. The initial test run also exposed a synthetic person-package prefix assumption and a missing metadata fallback; both are corrected and the failed evidence remains in the execution trace. No original data is changed by profiling.

## Consequences

The user clarifies that only Windows is slow and Mac is online and functioning normally. No Mac write or inference experiment is authorized. These changes reduce unnecessary work locally without skipping export validation in actual task/export reads. Windows activation after the CUDA experiment verifies identical original database/material/key contents and16 served frontend build hashes; the later preview/diagnostic restart rechecks all15 table contents and3623 existing file hashes. Three actual diagnostic medical tasks preserve original history, and batch reads during OCR range8.4–42.3ms in this small local run. The [combined report](2026-10-19-preview-and-diagnostic-read-cost.md) distinguishes model timing recovery from measured read-path fixes. The Mac branch and deployment remain unchanged. Existing uncommitted documentation/index repairs are preserved.
