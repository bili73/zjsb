# Agent Note: Evaluate automatic document regions with frozen OCR references

Status: implemented
Scope: scripts/run_auto_layout.py, scripts/test_auto_layout.py, scripts/run_two_model_retest.py, scripts/export_auto_layout.py, scripts/test_auto_layout_export.py
Last-verified: 2026-09-29

## Problem

Manual crops improved PaddleOCR-VL completeness on difficult documents, but those results do not establish that automatic partitioning works. HR computers may have only 16 GB RAM, and their GPU configuration is unknown. The experiment must separate layout quality, recognition quality and resource cost.

## Decision

The diagnostic benchmark uses PP-DocLayoutV3 on CPU to detect regions in full-resolution source images. It preserves detected tables as separate regions and combines nearby text without crossing tables. Coordinates, omitted image regions and visual overlays are saved. Original PaddleOCR-VL-0.9B and GLM-OCR run serially on identical crops, with only one recognition model resident for this controlled experiment.

Seven previously difficult pages and two controls are compared against existing whole-page and manual-crop results. Reference fields are frozen before inference; missing and wrong fields stay in the denominator, and layout, loading and OCR request time are separate. No per-sample manual coordinate or rotation corrections guide the automatic variant. Field scoring reviews current outputs and binds reviews to file hashes.

The first prototype and three geometry tests predate DDE initialization in this session. The proposal was recorded before OCR evaluation; the completed experiment is stored in output/auto-layout-20260929-v1. This implemented state describes the offline experiment, not a production routing, retry, merging or application runtime implementation.

## Decision audit

No proposed, implemented or rejected notes existed when this first note was created. Historical benchmark reports remain evidence, not retroactively created decisions. The later [dual-model runtime decision](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) partially overlaps in resource policy but changes production residency, while this benchmark deliberately isolates single-resident measurements. Neither note fully supersedes the other.

The [schema extraction diagnostic](2026-09-30-schema-extraction-benchmark.md) shares serial benchmark conventions but evaluates field mapping on identical images rather than crop quality; neither experiment supersedes the other.

## Alternatives considered

- Manual crops give precise boundaries and have measured benefits, but require sample-specific intervention. They remain a comparison, not the automatic implementation.
- Whole-page recognition has the simplest pipeline and lowest layout overhead, but prior dense pages contain truncation and repetition. It remains the baseline and a necessary production option for simple documents.
- Keeping both recognition models resident better represents the latest proposed application experience, but confounds this isolated model-quality/resource comparison. The benchmark runs serially with one resident model; dual-resident startup and inference require a separate acceptance run.

## Consequences

Automatic layout produces 91 regions across nine pages. Both models return nonempty EOS outputs for every formal region, with no token-limit or repetition stop. GLM retains 125/130 fields; Paddle retains 122/130. On the seven difficult pages, scores are 115/118 and 112/118. These are selected-field results against provisional visual references, not full-document or representative production accuracy.

The two normal controls fall from 12/12 to 10/12 for both models because the detector omits certificate body text. A screenshot also loses school and major regions; table-internal units are redundantly detected. Better region recognition does not prove complete source coverage. Simple-page whole-image routing, coverage checks, deduplication and bounded missing-region recovery therefore remain production design requirements. Such changes must use a new run directory and include normal controls; the existing results must not be repaired by substituting older correct outputs.

Nine-page layout/crop preparation costs 9.31 seconds, with 2.50 seconds of separate layout model loading. Formal OCR requests total 185.69 seconds for GLM and 105.21 seconds for Paddle, excluding model load, warmup and layout. Manual preparation time is unmeasured and represented as null. The benchmark does not implement or validate the SPEC whole-Task 180-second budget.

Layout is CPU-only and OCR sessions do not overlap. Peak single-process RSS and PyTorch memory are measured in their specific scopes, not asserted as hardware requirements. Both-model residency, CPU-only OCR and the 16 GB HR PC remain untested. Fine-tuning remains deferred.

## Verification

- Three geometry invariants pass with scripts/test_auto_layout.py.
- Two scoring tests pass with scripts/test_auto_layout_export.py, including failed-parent denominator/time retention and no fabricated accuracy for unscored input.
- scripts/export_auto_layout.py verifies frozen reference, input and current output hashes, all parent reviews, and serial session ordering. All 182 formal outputs are reviewed; two warmups are excluded from scores and request totals.
- The bounded Windows System log audit has no matching sleep/resume/restart events and no query errors during the OCR window; see output/auto-layout-20260929-v1/timing-audit.json.
- output/auto-layout-20260929-v1/REPORT.md and data/ preserve observations, timing scopes and plotting rules. Baselines come from output/two-model-retest-20260929-152421; they were not rerun in this iteration.
- DDE verification and index checks run after note lifecycle and link updates.
