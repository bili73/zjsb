# Agent Note: Extract the report's examination-project catalogue

Status: implemented
Scope: backend/ocr_app/extraction.py, backend/ocr_app/doc_profiles.py, backend/ocr_app/task_store.py, backend/ocr_app/review.py, backend/ocr_app/exporting.py, frontend, tests, scripts, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md
Last-verified: 2026-10-08

## Problem

The implemented [business Excel layout](2026-10-09-business-xlsx-layout.md) places this catalogue alongside personal information in a medical summary worksheet. The independent printed-project meaning and catalogue extraction remain unchanged.

The user removes report_no, report_date, package_name and institution from medical structured fields and asks for broad examination-project names from the project column below the report's 本次体检项目意义 title. Existing items are detailed measured results and must not be replaced or counted together with this catalogue. Native samples put the body table on pages18/19 and repeat the title in contents; chapter numbers differ between reports.

## Decision

exam_projects is an editable optional string Field containing ordered project names separated by the Chinese semicolon. Extraction preserves printed names such as 内科检查 and 心电图 without inventing a fixed department vocabulary. It accepts only uniquely identified 项目 and 临床意义 columns in a table within the stand-alone body-title scope. Contents entries, clinical-meaning prose and unrelated chapters cannot supply names; repeated reliable headers can continue across adjacent pages. Available table/cell sources remain in the Field's primary source plus optional sources. Missing or ambiguous layouts leave the field empty or explicitly incomplete, with no fabricated name or probability.

Remove the four keys from the catalogue/new extraction, authenticated historical structured projections and current review/export fields. Keep their printed labels as parsing boundaries where needed, rather than corrupting neighboring legacy values. Do not rewrite old encrypted results, original evidence, runs or benchmarks. Source text naturally still contains original printed metadata. Current fields/basic_info must agree and old absent exam_projects can be manually entered.

The frontend uses a multiline scalar-field editor and display with the new catalogue, validates optional source lists, and offers each project's source in a dropdown. Excel receives the new column and drops the four retired columns via the current profile. New-field missingness is optional and does not add a gate to the [required-fields-only export policy](../../implemented/simplification/2026-10-08-required-fields-only-export.md).

## Decision audit

The [HR field profile](../../implemented/feature/2026-10-08-hr-document-field-profile.md), [mapping](../../implemented/bug-fix/2026-09-30-evidence-bound-field-mapping.md), [review/export](../../implemented/feature/2026-10-08-human-review-and-xlsx-export.md), [frontend](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) and [presence-only export](../../implemented/simplification/2026-10-08-required-fields-only-export.md) remain partially active. This extends medical metadata/catalogue and the user's anomaly eligibility scope, while preserving classification facts, report-summary counts, model lifecycle and export policy. None is fully superseded or archived.

## Anthropometric exclusion

The user additionally excludes height and weight from abnormal projects while retaining BMI. Exact normalized 身高, 体重 and standalone combined 身高体重/身高\/体重/身高、体重 labels are measurement evidence but outside the user's anomaly/statistics scope. All-items/manual/XLSX views retain their original values, grades, diagnoses, sources and derived flags. The server-derived optional abnormal_exclusion_reason=HEIGHT_WEIGHT explains the exclusion rather than mislabelling it NORMAL or UNKNOWN. BMI/体重指数 and broader labels such as 身高体重血压 remain eligible; extraction never calculates a missing BMI. Shared backend classification, complete statistics and current historical projections enforce the exclusion before any response filter. Manual renaming recomputes eligibility; clients cannot edit the derived property. Incomplete stats stay null. Printed report-summary findings and declared counts remain intact.

The reported reappearance after save came from a resident process started before the field change, verified through its old11-key live catalogue. The local service is updated after passing regression checks and confirming no active tasks. Save followed by result read uses the current8-key profile; read projections never rewrite historical encrypted results.

## Alternatives considered

The approved [medical ledger template](../../implemented/feature/2026-10-09-medical-ledger-template.md) partially supersedes the medical primary profile and workbook: restore institution/report_date, keep the catalogue and add its independent read-only count. Height/weight remain outside anomaly/item-review scope and BMI stays eligible. The source/table catalogue rationale and earlier verification here remain active.

- Reusing detailed items is effortless and already source-linked, but mixes laboratory indicators with broad examinations and changes anomaly counts. Keep a separate catalogue field.
- A structured editable array gives per-project UI controls, but expands the shared scalar Field/review/export contract for a simple textual list. Reuse one string field while retaining multiple source records.
- Global matching of 项目 is short and catches many tables, but also matches laboratory results and contents. Bind extraction to a real titled section and reliable column identity.
- A fixed department whitelist creates tidy labels, but the actual reports contain mixed scopes including 身高体重血压 and 肝功五项. Keep the printed project names.
- Hiding the four fields only in the frontend is simple, but leaves obsolete required institution gates and Excel columns. Retire them throughout the current structured contract while preserving originals.
- Dropping height/weight rows entirely is short and follows the earlier 小结 guard, but loses valid measured data. Keep measurements with explicit derived exclusion and count only eligible rows.
- Clearing height/weight flags to NORMAL makes existing filters easy, but invents a clinical interpretation. Preserve report facts and expose the operational exclusion separately.
- Removing height/weight from the printed conclusion list could lower displayed counts, but would alter the document's independent declared-list scope and create false mismatches. Keep that evidence intact.

## Testing

The complete CPU regression passes419 backend tests in12.746s and57 frontend tests; typecheck/build pass. Ten new backend tests cover profiles, parsing boundaries, title/table/source scope, wrong/duplicate headers, duplicates/adjacent pages, immutable historical reads, manual entry/reload, retired-field rejection, XLSX columns, height/weight facts, exact exclusion/BMI eligibility, manual renaming, and stable statistics under filtering. Earlier failed attempts remain in the output directory; the final passing log is backend-tests-final-v2.txt.

The [native replay](../../../../output/medical-project-catalogue-20261008-v1/native-replay/summary.json) checks three unchanged PDFs against directly read native project cells:9/10/11 names and30 valid cell sources, on pages19/19/18. The third-party titles include 八 and 九, so fixed chapter/page assumptions are unsupported. Detection rows remain62/67/69 and report declared/observed lists remain6/6,6/6,2/2 with match versus the preserved subsection baseline. Each report retains2 excluded measurement rows and1 BMI row. The replay has0 model calls and154 pending graphic regions; these are native mapping/source observations rather than independently labelled accuracy or a complete OCR benchmark.

The isolated [browser acceptance](../../../../output/medical-project-catalogue-20261008-v1/browser-003/summary.json) verifies the current built UI's8 fields, multiline catalogue editor, individual project source dropdown/corrected preview, all-items versus anomaly filtering, actual save followed by result reload, and downloaded XLSX containing current columns and retained measurements. It has0 page errors/model calls; two earlier failed test-locator attempts remain preserved. All source/build hashes are recorded.

The [read-only live check](../../../../output/medical-project-catalogue-20261008-v1/live-service.json) verifies14 stored medical results with28 excluded measurement rows; result filters preserve complete-statistics values and original report summaries, encrypted blobs remain unchanged, and the live root serves the current build. Both resident models report ready. No production recognition/export or sample mutation is part of this check.

## Consequences

Unfamiliar chapter layouts, scanned pages or absent column structure may abstain. Native-text evidence does not mean all report graphics were recognized. The optional string list can be corrected manually but is not a controlled medical classification. Existing results gain the new extracted list after rerun; current projection removes retired fields immediately and may expose an empty new field for supplementation. No model, deployment or clinical-risk grading change is included.

Height/weight remain available to auditors without contaminating the requested anomaly scope. Complete stats now count eligible rows rather than every visible measurement, so clients must use the supplied stats and exclusion property instead of items.length or flag alone. The catalogue and independent report-follow-up list remain separate; this scope change cannot manufacture agreement with a printed declaration. Current medical required fields are name/gender/exam_date, and missing optional exam_projects does not block export.

The implemented [medical review-scope correction](../bug-fix/2026-10-08-medical-review-scope.md) extends exclusion into human-review targets and the editor, and adds SECTION_SUMMARY for old exact 小结 rows. The preceding419-test checkpoint qualifies anomaly/statistics exclusion only. The current default editor exposes eligible tests, while all-items/source/XLSX and original recognition issues retain the excluded evidence.
