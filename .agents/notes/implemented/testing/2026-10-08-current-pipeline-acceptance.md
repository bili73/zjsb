# Agent Note: Verify the repaired pipeline through an isolated real API run

Status: implemented
Scope: scripts, tests, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-08

## Problem

The user resumes implementation after the field-mapping repair. Its frozen-output replay proves mapping changes, not the actual upload/worker/model route. The old real API probe predates the repair and records populated fields rather than labelled correctness. Current source hashes still match the delivered mapping code.

The three medical PDFs still plan 50/53/51 OCR regions, including exact repeated inputs. More importantly, the old report-004 probe spends 158.781 seconds on two attempts for a large page-6 image, versus 10.466 seconds for 26 small regions. The repeated-image hypothesis does not explain the main observed timeout. The runtime's production Paddle is still v1, with 1.6 only installed as an experimental candidate.

The existing launcher-based probe uses `.runtime/data`. Its normal startup invokes seven-day retention, which would alter historical business artifacts now that the earlier run is older than seven days. A fresh output folder alone does not isolate the database or queue.

## Decision

The already approved real-file acceptance uses a probe that starts the existing API, Business and RuntimeClient components with a new encrypted data root. A supervised child serves loopback HTTP, and its parent owns the existing GPU byte lock. Model work remains serial. The original v1 uses single residency; the [bounded-medical extension](../bug-fix/2026-10-08-bounded-medical-recognition.md) adds explicit dual-mode qualification in a new v2 directory. The probe does not modify production code, saved preferences, or old business storage.

Both runs use two synthetic inputs (native PDF and its image) and all four frozen certificate images. The v1 baseline includes one whole report-004 PDF; v2 explicitly selects all three frozen medical PDFs. Encrypted references are reused only after source/protocol hashes pass. The scorer reads the same encrypted result published by the worker; default HTTP masks are not mistaken for OCR errors. Per-field outcomes distinguish present, absent and uncertain references; failures and conflicts remain in their original denominators. Population is never called accuracy.

Medical verification separately checks the blood-result subset, source resolution, explicitly scoped follow-up list and retained pages/pending regions. Counts are post-extraction assertions, never inputs to inference. The existing 180-second active budget and token settings remain unchanged. A timeout ends that run; the probe retains its partial result and does not silently restart a failed runtime to finish the dataset.

New anonymous CSVs record wall time, model attempts, inference/total duration, termination and tokens, field outcomes, required misses and count checks. Inputs, references, page images and result bodies remain encrypted. Reports and diagnostic exports omit document text, names, original filenames, keys and raw exceptions. Finally close the supervised tree and verify remembered process handles.

## Decision audit

The [durable tasks decision](../../implemented/feature/2026-09-30-durable-document-tasks.md) owns the processing and privacy boundaries; it partially overlaps, and this probe reuses them without changing retention. The [mapping repair](../../implemented/bug-fix/2026-09-30-evidence-bound-field-mapping.md) retains the CPU replay and abstention semantics. The [whole-medical corpus](../../implemented/testing/2026-09-30-whole-medical-corpus.md) and [certificate diagnostic](../../implemented/testing/2026-09-30-dual-certificate-extraction.md) own frozen references, overlapping convenience samples and serial inference rules. No note is superseded or archived.

## Alternatives considered

- The existing launcher probe most directly tests startup and already supervises exits. Its fixed production data root also processes old queued work and runs retention; use component-level real HTTP for this controlled run and label launcher/browser startup as a separate earlier acceptance surface.
- Replaying stored OCR again is quick and repeatable. It cannot exercise current decoding, scaling, model routing, request termination or source registration; retain the replay as a baseline and perform fresh actual inference here.
- Increasing timeout or changing tokens before measuring could complete more material. It confounds the mapping change with scheduling/model changes; establish the current baseline first.
- Dual residency reflects the configured interactive default. It confounds model-quality measurements with simultaneous memory residency and is unnecessary for the original baseline's serial calls; v1 therefore uses the supported single-resident mode and makes no new HR-hardware claim. The separately approved bounded-medical follow-up deliberately measures the production dual default, without rewriting that baseline choice.

## Testing

The isolated real run executes all seven cases in `output/current-pipeline-acceptance-20261008-v1`. The infrastructure, current publication identity, encryption and owned-process shutdown checks pass; document acceptance is partial. The native synthetic PDF has zero model attempts and both synthetic inputs score 7/7. The four real certificates retain all 39 present, 4 absent and 6 uncertain references: 37/39 correct, one missing award_date and one wrong school_name. Four runtime required values remain absent, including three reference-uncertain graduate_date fields. Published sources resolve and confidence remains unavailable.

The whole report times out at 181.625 seconds but retains 21 pages. Its frozen blood subset scores 24/24 with valid row sources; the exact follow-up heading declares and yields two findings on page 8, independent of laboratory abnormal counts. OCR coverage remains incomplete: 20 recognized, one incomplete and 30 pending regions. Whole-report and personal-information accuracy are not measured.

Current diagnostics identify a 55.735-second Paddle load/warmup within the single-resident task budget, followed by page-7 token_limit at 4096 tokens in 84.000 seconds and a 19.171-second retry timeout. The earlier page-6 hotspot finishes in 4.016 seconds here; the report preserves both observations rather than attributing the current failure to the old region.

Nine targeted CPU tests and 208 complete backend tests pass; 24 frontend tests and typecheck/build pass. All 12 observed owned handles are signaled. The original `.runtime/data` tree (52 files, 31,188,405 bytes) has identical before/after hashes. Frozen sources and protocol code hashes match after the run. Reports and chart CSVs remain anonymous; private snapshots stay encrypted. The test code, production code, prior outputs and references are distinct artifacts.

The separate [v2 run](../../../../output/current-pipeline-acceptance-20261008-v2/summary.json) completes 9/9 cases after [bounded medical recognition](../bug-fix/2026-10-08-bounded-medical-recognition.md), with 225 backend and 24 frontend tests plus typecheck/build passing. Windows dual startup is 156.000 seconds; the three PDFs finish at 120.250/147.000/150.625 seconds. All 154 medical OCR regions finish, while 66 physical calls and 97 cache hits remain distinct. Eight time_limit and one repetition_stop attempts remain visible; all nine GLM fallbacks end at EOS. Blood results are 72/72 and scoped lists retain 6/6/2. Four certificate controls retain exactly the v1 49 outcomes (37/39 present correct, 4 correct absences, 6 uncertain); no denominator drift or regression is hidden. Published identity, source resolution, encrypted-snapshot scoring and unchanged provenance are independently checked. The six public CSV/JSON files pass an in-memory sensitive-value/material-text/API-key scan.

## Consequences

The references are provisional, overlapping convenience samples and not independently double-reviewed. Neither seven v1 tasks nor nine v2 tasks establish throughput or held-out accuracy. V1 single residency includes switch costs in task wall time; v2 dual startup is reported separately and is not interchangeable with cached synthetic startup timing. The large-image failure remains historical measurement rather than permission to hide coverage. V2 completes processing, but full medical content is not fully labelled: NEED_REVIEW and null medical stats remain. The probe itself does not implement review editing/export, qualify Mac/16 GB machines or add a model; the separately documented bounded-medical change owns the new scheduling behavior.
