# Agent Note: Compare serial GLM and Paddle certificate extraction

Status: implemented
Scope: scripts, tests, IMPLEMENTATION_PLAN.md
Last-verified: 2026-09-30

## Problem

The user asks for ready-to-use specialized card models and explicitly authorizes a GLM-OCR plus PaddleOCR-VL experiment if research does not establish an ideal local alternative. Public candidates either provide card correction, digit recognition, domain training infrastructure, generic OCR wrappers, or proprietary offline SDKs. None verified in this search supplies downloadable, ready-to-use weights for all required Chinese card and educational-certificate fields.

## Decision

The isolated paired diagnostic uses four encrypted certificate inputs and frozen visual references from the valid schema v2 experiment, plus three existing front-side bank-card samples scored only on card_number. Bank references are visually rechecked before inference. Inputs, references, prompts, merge policy and code hashes are frozen. Production fusion behavior and old experiment artifacts remain unchanged.

Paddle first returns full OCR text. GLM then runs three paths on the same image: full-text OCR plus the existing field mapper, direct English-key image JSON extraction, and image JSON extraction with Paddle's OCR text as untrusted auxiliary evidence. Deterministic postprocessing compares direct GLM values with Paddle field candidates: a GLM-first fill keeps its preview value but flags conflicting nonempty values; an agreement-only path abstains on disagreements and one-model values. Both models run on every input, sequentially, with one resident process at a time. No third model or calibration claim is introduced.

Measure exact normalized present-field accuracy, missing/wrong values, absent-field false positives, consensus accuracy and coverage, review reasons, serial paired request time and memory. Attribute the full Paddle request cost to every combined path; never report only the final GLM stage as end-to-end time. Loading and warmup remain separate. Use two repeats and retain timeout, truncation and invalid-JSON attempts. Ambiguous references remain unscored. All preview fields still require human review because probabilities are uncalibrated, even when both outputs agree.

## Decision audit

The initial completed v1 run reveals optional-key omission and malformed JSON in six of eight certificate hint calls, and bare-number outputs in all six direct bank JSON calls. An independent exploratory v2 retains v1 records and verified original script snapshots, places OCR evidence before a final schema, and clarifies all-key and date/degree semantics. Both direct and hinted paths use that revised template. This is adaptive exploration on the same sample, not a held-out validation or a repair of v1 outputs.

The [schema diagnostic](../../implemented/testing/2026-09-30-schema-extraction-benchmark.md) partially overlaps in frozen references and scoring, but owns its original single-GLM experiment; it is not superseded. The [runtime note](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) continues to own production residency and supervised serial execution. The [task note](../../implemented/feature/2026-09-30-durable-document-tasks.md) retains production field mapping, admission and review constraints; this diagnostic does not add bank cards to the application. The automatic-layout, diagnostics and DDE workflow decisions remain independent. There is no existing proposed/rejected note for this fusion decision.

## Alternatives considered

- A commercial offline card SDK offers ready-made field outputs and may lower hardware demands. Its per-product Windows support, license and sample accuracy are unverified, and the user has not authorized procurement; it remains a research candidate.
- Domain-specific SER/RE offers explicit field labels without generative mapping. Public verified weights are not the requested complete certificate schema, and adapting them needs labelled training work which the user defers.
- Majority voting is simple with multiple independent candidates. Two models can agree on the same wrong value and cannot break a disagreement; this experiment keeps disagreements visible instead of silently voting.
- Sending Paddle text alone to a third general LLM allows semantic extraction. It adds another deployment before testing the existing GLM image extraction mode, so the combined path reuses GLM and the original image.

## Testing

- Seven meaningful CPU tests cover normalization, conflicting candidates, shared wrong consensus, unknown references, full paired time, bounded hint ordering and precision/coverage denominators.
- v1 and v2 each complete 56 formal calls, all EOS, with confirmed owned-process exit, matching frozen input hashes and stable repeated field values. JSON contract failures remain in the denominator; optional-key omission can invalidate a whole diagnostic prediction and is distinguished from recognition loss.
- v1 certificate direct GLM and merge both score 54/78 present-field instances. Agreement-only accepts 18/78, all correct in this small sample. Hints score 16/78 and have six of eight certificate contract failures. Direct bank schema has six of six format failures, not six proven digit-reading failures.
- v2 uses a revised final template for direct and hinted paths. Certificate direct GLM scores 38/78, merge 46/78 and hints 36/78. This remains worse than the original v1 direct template. Bank direct/hints each score 4/6; GLM/Paddle raw rules score 4/6 and 2/6 respectively. Confidence stays unavailable.
- The [v1 report](../../../../output/dual-extraction-20260930-v1/REPORT.md), [v2 report](../../../../output/dual-extraction-20260930-v2/REPORT.md) and [card research](../../../../output/card-model-research-20260930/REPORT.md) retain separate plotting data and limitations. Sleep/restart audits find no matching events/query errors but do not certify absence of all stalls.
- The [Paddle qualification](../architecture/2026-09-30-paddle-vl-16-upgrade.md) extends the diagnostic with pinned 1.6 weights; it does not replace these initial results or silently adopt fusion in production.

## Consequences

The four certificate images are an already inspected convenience sample and bank references are provisional. OCR hints can contaminate GLM with Paddle mistakes, and these runs do not establish a useful general improvement. Agreement-only loses most field coverage despite its small accepted subset being correct. Production does not adopt automatic fused truth or calibrated confidence. Single-resident measurements do not qualify production dual-resident memory or HR's unknown configuration. Model load and disk-cache state influence startup time and remain separate from recognition.

## Related verification

The [isolated current-pipeline acceptance](../testing/2026-10-08-current-pipeline-acceptance.md) verifies the repaired real API path with the same frozen references and a separate encrypted store. It retains the v1 historical medical timeout and distinguishes single-resident loading from inference; it does not replace these historical measurements or qualify production hardware.

The [current diploma refresh](2026-10-09-diploma-accuracy-refresh.md) measures the current application route, not this paired-model experiment. Its new interval-date reference and expanded scores are separate, with original paired references preserved.
