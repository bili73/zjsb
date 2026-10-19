# Agent Note: Isolate packed Paddle images without a quadratic batch mask

Status: implemented
Scope: backend/model_worker.py, backend/ocr_app, scripts/probe_cuda_batches.py, tests, ARCHITECTURE.md, RUNTIME.md
Last-verified: 2026-10-19

## Problem

The user authorizes repairing image isolation before enabling batching. The [Windows qualification](../../implemented/testing/2026-10-19-windows-model-batching.md) finds differing Paddle batch outputs although per-image patches/grids/tokens match single-image inputs. The installed vision attention packs images along one sequence, but its SDPA branch ignores cu_seqlens when selecting attention bounds. The exact-class CPU reproduction shows a peer-only input change altering another image's output. Existing production single-image FIFO is not this experimental batched path.

## Decision

The original Paddle checkpoint loads a narrowly scoped adapter from repository code. Weights, cached model source and environments remain unchanged. For packed SDPA vision input, the adapter calls the original attention separately on the cu_seqlens image segments, slices RoPE and any supplied mask to the same segment, then concatenates outputs. Single-image and non-SDPA calls use the original path unchanged; the single-image path performs no per-layer device-to-host boundary synchronization. Segmentation is validated before execution; unsupported attention-debug output fails explicitly instead of bypassing isolation. Loading twice is idempotent. Decoder batching, precision, prompts, cancellation and ownership are unchanged.

Actual CUDA batch1/2/4 are requalified against the new single-image baseline, preserving previous failures. Startup, whole-call latency, memory and row-local stopping are recorded separately. A fresh output, exclusive GPU lock and idle Windows backup/stop/restore retain deployment ownership. Qualifying isolation does not enable production batching; application-level task ownership/deadlines and Mac adaptation remain separate.

## Alternatives considered

- A block-diagonal mask preserves fused packed QKV but allocates quadratically with all image patches; large real photos can erase memory/latency benefits. Segment original attention instead.
- Switching to FlashAttention may use cu_seqlens natively, but changes dependencies and backend qualification on Windows. Repair the installed SDPA path first.
- Serializing whole model calls preserves isolation easily but cannot test batched decoder throughput. Restrict serialization to vision attention segments.

## Testing

Four exact installed attention-class CPU tests pass in the Paddle environment, covering unequal image sizes, peer replacement, RoPE/masks, single-image compatibility without boundary synchronization, repeat installation and malformed boundaries. App tests gain no Torch dependency. The real CUDA experiment in output/cuda-isolation-20261019-103529 passes: batch1/2/4 model-call totals13.962/8.082/5.713s, with8/8 serial-output agreement and8/8 EOS at each size. Peak allocated memory is1.997/2.195/2.593GiB. Row-local cancellation/deadline probes pass; these are not application-level cancellation tests.

The idle Windows service is backed up and stopped only for its exclusive experiment. Immediately after restoration all15 database tables,3705 existing material/key files and16 served files match the snapshot. Dual-resident health is subsequently ready. Later normal UI/HTTP checks add expected login/access history; original task/run/results and prior files remain preserved. Mac receives no write or inference operation.

## Consequences

Per-image attention calls add kernel launches, but this short synthetic trial still reaches2.44x the new single-image throughput at size4. It is not a business accuracy benchmark, sustained capacity estimate or Mac measurement. Vision segmentation alone does not prove application cancellation or long-report accuracy. An incompatible future checkpoint must not silently take an unisolated fallback. This adapter alone does not authorize runtime batching. The separately implemented [Windows runtime admission and row ownership](../architecture/2026-10-19-runtime-two-image-batches.md) qualifies at most2 short-file images per exclusive model call; long medical files retain serial lane admission. The original isolation experiment is preserved.
