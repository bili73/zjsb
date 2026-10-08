# Agent Note: Decode Paddle OTSL before medical column mapping

Status: implemented
Scope: backend/ocr_app/extraction.py, backend/ocr_app/table_format.py, tests, scripts, IMPLEMENTATION_PLAN.md, RUNTIME.md
Last-verified: 2026-09-30

## Problem

The serial Paddle v1/1.6 medical probe returns OTSL markers (<fcel>, <ecel>, <lcel>, <ucel>, <xcel>, <nl>) rather than HTML. The current medical extractor only enumerates HTML tables, so all twelve real model outputs produce zero items despite EOS. These scores measure a missing format adapter, not character recognition failure. The user asks whether rules are causing misses; this is a verified integration defect.

## Decision

The small standard-library OTSL-to-HTML decoder runs before existing medical column mapping. It follows official PaddleX token semantics, escapes cell text, preserves horizontal and vertical spans, and never uses field references to repair OCR. Raw model output remains in encrypted evidence/attempts. Non-OTSL text follows the existing path. Malformed or orphan spans retain a visible limitation and original evidence rather than inventing row ownership.

Frozen twelve old/new medical predictions are rescored in a separate directory with source prediction hashes and decoder code hashes. Original no-adapter scores and request times remain intact. Additional decode/scoring time is separate; the offline rescore is not new inference or whole-report coverage. The existing medical extractor uses this adapter in production.

## Decision audit

The [durable-task decision](../../implemented/feature/2026-09-30-durable-document-tasks.md) partially overlaps in medical parsing and retains scheduling, persistence and review ownership. The [Paddle qualification](../../implemented/architecture/2026-09-30-paddle-vl-16-upgrade.md) owns checkpoint/environment selection; table-format decoding is also needed by the original release and is not a reason to rewrite model benchmark history. The [whole-folder diagnostic](../testing/2026-09-30-whole-medical-corpus.md) extends evidence without claiming complete native-PDF field mapping. The schema/dual diagnostics retain separate field and prompt contracts. No previous note covers OTSL conversion.

## Alternatives considered

- Installing the complete PaddleX pipeline provides official postprocessing, layout and model orchestration. It adds a second scheduler and a much larger dependency boundary; the present defect needs only format decoding before the existing parser.
- Switching table tasks to plain OCR can make output easier to read. It discards explicit cell topology and does not address the original task's row/column requirements.
- Splitting tokens into text lines is short and can recover visible numbers. It loses merged-cell ownership, making value/reference association unsafe; convert the explicit grid instead.
- Official width-repair heuristics improve tolerance of ragged model grids. They can truncate trailing cells; this adapter pads only empty positions and rejects inconsistent spans without deleting recognized text.

## Testing

- Five CPU tests verify source-bound medical result/unit/reference/marker mapping with a merged header, two-dimensional spans, HTML escaping, ragged-row empty padding, rejection of orphan/nonrectangular spans, and unchanged HTML/plain-text handling. Null confidence and manual review remain enforced.
- The frozen 12-output rescore recovers 144/144 selected old-version field instances and 130/144 for 1.6; the original zero-item no-adapter scores remain visible. Decode/score costs average about 0.0045 seconds separately.
- A real 12-call matched-pixel run uses this production extractor during inference and reproduces the same field results, with all EOS and owned exits confirmed. Neither run qualifies units/ranges, whole reports or population accuracy.
- 135 backend CPU regressions pass. The real default dual-resident synthetic runtime probe also passes with reused PIDs and confirmed process-handle cleanup; no 16 GB qualification is inferred.

## Consequences

The adapter fixes a format integration loss without changing weights or repairing predicted digits. Correct topology does not establish correct digits, units, reference intervals or full document coverage. Model-generated merged grids may be inconsistent; conservative decoding can abstain. Existing column labels, missing abbreviations, native-PDF table recovery and narrative certificate mapping remain separate defects. No medical grading or Excel policy is added. Evidence and plotting data are in the [qualification report](../../../../output/paddle16-upgrade-20260930/REPORT.md).

The [field-mapping repair](../../implemented/bug-fix/2026-09-30-evidence-bound-field-mapping.md) covers the separately verified header-only native tables, decorative conclusion bullets, explicit LaTeX arrows and candidate-boundary defects. These repairs are implemented separately; they are not performed by the OTSL adapter.
