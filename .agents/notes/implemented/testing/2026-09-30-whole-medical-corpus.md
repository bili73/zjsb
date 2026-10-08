# Agent Note: Separate native PDF evidence from model recognition across the medical folder

Status: implemented
Scope: scripts, tests, IMPLEMENTATION_PLAN.md, RUNTIME.md
Last-verified: 2026-10-08

## Problem

The user asks to include F:/dingding/附件_按类型_20260929/体检报告 in the Paddle v1 versus 1.6 assessment. This folder has three PDFs (22, 22 and 21 pages) and one 1080x3757 JPEG: 66 pages/images. Existing blood-page probes cover only selected results. Most PDF pages have native text, so treating all reports as pure OCR inputs misstates production work and attribution.

## Decision

The frozen corpus contains all four source hashes and encrypted copies, every page's existing decoder evidence, blank-page records and conservative raster regions. Native text/table evidence remains independent of OCR. Twelve table pages are explicitly forced OCR stress inputs, not production routing; the other 192 cases are automatically partitioned raster candidates. CSVs separate those modes and physical inference from logical reuse.

PDF table references come from source-layer cell topology with source hashes and are labelled native_pdf_reference, not human gold. Existing independently frozen visual blood references remain a distinct provisional subset. Ambiguous repeated labels are unscored, never arbitrarily overwritten. Input images and references are encrypted; public records omit file names, personal values and raw output.

Identical image bytes/task/preprocessing within each model run reuse one measured inference, while every logical region retains its own origin and scoring. Executed inference cost and reused logical regions are reported separately; this is diagnostic deduplication, not a production cache or production document latency. A single resident model and serial GPU channel are enforced. No native evidence is counted as model accuracy. Failures/abstentions remain visible, unknown reference accuracy stays null, and mapped rows do not establish report-wide coverage.

The offline report validates source/image/fixture/code/checkpoint hashes, request population, exact-byte reuse identity and null reused costs, owned model exits and recomputed field scoring. Public reports contain only sample IDs, field names and aggregate outcomes; encrypted private values never appear in console or plotting CSVs.

## Decision audit

The [Paddle qualification](../../implemented/architecture/2026-09-30-paddle-vl-16-upgrade.md) owns checkpoint/profile adoption and partially overlaps. The [OTSL adapter](../../implemented/bug-fix/2026-09-30-paddle-otsl-table-decoding.md) owns table-format behavior; the [durable-task note](../../implemented/feature/2026-09-30-durable-document-tasks.md) still owns production deadlines, region preparation and review. Prior schema, fusion and layout diagnostics remain separate datasets. This folder is not claimed to be a new held-out cohort because previous samples overlap it. No previous proposal/rejection owns a whole-folder/native-versus-forced-OCR comparison.

## Alternatives considered

- OCR every full PDF page gives a simple equal-image comparison. It spends time on native text and hides the production native-first boundary; forced table images are explicitly separate stress cases.
- Only blood-page tests provide strong existing references with low cost. They miss urine, chemistry, long photos, blank pages and raster routing, so this run inventories the whole folder.
- Counting every repeated logo inference makes timings closer to the current application. It wastes diagnostic GPU work; reusable duplicates retain logical origin, and deduplicated timings are never presented as current application performance.

## Testing

- The v2 run completes 408/408 logical requests, 164 physical inferences (82 per checkpoint), with 122 exact-byte logical reuses per checkpoint. All 66 inventory records and four source hashes validate; both owned processes confirm exit. The v1 directory is preparation-only, preserved before the driver protocol was extended and never counted as inference.
- Blood-result visual references score v1 72/72 and 1.6 66/72, with no missing and six new-version wrong values. Other native table references score consistency v1 51/95 (38 missing, six wrong), 1.6 64/95 (24 missing, seven wrong). These denominators are deliberately separate and are not whole-report accuracy.
- The native mapper yields 103 medical items elsewhere but misses all 72 known blood results. Reliable text exists on those pages; the current native row/column recovery and mapping remain unqualified.
- Physical termination counts are v1 74 EOS, seven 45-second generation timeouts and one repetition stop; 1.6 79 EOS, two generation timeouts and one repetition stop. Logical incomplete counts are 10/3 including repeated failed inputs. No failure is discarded or relabelled EOS.
- Unique-input mean request times are 6.743/4.042 seconds, including failures and many small repeated-asset inputs. Blood-page means are 24.411/21.762 seconds; total experiment wall time is 943.946 seconds. These are not application document latency. Single-model allocator peaks are 2.760/2.629 GiB, sampled inference RSS peaks 1.805/1.907 GiB; load/request resource scope is separate.
- The validation artifact passes all eleven integrity checks. System event query for the run window has no errors and no matching sleep/reboot events; this does not exclude other stalls. The previously completed 135 CPU regressions cover the production decoder/checkpoint changes; this reporting extension is validated against all frozen records. DDE verification is the delivery gate.
- [Report and plotting data](../../../../output/medical-corpus-20260930-v2/REPORT.md) retain native, forced OCR, automatic raster, accuracy-basis and physical/logical boundaries.

## Consequences

The whole-folder inventory reveals native-PDF omissions and automatic-region stalls that selected blood pages hide. The newer recognizer stops less often on this corpus and matches more native chemistry references, but has wrong blood values; no automatic default switch is justified. Native PDF extraction is not an infallible ground truth. One hospital's layouts and three PDFs cannot establish generalization; the long photo and many raster regions remain unlabelled. Exact-byte deduplication reduces measured inference work, so its elapsed time is not production report latency. Automatic partitioning can split semantic groups even when geometrically complete. Missing field mapping and full-report medical coverage remain unqualified; native table recovery, targeted OCR fallback, confidence calibration and medical grading remain future work.

## Related verification

The [isolated current-pipeline acceptance](2026-10-08-current-pipeline-acceptance.md) verifies the repaired real API path with the same frozen references and a separate encrypted store. Its v1 single-resident timeout remains evidence, separate from this offline corpus. [Bounded medical recognition](../bug-fix/2026-10-08-bounded-medical-recognition.md) subsequently implements Task-local EOS reuse in production and validates all three PDFs on Windows dual residency: 72/72 blood results, 6/6/2 scoped findings, 66 actual medical model calls and 97 cache hits. These new production measurements do not relabel the older offline deduplication timings, change frozen scores or establish whole-report/long-photo accuracy.
