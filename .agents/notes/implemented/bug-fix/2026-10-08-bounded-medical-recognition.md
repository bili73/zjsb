# Agent Note: Bound medical generation and reuse exact successful region predictions

Status: implemented
Scope: backend, tests, scripts/probe_current_pipeline.py, SPEC.md, ARCHITECTURE.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-08

## Problem

The user authorizes optimization and plans a Mac Studio server; remote access is undecided and explicitly deferred. Current medical processing is the main blocker, although four certificates still have one known omission and one wrong value. More RAM does not prevent autoregressive degeneration.

The v1 real acceptance preserves the native blood subset (24/24), scoped follow-up list and all 21 pages, yet fails after 181.625 seconds. A single-resident switch spends 55.735 seconds loading/warming Paddle; page 7 then generates 4096 tokens in 84 seconds and its repaired-image retry times out. This image has no native text and lacks safe internal white cuts. Numeric-varying template repetition also evades exact token-repeat detection. This evidence does not justify dropping the region or editing generated medical numbers.

## Decision

Dual-resident startup remains the default and loads serially. The later [independent queues decision](../../implemented/architecture/2026-10-08-independent-model-queues.md) permits cross-model inference and targeted stop while retaining180-second Task and181-second supervision. Medical generation uses20 seconds; time_limit returns partial text normally. Post-load RPC wait is soft plus10 seconds clipped by Task time. Model queue waiting counts Task time, not soft generation. Loading remains separately bounded and consumes active Task time when switching. Soft stop cannot preempt native/GPU hangs; hard supervision remains necessary. The v2 serial timings below remain historical evidence.

Medical regions make at most two attempts: primary on the original image, then the alternate on that same image. Incomplete termination (including time_limit) is never successful. Both incomplete attempts preserve their text and leave the region incomplete while subsequent regions continue. Certificates retain their existing input-repair policy and no new soft default. Real transport timeout and failed supervision retain the existing fatal boundaries.

A cache exists only within a Task's process_document call. Its key includes immutable checkpoint revision, model, exact encoded input digest, recognition task/prompt, preprocessing, max tokens and generation settings. Only nonempty, error-free explicit EOS is reusable. Cached text binds to the current page/region/bbox; no sources or measured inference durations are copied. Logical-region records identify reuse and origin. Failure, truncation, cancellation, another Task and rerun cannot reuse a cache entry. Unknown revisions disable reuse.

The isolated real-API probe supports explicit dual mode and all three frozen medical PDFs, while retaining single-resident replay and the four certificate controls. Every run has a fresh output directory and encrypted storage. Public results distinguish inferred calls from cache reuse, subset accuracy from coverage, startup from task wall time and incomplete from pending. Existing reference denominators and prior outputs remain immutable.

## Decision audit

The [durable task decision](../feature/2026-09-30-durable-document-tasks.md) partially overlaps: Task budgets, serial ownership and partial publication remain; medical retry ordering is changed. The [runtime lifecycle](../architecture/2026-09-29-local-dual-model-lifecycle.md) retains dual startup and hard cleanup. The [diagnostics decision](../feature/2026-09-30-local-diagnostics.md) gains one bounded termination enum. The [current acceptance](../testing/2026-10-08-current-pipeline-acceptance.md) retains the v1 failure and supplies isolated storage and scoring for v2. [Whole-corpus references](../testing/2026-09-30-whole-medical-corpus.md) remain frozen. Nothing is wholly superseded or archived. The separate [Mac migration proposal](../../proposed/architecture/2026-10-08-mac-studio-inference-service.md) remains unimplemented.

## Alternatives considered

- A larger Task timeout is the smallest parameter change and might accommodate slow output. It repeats the same degenerate decoding and raises user wait; retain the current bound and change the per-region behavior.
- Forced overlapping tiles can preserve pixels and might reduce generation size. The observed region lacks reliable internal cuts; split table headers and duplicated findings require additional contracts. First test normal soft return and the existing alternate model.
- More aggressive numeric-template repeat stopping could end the observed degeneration sooner. Genuine medical rows also have repeated structure with different numbers; do not make template normalization an unvalidated semantic classifier.
- Removing repeated logos could save time. Size or appearance is not proof of irrelevant content; exact successful inference reuse preserves every region instead.
- Caching across documents or approximate images saves more work. It complicates privacy, revisions and source identity; cache lifetime is one current Task only.

## Testing

- 225 backend CPU tests and 24 frontend tests pass; frontend typecheck/build passes. Regressions cover soft stop, worker reuse, parameter forwarding, cold-load separation, medical fallback, cache source rebinding, key distinctions and non-cacheable incomplete output. Hard failures remain fail-closed.
- The [v2 real API run](../../../../output/current-pipeline-acceptance-20261008-v2/summary.json) records all nine cases on Windows/CUDA with serial dual residency. Startup takes 156.000 seconds, separate from task wall time. The three entire PDFs take 120.250, 147.000 and 150.625 seconds without Task timeout. These are current-host measurements, not Mac or 16 GB HR qualification.
- All 154 medical OCR regions finish with recognized status: 66 physical model calls and 97 cache hits produce 163 logical attempts. Eight soft stops and one repetition stop remain in the records; their nine GLM fallbacks end at EOS. Cached attempts do not duplicate measured GPU costs. Recognized/EOS status establishes processing completion, not semantic completeness.
- The frozen blood-result subset remains 72/72 and the separately scoped follow-up lists retain 6/6/2 findings with valid sources. Native evidence is not scored as model-only accuracy. Four real certificates remain 37/39, with one missing award_date and one wrong school_name; all four absent references remain empty and six uncertain references remain unscored. All 49 certificate outcomes match v1, and four runtime-required fields remain absent.
- Published task/run/revision identities, encrypted snapshots and field CSV scores agree. Code/input hashes are unchanged and owned shutdown succeeds; prior outputs and original business data are preserved. The six public CSV/JSON files contain none of the scanned sensitive reference/actual values, material text or current API key. DDE index/verify is the documentation delivery gate.

The [v2 report](../../../../output/current-pipeline-acceptance-20261008-v2/REPORT.md), [plotting rows](../../../../output/current-pipeline-acceptance-20261008-v2/chart_data.csv) and [historical-store guard](../../../../output/current-pipeline-acceptance-20261008-v2/historical_store_guard.json) retain the measurement scopes. The original store remains 52 files and 31,188,405 bytes with identical tree hashes. The combined change in residency, generation bounds and reuse is not a single-factor ablation.

## Consequences

Bounded generation and exact successful reuse let these three PDFs finish without extending the Task budget. A soft bound may also stop a legitimately dense region; alternate recognition and manual review still matter. Full medical reports are not fully labelled, successful results remain NEED_REVIEW and medical stats remain null without coverage proof. The evidence cannot guarantee that every admissible 100-page document fits 180 seconds. Model-native kernels may overshoot until hard cleanup. Double residency and Apple-backend compatibility require target-machine validation. This iteration changes the medical retry strategy, not source medical values, clinical grading, review editing/export, model version, network exposure or the public API schema.
