# Agent Note: Qualify Mac Studio before moving the local OCR service to a shared host

Status: proposed
Scope: ARCHITECTURE.md, SPEC.md, RUNTIME.md, IMPLEMENTATION_PLAN.md, backend
Last-verified: 2026-10-09

## Problem

The user confirms a Mac Studio with M3 Ultra and 96 GB unified memory and proposes model deployment with API access. Its macOS version, GPU-core variant and actual performance remain unverified. Remote access is still undecided. The existing local Windows/CUDA service is not a portable Mac or remotely authenticated deployment; memory capacity does not establish a speedup over the current RTX 3060.

## Proposal

Keep current recognition optimization independent of the host backend. When the Mac is available, qualify its native Apple GPU route using the existing frozen evidence and separate measurements. The official [GLM MLX guide](https://github.com/zai-org/GLM-OCR/blob/main/examples/mlx-deploy/README.md) and [Paddle Apple Silicon guide](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PaddleOCR-VL-Apple-Silicon.en.md) provide concrete MLX-VLM paths. Paddle's example is 1.6 and identifies M4 validation; this is not evidence that the current original Paddle revision behaves identically on every Mac chip. Preserve version, quantization and backend distinctions in every result.

The recommended rollout first exposes private Mac region-inference APIs to the existing business pipeline for qualification; the eventual centralized topology places the business API, persistent queue, storage and model workers on the Mac, with HR using a browser. These are proposed stages, not an implemented remote service. Preserve native PDF extraction, region preparation and field mapping; the model API alone is not an end-to-end document-processing API.

The MLX-VLM maintainer also documents the original [PaddleOCR-VL model](https://github.com/Blaizzy/mlx-vlm/blob/main/mlx_vlm/models/paddleocr_vl/README.md), so migration does not by itself require replacing v1 with 1.6. Pin and test the current checkpoint/precision first. Implement and qualify server-side soft generation stop, cancellation and hard process cleanup: a client HTTP timeout cannot be treated as confirmed inference termination, and our time_limit protocol is not automatically supplied by an OpenAI-compatible endpoint.

First test each model serially on the actual Mac. Validate numbers, arrows, long regions, termination, latency and resource measurements before connecting the existing field mapper. Then adapt inference, process ownership/hard shutdown, key protection and startup. Current code requires CUDA, Windows Job, DPAPI, msvcrt and Windows virtualenv paths; neither copying the checkout nor changing cuda to mps is an accepted implementation.

Choose remote access only after the user chooses a private device network or authenticated HTTPS route. Keep model ports private. The current loopback/Host restrictions, shared local operator Key and unscoped Task queries are not a remote-user identity/ownership contract. Server authentication, proxy trust, task permissions, TLS and log/privacy boundaries require their own concrete implementation and acceptance. Do not publish a tunnel or deploy credentials in this phase.

## Decision audit

The user now requests central Docker deployment with one or two accounts. The [hosted web-session proposal](2026-10-09-hosted-web-session-auth.md) records the candidate replacement for manual API keys, the retained browser HTTP interfaces and the distinction between containerized business services and native Apple-GPU inference. Both proposals remain unimplemented; the qualification and cancellation gates here still apply.

The current Windows [independent queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) implement authorized cross-model scheduling before Mac qualification. Its supervision, GPU timings and DPAPI remain platform-specific. The [temporary workbench](../../archived/feature/2026-10-08-temporary-recognition-workbench.md) adds local source comparison without exposing remote services.

The [local dual-model lifecycle](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) remains implemented for the current Windows host. Its original no-server assumption changes in the user's future deployment, so this proposal is linked instead of silently rewriting or archiving it. The [durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md) retain storage/privacy contracts that require a Mac-specific key-protection strategy. [Bounded medical recognition](../../implemented/bug-fix/2026-10-08-bounded-medical-recognition.md) is implemented and measured separately on Windows/CUDA with serial dual residency; its three completed PDF runs and 156-second startup do not qualify Apple inference or remote deployment.

## Alternatives considered

- Copying the current Windows app is fastest in appearance. Its CUDA, supervision and key protection are platform-specific, so it cannot serve as a qualified Mac installation.
- A direct PyTorch mps substitution is smaller. Generic device support does not prove these models' processors, operations or masking compatible; official native MLX deployment is the first concrete candidate to qualify.
- Publicly exposing the current loopback API preserves the UI. A tunnel does not supply per-user roles, task access or proxy trust; the user has deferred that choice and the current security contract remains local.
- Replacing model version, quantization, layout and backend together may improve throughput. It confounds quality regressions; record and qualify changes separately.

## Acceptance criteria

- Actual chip/RAM/macOS and exact model/backend revisions are recorded; real serial labelled results and stop behavior pass on that hardware.
- Mac process supervision and encryption/key recovery are verified rather than inferred from Windows tests.
- Remote identity, permissions, proxy trust and TLS are selected and tested before exposing business data; model endpoints are private.
- Current original materials and encrypted Windows artifacts are preserved; DPAPI migration is not represented as copying a usable key.

## Risks

Official support does not guarantee accuracy, latency, coexistence or unattended reliability on this untested M3 Ultra configuration. Backend/version/quantization changes may alter medical values. Remote exposure changes data processing and access boundaries. The Mac is not accessible in this session; this proposal remains unimplemented and does not block the user-authorized recognition optimization.
