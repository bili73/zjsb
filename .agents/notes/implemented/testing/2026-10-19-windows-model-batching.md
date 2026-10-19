# Agent Note: Qualify model batching on Windows before a Mac adaptation

Status: implemented
Scope: scripts, tests, RUNTIME.md
Last-verified: 2026-10-19

## Problem

Account rotation is implemented but each model still handles one request. The next approved step is to measure genuine1/2/4-request batching before changing production ownership, cancellation or deadlines. The user requires keeping the Mac online environment untouched and now requests reproducing batching on Windows first.

## Decision

Use the installed fixed GLM and original Paddle checkpoints, respective CUDA/Transformers environments, bfloat16/SDPA and existing prompt templates. Run each model alone under the existing exclusive GPU experiment lock; serialize model loading and batch-size rounds. Create distinct synthetic certificate/table images and run real batched generate calls with padding and per-row output separation. Compare1/2/4 throughput, first token/completion timing, tokens, peak memory, EOS/truncation and normalized text agreement against size1. Record load/warmup separately. A row-local synthetic cancellation/deadline probe checks that other rows can finish; it does not certify application task cancellation or Mac MLX behavior.

Preserve the idle Windows service database, keys, files and previous outputs before its owned launcher tree stops; restore dual_resident after experiments and verify preservation. Do not run a second inference process alongside the resident service or modify model environments/weights. Keep batch failures, OOM and differences; do not enable production batching from a throughput-only result. Mac SSH activity so far was read-only: HEAD63c8f3e, dual models ready, MLX-VLM0.7.6/MLX0.32.3 and BatchGenerator signatures. Read-only inspection is allowed; no model experiment, write or release runs there, and no further Mac activity is performed during this qualification.

## Related decisions

The [account-fair queue](../../implemented/architecture/2026-10-16-account-fair-document-queue.md) is the completed first step and remains active. [Independent model queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) retain their single-owner production fences. This is a throughput/consistency experiment, not a serial business accuracy benchmark. [Local read amplification](../../implemented/bug-fix/2026-10-19-batch-read-amplification.md) is a separate latency repair and passes its own tests before a service restart activates it.

## Alternatives considered

- Raising file-worker concurrency is easy but queues more work behind a still-serial model and consumes task deadlines without proving throughput.
- Changing the Mac production service would test the target backend directly, but the user explicitly postpones any operation there.
- Reusing MLX code directly on the current Windows CUDA runtime hides different processors/caches and cannot qualify the installed backend. Keep backend-specific generation and carry over the measured protocol and ownership requirements.

## Testing

All1/2/4 trials complete with8 synthetic images per model. GLM model-call totals are17.724/10.310/6.569s (up to2.698x), with8/8 serial-output agreement at each size. Paddle totals are12.599/10.954/8.606s (up to1.464x), but size2 and4 each match only6/8 serial outputs, including differing sample identities. Its qualification fails despite EOS and a normally exiting process; retain all failed evidence. The script now exits2 when qualification fails. Both models pass row-local stopping probes; three pure-state tests pass without CUDA. This does not qualify application-level ownership, cancellation or hard stops.

The report, graph CSV and raw JSON/logs are retained under output/cuda-batching-20261019-095001. Startup is separate (GLM38.375s+2.188s warmup, Paddle24.172s+1.140s). Batch totals exclude HTTP/business persistence and aggregate return waits for the entire generate call; per-row internal finish times are not early HTTP delivery. Windows restore verifies all prior database rows (340 tasks/72 batches),3608 original material/key hashes and16 served build files. The completed artifact is this qualification experiment; production batching is still unimplemented and disabled. No Mac write or inference experiment is performed.

## Consequences

Synthetic output agreement is not business accuracy. Offline CUDA batching does not qualify Mac MLX, mixed production requests, fair batch admission, per-task hard stops or long medical reports. The12GiB Windows GPU may cap batch size; larger batches can increase first-response latency or trigger OOM.

GLM demonstrates a candidate throughput improvement; the initial Paddle differences block its qualification at that point. Each size has one short synthetic trial, not a sustained capacity distribution. Keep existing per-model FIFO until a separately approved runtime implementation and actual material checks satisfy its invariants.

Follow-up CPU-only checks find each Paddle image's packed pixel patches, grids and unpadded prompt tokens identical to the single-image preparation. Executing the exact installed PaddleOCRAttention class with small random tensors reproduces cross-image influence: changing only a peer image changes the first image's output by max5.0814; an explicit block mask agrees with single-image output within5.96e-8. Source inspection finds that the SDPA branch does not use cu_seqlens to construct an image-isolating mask, unlike its FlashAttention path. Evidence is retained in paddle-input-check.json and paddle-vision-isolation.json, including source hash. This initial experiment and failed outputs remain unchanged.

The subsequent [packed-image isolation repair](../bug-fix/2026-10-19-paddle-packed-image-isolation.md) installs a repository adapter and requalifies Paddle in a fresh output. All8 outputs agree at1/2/4; totals13.962/8.082/5.713s, up to2.44x against the new single-image baseline. This resolves the synthetic isolation failure, not production task scheduling, actual-material accuracy or Mac qualification. The production per-model exclusive FIFO remains active; subsequent [Windows runtime admission and row ownership](../architecture/2026-10-19-runtime-two-image-batches.md) supplies the separately qualified short-file batching. This note preserves the earlier failed experimental evidence.
