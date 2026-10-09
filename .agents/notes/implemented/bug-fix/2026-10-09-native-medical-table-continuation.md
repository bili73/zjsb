# Agent Note: Recover observed cross-page laboratory headers and expose missing result links

Status: implemented
Scope: backend/ocr_app/documents.py, backend/ocr_app/extraction.py, backend/ocr_app/review.py, backend/ocr_app/task_store.py, frontend/src, tests, scripts/replay_oct9_repairs.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user reports four detected abnormalities versus six review findings for Zhang's report and suspects height/weight fulfilled an early stop quota. Read-only audit of task a03c86a9-5813-41f5-9385-40f71ccd0efa revision 2 instead finds 67 structured measurements, four eligible abnormalities, six printed follow-up findings and zero pending regions. Neither missing urine measurement is in items. The six findings are BMI, gallbladder, kidneys, platelet distribution width, occult blood and protein; no height or weight is in this list. There is no declared-count early-stop branch in the processing loop.

PDF physical page 13 ends with the urine table header. Its last cell contains only risk (风险); physical page 14 begins with the remaining grade (等级), followed by 20 urine rows. Current recovery treats pages independently and cannot recover the previous header's data on the next page. The original page 14 clearly prints occult blood +3 and protein +1, both E3. The stored findings retain their diagnoses but have no linked result. Audit, original-header snapshots and rendered pages are preserved in [triage evidence](../../../../output/triage-20261009-v1/audit.json). This is a field/table recovery defect, not a new OCR accuracy measurement.

## Decision

Extend native table recovery with one bounded adjacent-page context for an observed split header: a qualified medical header at the prior page bottom ends in 风险, and the aligned next-page top header contains only 等级 in its last cell. Require compatible page sizes and matching observed column bounds, join the observed labels and reuse the same-page row recovery. Preserve actual next-page row/cell source boxes, stop at observed specimen/footer/next-table boundaries and reject ambiguous columns or non-consecutive ordinals. A blank/intervening page clears the context; unmatched/final headers retain their limitation. This is not generic inheritance for arbitrary headerless tables. Do not use a declared clinical count, reference answer or fixed page number to select rows. No new model is needed for this sample.

Retain report_summary.count_check as the comparison of the declared count with its own printed list. Separately display how many list entries have a reliable corresponding measurement and which still lack results. A six-row list match must not imply complete laboratory extraction. Keep height, weight and exact 小结 excluded from review/statistics; BMI remains eligible. Different sections' counts must not be forced equal: some abnormal measurements may not appear in the follow-up list. Resolve by source-backed association, not a count quota or a truncated loop.

Historical saved tasks are not automatically overwritten or marked completed. Qualify the parser on the untouched original and replay frozen evidence; users can rerun or apply an explicitly versioned correction. Original recognition and human edits remain recoverable.

## Decision audit

[Evidence-bound mapping](2026-09-30-evidence-bound-field-mapping.md) partly overlaps: same-page recovery, independent list count and evidence contracts remain, while adjacent continuation is new. [Medical review scope](2026-10-08-medical-review-scope.md) retains its exclusions. [HR profiles](../feature/2026-10-08-hr-document-field-profile.md) retain grade and diagnosis association. [Business Excel](../feature/2026-10-09-business-xlsx-layout.md) consumes these linked results. Related proposed/implemented/rejected themes were searched; none is wholly superseded or archived.

## Alternatives considered

- Match the printed six to six arbitrarily selected abnormal rows: easy to present, but mixes scopes and can conceal missing rows. Reject.
- Use more OCR for the whole report: may read images unsupported by native extraction, but the two missing values and their geometry already exist in this PDF. Repair native recovery first.
- Guess all columns from flattened text: simple and broad, but can shift result, unit and grade. Require the observed header's geometry and qualified continuation.
- Replace the list count with detected abnormal count: creates one number but destroys the report's independent declaration. Keep both scopes visible.

## Verified invariants

- On the original Zhang PDF, recover all 20 urine rows, including +3/+1 and E3, with valid page 14 sources; link all six follow-up rows and retain BMI. No height/weight/小结 appears as an eligible abnormality.
- Regression covers split headers, real continued rows, changed page width, unrelated following tables, footer termination, duplicate/missing ordinals and ambiguous columns. Failure preserves evidence and an explicit review issue.
- A list that declares six but lacks two measurement links explicitly shows 6 listed / 4 linked / 2 unresolved. No inference or review is stopped by matching a count.
- Existing report fixtures, review edits, filters and count semantics pass unchanged. Partial full-report coverage is not upgraded merely by matching one table.

## Verification

Six continuation regressions pass, including changed page width and rejection cases, alongside existing native-table tests. On the unchanged 22-page original PDF, [CPU replay](../../../../output/repairs-20261009-v1/replay/summary.json) reconstructs 20 urine rows on physical page 14 from the page 13 header, including 潜血 +3/E3 and 蛋白质 +1/E3. The result has 87 measurements, six eligible abnormalities and six reliably linked follow-up entries. Native decoding took 1.078 seconds and mapping 0.125 seconds in this replay. There are still 53 pending image OCR boxes: no new model call or full-report accuracy/coverage claim is made. Full backend regression is 447 passing tests. Independent synthetic [browser acceptance](../../../../output/repairs-20261009-v1/browser-4/summary.json) checks both six linked and four linked/two missing presentations.

## Consequences

Adjacent-page inheritance can attach unrelated rows if qualification is loose, so recovery is limited to the observed split-header geometry and qualified consecutive body. Mac and new hospital layouts remain unqualified. Original production records remain unchanged until a rerun or explicit versioned correction.

## Later measured-group summary policy

The [measured-group summary correction](../../implemented/bug-fix/2026-10-09-medical-measured-group-summaries.md) partially supersedes normal-summary eligibility: liver and source-backed A-grade measured rows can produce 未见异常 without a printed 小结. Closed numbered native catalogues distinguish report absence from missing recognition. Abnormal details, attribution, counts, manual priority, source binding, unavailable confidence, review and immutable history remain active. The older decision and measurements above retain their original rationale; no note is archived.
