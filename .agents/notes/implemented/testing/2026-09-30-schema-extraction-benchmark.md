# Agent Note: Compare evidence-bound rules with GLM schema extraction

Status: implemented
Scope: scripts, tests, IMPLEMENTATION_PLAN.md
Last-verified: 2026-09-30

## Problem

The current application recognizes certificate text but loses fields at the rule mapping step. The user approves an isolated comparison of the unchanged OCR-plus-rules baseline with the already-installed GLM-OCR image information-extraction mode. Adding a third resident language model would increase deployment requirements before establishing whether it is necessary.

## Decision

The diagnostic freezes source images, SPEC field templates and provisional Agent visual references before model inference. Identical inputs run through text recognition plus the unchanged extractor and explicit English-key and Chinese-field JSON templates. Only GLM is resident, and GPU calls are serial. Loading, warmup, recognition and field parsing costs remain separate. Failed, truncated and invalid-JSON measurements stay in the denominator. References, source images and predictions are encrypted using the existing local Storage mechanism; shareable CSVs contain IDs, field keys and correctness indicators only.

Measurements include correct present-field recall, missed and wrong values, absent-field false positives, schema validity, request time and sampled CPU/GPU memory. Required-field results use SPEC definitions. Ambiguous/unreadable references are excluded with explicit counts, not treated as absent. This is a small diagnostic sample, not population accuracy, medical whole-report coverage or a 16 GB hardware qualification. Application extraction behavior is unchanged. The Chinese diagnostic calls degree_category a degree level because its SPEC label says category but its enum is bachelor/master/doctor; no production contract is changed.

## Decision audit

The [serial dual-model diagnostic](2026-09-30-dual-certificate-extraction.md) reuses this frozen reference subset to evaluate fusion while retaining these single-model results and their distinct full/required-only denominators.

The [durable task note](../../implemented/feature/2026-09-30-durable-document-tasks.md) partially overlaps in field extraction but retains ownership of the production pipeline. The [automatic layout experiment](../../implemented/testing/2026-09-29-automatic-layout-evaluation.md) partially overlaps in benchmark conventions; its crop comparison is not superseded. The [runtime note](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) retains production dual residency while this accuracy experiment remains single-resident. DDE tooling and local diagnostics are unrelated decisions. No prior proposed or rejected semantic extraction note exists.

## Alternatives considered

- Expanding narrative regular expressions is inexpensive and deterministic for known wording. It does not test generalization to different wording and repeats the user's previous maintenance problem; it remains the frozen baseline rather than the proposed extraction route.
- A separate general language model can interpret OCR text without rerendering. Its additional weights and inference costs are not justified before testing the existing GLM image extraction capability; no third model is installed.
- Replacing production extraction immediately would make the experiment directly usable. It risks silently introducing incorrect dates and unsupported output contracts, so adoption waits for measured accuracy and evidence validation.

## Testing

- Input, reference and prompt hashes are frozen and verified; paired paths use identical image hashes.
- 121 CPU tests pass, including six diagnostic tests for SPEC consistency, JSON types/duplicate keys, date precision, failed denominators and unmeasured memory remaining null.
- The full-field run has seven inputs, 53 known-present fields, 12 known absences and eight ambiguous fields. Two repetitions per path produce 42 formal calls. The English JSON path retains 76/106 present-field instances, versus 44/106 for text plus rules; wrong values increase from 4/106 to 22/106, and JSON adds 10/24 absent-field false positives.
- Chinese full-field output has eight of 14 contract failures; these remain visible rather than being repaired silently. A separate one-repeat required-only compact-prompt diagnostic scores 25/31 English and 24/31 Chinese, versus 19/31 for the baseline. Its reduced denominator is never pooled with the full-field run.
- v1 initially inherits a wrong baseline major as reference. It is marked invalid_reference and preserved. v2 corrects the reference against the original image before rerunning all paths. References are provisional and not independently double-labelled.
- Both measured runs have only EOS model outputs, no token-limit or timeout, and confirmed owned-process exit. System sleep/resume/restart audits have no matching events or query errors in their windows; this does not certify absence of all stalls.
- The [full-field report](../../../../output/schema-extraction-20260930-v2/REPORT.md) and [required-only report](../../../../output/schema-extraction-20260930-required-v3/REPORT.md) retain per-request and per-field plotting CSVs, encrypted predictions, loading/warmups and resource scopes. Unmeasured native-page RAM stays null.

## Consequences

GLM schema extraction improves field recall in this diagnostic but creates false values and guesses absent fields, so it is not adopted as automatic truth. JSON syntax does not prove correctness. Reusing weights avoids a third resident model but adds inference work and temporary memory; running OCR and semantic extraction together requires adding their costs. Native PDF page diagnostics evaluate current block-to-field mapping, not replacement of reliable PDF text or report-wide merging. The sample is selected, includes only one degree certificate and uses provisional references, so it does not calibrate confidence.

The user clarifies medical recognition as personal information, table-title categories and individual result rows with original abnormal markers. The future Excel grading toolkit and export remarks are recorded in IMPLEMENTATION_PLAN.md but are not parsed or applied. Report coverage, clinical grading, review/export implementation, production prompt routing and HR hardware qualification remain separate work.
