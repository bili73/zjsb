# Agent Note: Preload both OCR models for an interactive local session

Status: implemented
Scope: ARCHITECTURE.md, SPEC.md, openapi.yaml, IMPLEMENTATION_PLAN.md, backend, tests, scripts/probe_runtime.py, RUNTIME.md, start.cmd, start.ps1, requirements-app.lock.txt
Last-verified: 2026-10-08

## Problem

HR uses a local PC without an inference server. Loading models on each first use or switch interrupts interactive work. The user explicitly chooses startup loading and dual residency, with single residency reserved for machines that cannot sustain both. The previous on-demand default no longer reflects that choice.

## Decision

The launcher exposes the lightweight local UI/service first and starts an independent runtime worker. It sequentially loads and warms GLM-OCR then PaddleOCR-VL in their existing isolated environments. Both remain resident in default dual_resident mode. The [independent queues](2026-10-08-independent-model-queues.md) change successful dual operation to cross-model inference while retaining serial loading/warmup and single-resident switching. The Vue page shows actual enum states without fabricated percentage or ETA.

The single_resident mode starts with GLM. A request for the other model first closes the previous model's supervised process tree, then loads the requested model. An explicit --mode choice persists in .runtime/settings.json. A resource failure changes only the current session mode. A healthy model survives where possible; a failed resource load receives at most one isolated recovery, and failed recovery disables that model for the session. Dependency errors do not become resource errors. Polling never starts models. Inference failure has no hidden retry: the later Task pipeline owns the bounded region retry and whole-Task budget.

RuntimeClient imports no model libraries. Trusted private JSON-lines pipes connect the application, runtime worker and model workers. Public HTTP binds 127.0.0.1 and rejects non-loopback clients and unapproved Host values. Health and static files are public locally; the second-stage business routes require an API key. No public model-control or shutdown API is introduced. Runtime snapshots retain the v1.9 enum structure under SPEC/OpenAPI v1.10, never PIDs, local paths or raw exceptions.

The launcher owns lifetime. Closing a browser tab does not exit the application. Windows Job membership is assigned atomically at process creation with STARTUPINFOEX / PROC_THREAD_ATTRIBUTE_JOB_LIST; the owner alone holds the non-inherited KILL_ON_JOB_CLOSE handle. Creation/supervision failure prevents further scheduling. Normal shutdown requests exit and then performs bounded Job cleanup; owner termination also kills contained processes. Job activity reaching zero is followed by waiting for the direct process handle to signal. The acceptance probe retains known descendant handles and checks those within a shared five-second deadline. PID visibility alone is not termination evidence. A shared Windows byte lock prevents another application or legacy benchmark from acquiring the GPU channel.

## Implementation boundary

This note owns the launcher, independent worker, model adapters, Windows supervision and health snapshot. The [durable-task decision](../feature/2026-09-30-durable-document-tasks.md) adds SQLite, authenticated uploads, PDF/region routing, seven-day artifact cleanup and persisted recovery. Health reports actual database and queue state. Full review editing, export and broader document families remain later work.

Each model load/warmup uses a bounded 120-second window. Private recognition caps calls at 180 seconds; business calls receive the remaining shared whole-task deadline, including required model switches. Independent supervision bounds native/GPU hangs. Closing callers share a bounded termination confirmation; failed cleanup never authorizes task recovery. The model adapter returns termination_reason and keeps allocator peaks separate from host-process measurements. [Local diagnostics](../feature/2026-09-30-local-diagnostics.md) adds persistent safe error locations and offline export.

[Bounded medical recognition](../bug-fix/2026-10-08-bounded-medical-recognition.md) supplies a 20-second soft generation budget and limits the post-load RPC to soft plus ten seconds, clipped by Task time. A normal time_limit keeps the worker usable; hard timeout removes it, and unknown cleanup prevents further scheduling. Independent queues now isolate owners for concurrent inference; a failed parallel-session model stays disabled until restart rather than unloading the healthy model to recover it.

## Decision audit

The [automatic-layout experiment](../testing/2026-09-29-automatic-layout-evaluation.md) partially overlaps in resource policy, but remains a serial single-resident benchmark. Its accuracy results do not validate production dual residency. The task and diagnostic decisions extend this runtime without superseding its residency choice. The DDE process note owns tooling conventions.

The [schema extraction diagnostic](../testing/2026-09-30-schema-extraction-benchmark.md) also isolates one resident GLM process and leaves this production residency policy unchanged.

The [dual extraction diagnostic](../testing/2026-09-30-dual-certificate-extraction.md) owns serial accuracy experiments rather than production fusion. The [Paddle 1.6 qualification](2026-09-30-paddle-vl-16-upgrade.md) preserves the public model key and original checkpoint/environment while testing a separate native Transformers adapter.

## Alternatives considered

- On-demand single residency minimizes memory and broadens hardware compatibility. It remains the fallback, but is not the default because the user prioritizes avoiding interactive load/switch waits.
- Concurrent loading could shorten startup on some hardware. Sequential loading bounds resource overlap while an already available page shows progress.
- A shared intranet inference server reduces HR client requirements. The company has none, so deployment remains local.
- In-process model imports avoid IPC. Separate processes preserve validated model dependencies and allow hard cleanup of a hung model without making HTTP availability depend on model imports.

## Consequences

Dual residency removes reloads during normal model switching but increases idle RAM/VRAM and retains two CUDA contexts. Separate environments, native Windows Job code and IPC add maintenance cost; CPU supervision tests cover ownership failures. Stable pages stop polling and refresh on focus or explicit refresh, so an untouched page may show a stale snapshot; the page states that limit.

Normal exit, crash cleanup and lightweight fault cases are tested. Task recovery, cancellation races, encryption and authentication have second-stage CPU tests and separate integration evidence. Full document resource qualification, CPU-only inference and actual HR hardware remain unverified. No promise is made for a 16 GB PC or instantaneous GPU release after a driver fault.

## Testing

Real serial probes use a nonsensitive 1000x300 synthetic image, GLM → Paddle → GLM. Dual v3 starts in 11.766 seconds and reuses both model PIDs across all requests. Single v1 starts in 5.828 seconds; calls requiring a switch take 6.531 and 6.547 seconds. All six predictions exactly match the synthetic text and end at EOS; all known process handles are signaled after shutdown. These are local cached-start measurements, not certificate accuracy or target hardware validation.

The first two dual attempts remain unaccepted and retained, including the v1 raw status-before-cleanup defect documented in its audit. Job exit timing and PID-based probe checks are corrected; accepted measurements use the corrected handle checks. Runtime and close errors are preserved separately, and probe cleanup always attempts to save results.

CPU tests cover serial scheduling, bounded OOM recovery, dependency failure, invalid input, process death, hanging RPCs, invalid protocols, failed cleanup blocking dispatch, owner termination, nested jobs, unrelated-process survival, failed creation handle counts, HTTP contracts and local access boundaries. Frontend tests validate health parsing and refresh policy; TypeScript/build and actual Edge desktop/narrow viewport rendering pass. Actual HTTP answers during loading at about 0.531 seconds; duplicate launch is rejected. OOM tests use fake models rather than intentionally exhausting the GPU.

Commands and evidence: [runtime guide](../../../../RUNTIME.md), [report and plotting CSVs](../../../../output/runtime-acceptance-20260929/REPORT.md), tests/, frontend/package.json. Host RSS, private commit and per-process PyTorch allocator metrics have different scopes; no aggregate minimum hardware requirement is inferred from them.

The separate [2026-10-08 v2 business run](../bug-fix/2026-10-08-bounded-medical-recognition.md) measures Windows/CUDA dual-resident startup at 156.000 seconds and completes three PDFs in 120.250/147.000/150.625 task-wall seconds. It preserves the earlier cached synthetic startup timings above rather than treating those different conditions as interchangeable. Neither measurement verifies a Mac backend or an unknown HR machine.

## Future deployment

The user now plans a central Mac Studio. The [Mac qualification proposal](../../proposed/architecture/2026-10-08-mac-studio-inference-service.md) records the changed future host and undecided remote-access boundary; the current implemented Windows lifecycle remains in force until the new host is qualified.

The former frontend portion is retired by the [frontend retirement](../../implemented/simplification/2026-10-08-retire-temporary-frontend.md); current Scope covers surviving code. Old UI checks describe historical acceptance.
