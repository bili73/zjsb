# Agent Note: Apply the medical exclusions to human review

Status: implemented
Scope: backend/ocr_app/extraction.py, backend/ocr_app/task_store.py, backend/ocr_app/review.py, frontend, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md
Last-verified: 2026-10-08

## Problem

The implemented [native medical continuation](2026-10-09-native-medical-table-continuation.md) addresses missing urine measurements and clearer list/result association. It retains this decision's fixed height/weight/小结 exclusions and BMI eligibility; it does not force laboratory counts to equal a printed follow-up declaration.

The user corrects the review scope: height, weight and exact 小结 rows must not interfere with review. The preceding catalogue change excluded height/weight from anomaly/statistical views, but review._targets, frontend collectIssues and the editor still enumerate every medical item. Preserved missing-grade/diagnosis issues on those measurements can therefore keep a review pending. Old encrypted results can also contain 小结 rows despite the new extraction guard.

## Decision

The same server-derived exact-name eligibility governs abnormal/statistical and medical item review scopes. abnormal_exclusion_reason includes SECTION_SUMMARY for exact 小结 (whitespace/trailing colon normalization only); HEIGHT_WEIGHT covers standalone height/weight rows. BMI and legitimate longer names remain eligible. Excluded rows retain original measurements, classification facts, source and recognition issues for evidence, but expose need_review=false and do not contribute review targets/blockers. They are not recorded as manually accepted and their issues are not deleted to simulate completion.

The review editor and current issue/automatic-acceptance list use eligible medical items. Source controls use the same filtered item order rather than the full items index. All-items display and XLSX retain measurements/history; newly extracted exact 小结 remains outside item extraction. Review eligibility is a fixed business rule, independent of a user toggle or the currently visible search results. Ordinary item problems, mandatory personal fields, report-summary conflicts and full-page coverage issues remain real review blockers. Save creates the existing versioned human revision; reads do not auto-complete stored tasks or rewrite history.

## Decision audit

The [catalogue/anomaly scope](../../implemented/feature/2026-10-08-medical-project-catalogue.md), [HR field profile](../../implemented/feature/2026-10-08-hr-document-field-profile.md), [human review](../../implemented/feature/2026-10-08-human-review-and-xlsx-export.md) and [frontend](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) partially overlap. This corrects their medical item review scope; fields, source evidence, versioning, report-declared list, model lifecycle and presence-only export remain active. None is fully superseded or archived.

## Alternatives considered

The approved [medical ledger template](../../implemented/feature/2026-10-09-medical-ledger-template.md) records height/weight as editable ledger metadata while preserving their medical-item exclusion. Small conclusions can support their group but never re-enter item/anomaly counts. Source fields and template format change separately; this item's review eligibility remains fixed.

- Exclude all non-abnormal items: this reduces work further, but the user named height/weight/小结 only and missing or uncertain actual tests can contain missed anomalies. Keep other real item issues reviewable.
- Review the current visual filter only: this is easy to implement, but changes completion when the user searches or switches tabs and can hide unresolved BMI issues. Use a stable server-side business exclusion.
- Delete excluded rows/issues from old results: this removes noise everywhere, but destroys original evidence and audit history. Preserve them with explicit exclusion and immutable read projection.
- Only hide editor rows: this fixes visual clutter, but backend blockers still keep the task pending. Apply eligibility in both layers.

## Testing

All424 backend tests pass in12.978s, including5 new targeted regressions. They reproduce excluded MISSING/CONFLICT blockers, prove an otherwise resolved legacy task completes on save without accepting/deleting those issues, preserve source/value/history/IDs, retain BMI/longer-name and incomplete-page blockers, and verify manual renaming re-enters review scope and derived-property edits remain rejected. The initial5 failing tests remain in [verification output](../../../../output/medical-review-scope-20261008-v1/before-fix.txt). All58 frontend tests and typechecked build pass, including exact automatic-acceptance scope and malformed reason rejection.

The isolated [headless Edge acceptance](../../../../output/medical-review-scope-20261008-v1/browser-002/summary.json) passes with0 page errors and0 FakeRuntime/model calls. Its old-result seed retains noisy height/weight/小结 records, while the editor exposes only the real BMI row. A deliberately different BMI source box verifies filtered-source identity, actual save produces COMPLETED, excluded recognition issues remain present/unaccepted, and downloaded Excel retains raw rows plus exclusion reasons. Browser-001 preserves a test failure from assuming the previous visible issue-list UI; the current authorized automatic-confirmation request is validated instead. Source/build hashes stay unchanged during acceptance.

The updated idle local service's [read-only live qualification](../../../../output/medical-review-scope-20261008-v1/live-service.json) checks15 saved medical results.72 excluded measurements/summary rows have no review blockers;91 original recognition issues and all original measured values, encrypted blobs and report summaries remain unchanged. Responses retain8 current basic fields and filter-invariant stats. Both models report ready and the root serves the current build. No production recognition/export request is used for this qualification.

## Consequences

The exclusion is operational, not a statement that height/weight or original subsection summaries are medically normal. Authentic printed report-summary entries remain independent evidence and are not erased to force a declared count match. Unrecognized pages and unresolved eligible tests can still require review. Unsupported names do not get a guessed exclusion.

Current and historical raw rows are available without causing redundant review work. Clients must treat abnormal_exclusion_reason as the eligibility signal: preserved excluded review_issues are evidence, not pending human blockers. Task status changes only through normal versioned save, so an existing NEED_REVIEW task is not silently completed by reading it. The default editor hides excluded rows; backend item correction remains available and recalculates scope on renamed items. Export eligibility remains required-value presence.
