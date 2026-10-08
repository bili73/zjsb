# Agent Note: Run certificate and medical tasks through independent model queues

Status: implemented
Scope: backend, tests, SPEC.md, ARCHITECTURE.md, RUNTIME.md, IMPLEMENTATION_PLAN.md, scripts, AGENTS.md
Last-verified: 2026-10-08

## Problem

The user explicitly authorizes cross-model concurrency in the current Windows test version, not only the future M3 Ultra deployment. Dual residency currently reduces loading waits but one coordinator executes entire documents synchronously. A medical report blocks certificates even when GLM is unused. Conversely fallback makes it incorrect to assume the two document types never share a model.

The existing pipeline uses PyMuPDF, whose [official guidance](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html) excludes concurrent thread use, and redirect_stdout mutates process-wide state. The watchdog also closes the entire runtime while holding a SQLite writer transaction, which would interrupt or block an unrelated active task.

## Decision

When both models complete serial startup successfully, use two bounded document lanes: one certificate lane (DIPLOMA and DEGREE_CERT) and one medical lane, each with at most one supervised CPU task process. Single-resident or startup-degraded operation retains one document lane. The coordinator and only model owner remains in the supervised runtime tree. No unbounded thread/process pool or distributed scheduler is introduced.

Each model has one FIFO recognition queue and a single consumer, so GLM requests never overlap GLM and Paddle requests never overlap Paddle. Ready GLM and Paddle may recognize concurrently. Fallback releases the first request before enqueueing the alternate, preventing two-model lock inversion. Serial checkpoint load/warmup and the current Task-local exact EOS cache remain. Concurrent model loss does not unload the healthy model or trigger an uncoordinated reload; recovery policy stays bounded and explicit.

Each request binds immutable task/run/request identity and a model process generation. Queue waiting occurs after document claim and counts within the existing 180-second active budget; the 20-second medical generation budget begins only at actual execution. Expired queued work is removed without terminating another run's model. The coordinator continues processing control messages while documents run.

Preserve the existing one-second supervision margin after the 180-second pipeline/queue deadline. It allows a cooperative child to publish partial evidence; it never authorizes more recognition. Immediate fencing at the pipeline deadline would race and discard that evidence. The private standalone diagnostic RPC retains global cleanup on its own wait timeout and is not the ordinary targeted business-stop path.

Cancellation and watchdog stop target the precise task/run, queued requests and only any matching in-flight model request. A short database transaction fences stopped-run publication before process shutdown; shutdown confirmation occurs outside the writer transaction, followed by exact-run recovery. A small additive migration records the internal stop fence without changing public result/task schemas. Delayed stop cannot kill a newer run or a different model owner. Failed stop confirmation remains globally fail-closed; ordinary cancellation/request failure must not kill the unrelated model lane. Application exit still confirms every owned CPU/model descendant.

Keep diagnostics anonymous and source evidence encrypted. Record model queue waiting separately from actual inference and retain failed/stopped attempts. This authorizes an isolated production concurrency probe on the current GPU; standalone accuracy benchmarks remain single-model and serial. Simultaneous inference is not a promise of faster kernels on a shared GPU or of Mac support.

## Decision audit

The [local lifecycle](2026-09-29-local-dual-model-lifecycle.md) is partly changed: dual loading/ownership is retained, but global serial inference is replaced in successful dual operation. [Durable tasks](../feature/2026-09-30-durable-document-tasks.md) retain run/revision, encryption and recovery; whole-runtime timeout/long writer locks are replaced for targeted stops. [Bounded medical recognition](../bug-fix/2026-10-08-bounded-medical-recognition.md) retains soft budgets/cache and historical serial timings. [Diagnostics](../feature/2026-09-30-local-diagnostics.md) retain allowlists. The [temporary workbench](../../archived/feature/2026-10-08-temporary-recognition-workbench.md) adds local source comparison. The [Mac proposal](../../proposed/architecture/2026-10-08-mac-studio-inference-service.md) remains unimplemented. Nothing is wholly superseded or archived.

## Alternatives considered

- Two pipeline threads require less process plumbing. PyMuPDF thread use and global stdout redirection can corrupt execution, so isolate document processing in processes.
- One global queue is simplest and fully validated. It preserves avoidable cross-model head-of-line blocking that the user now explicitly asks to remove.
- Giving each document its own model processes gives clear ownership. It duplicates weights and competes without per-model FIFO control, so retain two resident model owners.
- Pausing active time during model waiting could prevent contention-related deadlines. It would silently alter the established bounded Task semantics; preserve 180 seconds including waits and measure the new behavior first.
- Killing the runtime on every task timeout is an existing strong safety boundary. It also kills an unrelated task and may block its SQLite publication; use run fencing and targeted confirmation, reserving global kill for shutdown or supervisor failure.

## Testing

- All269 backend CPU tests pass, including queue FIFO/expiry, fallback, delayed ownership/cancel races, targeted watchdog, unknown stop fail-closed, migration0001→0002 byte continuity, short-stop transactions allowing other publication, protocol output isolation and the180/181 publication margin. A real lightweight two-Job test confirms one targeted Job exits while the other remains alive; it uses noGPU.
- All31 frontend tests and TypeScript/build pass; final synthetic Edge attempt003 passes12 checks. Browser mock evidence is separate from real backend/model evidence; PDF page-request binding does not verify the plugin's final rendered page.
- The [isolated production probe](../../../../output/concurrent-pipeline-20261008-v1/REPORT.md) completes9/9 tasks inNEED_REVIEW, noTask/RPC timeout:71 physical calls and97cache hits,11 verified cross-model/cross-run request overlaps,0same-model/0startup overlaps,39observed handles allsignaled. Backend/source hashes and52historical business files remain unchanged. Current Windows RTX3060/31.814GiB only.
- Three medical tasks take94.101/110.905/127.935 active seconds, with0.540/94.634/205.592 seconds pre-claim queue wait. Blood72/72 and title findings6/6/2 remain fixed subset outcomes; real certificate37/39,4correct absence,6uncertain,49field conclusions unchanged from serialv2. Full medical accuracy/stats and confidence remainnull.
- Startup17.157seconds is serial; previousv2 startup156seconds and active119.823/146.469/150.082 remain separate. Warm/cache conditions were uncontrolled, so neither these differences nor the faster medical tasks without any overlap establish causal speedup. [Independent timing audit](../../../../output/concurrent-pipeline-20261008-v1/timing-audit.json) checks timing sources, matchedphysical calls, checkpoint/input consistency and these limitations. Only7real files and syntheticPNG are byte-identical across rounds; syntheticPDF hash differs.
- Model request_id is scoped byTask/run/model rather than globally unique. Public interval/overlap joins require case/model/time or run context. Private diagnostic RPC still globally closes on its own wait timeout; normal business stops have their own targeted control and tests. Actual GPU cancellation/OOM was not deliberately injected. DDE gates run at delivery.

## Consequences

Both models share the same GPU. Contention can increase latency, soft stops or OOM; individual serial scores and the earlier 156-second startup do not qualify this execution mode. Killing a stuck model request may disable that model for the current session; the other lane must remain usable. Native file parsing remains bounded by supervised process lifetime. Mac process supervision and remote-user access still require separate work.
