# Agent Note: Keep certificate recovery crops out of two-image batches

Status: implemented
Scope: backend/ocr_app/pipeline.py, backend/ocr_app/model_queues.py, tests/test_certificate_recovery.py, tests/test_runtime_batching.py, tests/test_task_scheduler.py, tests/test_worker_pipeline.py, scripts, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, ARCHITECTURE.md, CHANGELOG.md
Last-verified: 2026-10-20

## Problem

Read-only inspection finds seven local-recovery attempts for the same certificate crop. All five one-image attempts preserve the specialization boundary and map the missing field; both two-image attempts contain the value but omit the following label/study-form/duration text and join unrelated lines, so the conservative mapper abstains. Every attempt uses identical input bytes, ends EOS and finishes far below the generation deadline. These repeated observations implicate the batched recognition path, not evidence of a general model accuracy rate or a proven low-level CUDA cause.

The model FIFO currently combines adjacent requests by task and token limit, including a recovery crop with another certificate's full page. A document-local one-retry limit does not imply a one-image model invocation.

## Decision

The pipeline adds a private context marker batch_policy=single only to required-field recovery requests and records that policy in the encrypted attempt. Existing worker and scheduler context forwarding carries it to ModelQueues. A marked FIFO head runs alone; a marked next request cannot join an ordinary head. The consumer neither skips that request nor delays ordinary dispatch to collect another pair. Adjacent ordinary requests retain qualified two-image batching, and Paddle keeps its independent queue.

Retain the same crop planner, one-retry cap, original180-second task deadline,20-second generation soft limit, task/run/revision fences, cancellation and partial/raw evidence. Do not loosen extraction rules or retrofit historical results/human corrections. Standalone serial calls already run singly; the marker only controls grouping in qualified runtime batching. No public API field, model, dependency, schema migration, priority jump or new user setting is introduced.

## Related-note audit

The [missing-field recovery](../../implemented/bug-fix/2026-10-20-certificate-missing-required-recovery.md) keeps its GLM choice and conservative merge; this decision narrows its grouping eligibility after new concurrent evidence. [Runtime batches](../../implemented/architecture/2026-10-19-runtime-two-image-batches.md) retain normal short-document batching and independent row ownership. [Independent queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) retain FIFO, cross-model concurrency and deadline semantics. Scope/topic searches across proposed, implemented and rejected find no earlier owner of a recovery-specific batch barrier. The positioning and model-expansion proposals are unrelated; no note is fully absorbed or archived.

## Alternatives considered

- Disable GLM batching globally: immediately restores single-image behavior, but removes throughput benefits from ordinary complete certificates. Isolate only the fragile recovery crop.
- Broaden the major regex: can recognize this particular joined output, but missing labels remove trustworthy field boundaries and similar text could silently become the wrong field value. Preserve abstention and improve the OCR input grouping.
- Retry singly only after a failed batched recovery: preserves more batching, but adds another model call and changes the approved one-recovery limit. Submit the existing recovery singly from the start.
- Use Paddle recovery: previously reads this crop, but reintroduces medical-queue contention and contradicts the user's selected GLM recovery path.

## Verification

The initial CPU run fails on missing marker creation and on all three batch-barrier arrangements. After the change,156 pipeline/worker/scheduler/queue/requirements/dispute tests and34 schema/certificate-mapping tests pass. Coverage includes marker creation and private forwarding, either batch position, adjacent recoveries, ordinary backlog pairing, cancellation, queued expiry, cross-model independence and preserved fields. Original failed and successful logs remain under tmp/certificate-recovery-isolation-*.log.

The isolated Windows HTTP/GPU probe uses three new accounts, encrypted storage and unchanged existing model weights. After serial dual-model startup/warmup with size2 enabled, three rounds repeat the same three real certificates; the first round also runs a22-page medical PDF. All three target recoveries return the visually verified specialization from identical crop bytes and use batch_size1/batch_policy=single; no filled primary field changes. Three ordinary two-row calls and nine overlapping GLM/Paddle call intervals occur. The medical task finishes in88.906 upload-to-terminal seconds with all50 OCR regions recognized and zero incomplete regions; all10 tasks finish NEED_REVIEW, with zero HTTP5xx and loading sampling errors. Repeated inputs are four unique source materials, not ten independent accuracy samples.

Target upload-to-terminal observations are23.313/16.438/16.438 seconds. Supplemental calls take4.610/2.547/2.516 seconds, with4.531/2.422/2.390 inference seconds; recorded recovery queue waits are zero. Startup18.797 seconds is separate. Evidence and the seven earlier observations, including both unsuccessful paired outputs, remain under output/certificate-recovery-concurrency-20261020-v1/. Raw attempts, results and source mapping stay encrypted. These qualify the failure mode and host call overlap, not population accuracy, sustained capacity or CUDA-kernel overlap.

After idle backup/testing, Windows is restored in dual-resident/size2 mode. The activation record output/windows-preview-restart-20261020-113122-ae47b6/verified.json verifies15 unchanged tables,499 tasks,4 users,1 existing session,4332 referenced blob metadata entries,2 keys and16 HTTP static files; SQLite quick_check/public health and anonymous-denial checks pass. Probe code hashes match running source. No production task rerun, session replacement, frontend publication or Mac operation occurs.

## Consequences

A recovery occupies the GLM queue alone and may wait behind an existing call. It does not preempt or remove the180-second budget, and correct reading is not guaranteed for all future material. A single sample and a few concurrency trials qualify this failure mode only. Shared-GPU contention and clinical accuracy remain outside this change.
