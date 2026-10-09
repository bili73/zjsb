# Agent Note: Extract and export the supplied medical ledger fields

Status: implemented
Scope: backend/ocr_app/doc_profiles.py, backend/ocr_app/extraction.py, backend/ocr_app/medical_ledger.py, backend/ocr_app/review.py, backend/ocr_app/task_store.py, backend/ocr_app/exporting.py, frontend/src, tests, scripts/replay_medical_ledger.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, IMPLEMENTATION_PLAN.md, ARCHITECTURE.md, RUNTIME.md
Last-verified: 2026-10-09

## Problem

The user supplies 入职体检审核记录台账模板.xlsx and asks recognition to follow its headers. Its 审核记录台账 sheet has eighteen columns: 序号, 姓名, 性别, 年龄, 体检日期, 体检机构, 报告日期, 身高, 体重, 血压, 血常规, 尿常规, 心电图, DR影像, 腹部彩超, 肝功五项（生化检测）, 体检项目数量, 异常指标. The second row contains six illustrative 正常 cells, not recognition evidence. Workbook SHA256 is de7c1fe274aefffd90a220b754c3030da25ccf5d2c1f85cf2a8c40ba22c5764f. Trim trailing header whitespace only; never load a Windows F: path at runtime.

The supplied Word reference has obsolete column numbers and automatic tier/hiring instructions. The user explicitly says it is only a loose reference and their instructions prevail. Their earlier human-only employment judgment remains active. Native replay already contains measured height/weight, source-backed project names and abnormalities, but item.category is empty, so grouped ledger cells need real section/table attribution rather than renaming existing fields.

## Decision

The user approves the field/extraction/review/export plan and explicitly defines the project count as the count of the body 本次体检项目意义 catalogue. Keep that editable catalogue as supporting evidence. Derive a read-only integer exam_project_count from its distinct ordered entries; repeated printed tables do not count twice, a missing catalogue is null rather than zero, and legitimate combined project names remain one entry. Detailed indicator counts and the printed follow-up declaration remain separate.

Medical structured fields are name, gender, age, exam_date, institution, report_date, height, weight, blood_pressure, blood_routine, urine_routine, ecg, dr_imaging, abdominal_ultrasound, liver_function, exam_project_count and auxiliary exam_projects. Restore institution/report_date, add measurements and six editable group summaries, and retire marital_status/phone/work_unit from the primary profile while retaining their source labels as parsing boundaries and all historical/raw evidence. Keep name/gender/exam_date as the only required fields. Unknown or ambiguous values stay null with source/review information; an optional missing value does not change export eligibility.

Bind groups to observed clinical section/table headings, explicit item names and source geometry. Never use contents entries, health-education prose, similar organ names alone or a follow-up suggested test as proof of the measured group. Preserve original project names. Exact 小结 can supply a group's printed conclusion but is never a separate measured project or anomaly. Populate an abnormal group from its source-backed abnormal measurements/diagnoses; an explicitly printed normal conclusion can supply a normal cell, but absence of detected anomalies cannot imply normal. Conflicting evidence remains reviewable. Height/weight keep the existing anomaly/count/item-review exclusion, and BMI remains eligible.

Use existing versioned manual fields/items and source controls. Refresh automatic derived count/summaries after relevant corrections, preserve explicit manually supplied group values and their absence reasons, and never overwrite human corrections with an old recognition run. Historical reads project the current profile without rewriting encrypted results; previously absent new values are editable blanks unless preserved source data proves a value. Count edits must target the catalogue, not the derived integer.

Medical export is the eighteen-column 审核记录台账, one source report per row, sequence numbers assigned in export order. The final abnormal cell contains original eligible names, results/units and diagnoses, using saved item/finding associations without duplicate linked entries; unlinked findings clearly say their measured result is unavailable. No default normal values, automatic company tier, employment opinion or extra technical columns are added. A medical-only export has one sheet; mixed exports retain other document-type worksheets. Preserve saved snapshot/version checks, all-or-nothing selection, required-value-only gates, literal string/formula safety and explicit cell-capacity failure. Long text wraps within the same row.

## Decision audit

- [Medical catalogue](../../implemented/feature/2026-10-08-medical-project-catalogue.md): partial overlap. Keep titled catalogue/source rules and anomaly exclusions; restore institution/report_date and add an independent derived count.
- [HR profile](../../implemented/feature/2026-10-08-hr-document-field-profile.md): partial overlap. Keep personal-info section priority, literal hospital grades, diagnosis linkage and diploma rules; the medical primary profile now follows the template.
- [Medical review scope](../../implemented/bug-fix/2026-10-08-medical-review-scope.md): partial overlap. Keep height/weight/小结 outside item review; new measured metadata can be supplemented through regular fields.
- [Business workbook](../../implemented/feature/2026-10-09-business-xlsx-layout.md): partial overlap. Replace only medical two-sheet/default opinion output; preserve other documents, saved corrections and safe serialization.
- [Presence-only export](../../implemented/simplification/2026-10-08-required-fields-only-export.md): unchanged eligibility, version and whole-selection semantics.
- [Rejected automatic threshold review](../../rejected/feature/2026-10-09-medical-threshold-review.md): retain human-only judgment; the temporary manual-opinion column is absent from this exact template.
- Existing runtime/queue/Mac proposals do not change. No decision is wholly absorbed or archived; scope and topic queries precede this proposal.

## Alternatives considered

- Reuse the current eight-field/two-sheet workbook: already verified and least change, but lacks most supplied headers and cannot populate the six groups.
- Execute the Word reference literally: specifies a ready workflow, but column numbers contradict the actual workbook and automatic hiring contradicts the user's human-only choice.
- Treat each laboratory indicator as a project: those rows are readily available, but the user explicitly defines count through the project-meaning catalogue.
- Copy template defaults or infer normal from no abnormal rows: yields complete-looking output, but confuses examples or incomplete recognition with report evidence.
- Put fixed hospital page numbers or filenames into mapping: short for one sample, but the existing samples move sections/pages. Use titles, table identity and source geometry.
- Retain a second abnormal sheet by default: easier to reuse the previous exporter, but repeats content outside the approved one-row ledger. Retain full evidence/details in the application.

## Verification

1. Exact eighteen normalized headers, one report/row, no copied normal defaults, safe +3/+1 strings and no formula execution; other material types remain compatible.
2. Catalogue count follows 本次体检项目意义, preserves combined names and duplicate handling, updates after manual catalogue correction, and stays null if unavailable.
3. Reliable group attribution and explicit conclusions/abnormal values have real page/region sources; missing/conflicting/partial evidence abstains instead of inventing normal values.
4. Height/weight are recorded without re-entering anomaly or item-review counts; BMI and missing urine abnormalities remain eligible, and printed follow-up counts remain independent.
5. Save/reload/export honor manual fields and current result version; historical source blobs stay unchanged; all newly added values remain optional.
6. The full backend regression passes 461 tests in 109.580 seconds; the frontend passes 65 tests, typecheck and production build. Isolated Edge browser acceptance passes five checks covering the seventeen fields, page-nine source preview, live catalogue count, saved/reloaded corrections and Cookie/CSRF-protected Excel download. The downloaded workbook is reopened and checked against the eighteen-column contract. There are zero page errors, real model calls or production writes in that acceptance.

Evidence is retained in output/medical-ledger-20261009-v1/. The final native PDF replay gives catalogue counts 9/10/11 and eligible abnormal counts 7/6/2; 张欢乐 includes 潜血 +3 and 蛋白质 +1. The native replay performs no model inference and leaves 154 image regions pending, so it does not establish whole-OCR accuracy or Mac performance. Source hashes remain unchanged. Exact exported XLSX cells, explicit strings, styles, wrapped rows and rendered previews are checked. Missing report dates and groups without an explicit conclusion or abnormal measurement stay blank.

Earlier red backend runs and browser attempts are retained. The browser harness fixes its response wait, ambiguous input/image selectors and mistaken Task-versus-TaskResult assertion; no application behavior is changed to satisfy those harness failures.

The final browser-5 acceptance also checks actual page-nine image decoding and its refreshed result_revision after saving. The qualified build is activated on the idle Windows loopback service as 1.16.0 after a consistent SQLite backup and full old process-tree exit. Both models are ready. All four served frontend files match the qualified build; the forty-nine stored tasks' encrypted fields, the one existing account and data-key files retain their prior hashes. No production recognition is performed. Runtime evidence and source replay limitations remain separately recorded in the release report.

## Consequences

Unfamiliar or graphic-only report sections can lack reliable group attribution. Multiple report/exam dates or repeated measurements can genuinely conflict and require manual choice. A single abnormal cell can be long; retain the existing explicit Excel capacity limit rather than truncating it. Read-only derivations must not overwrite human values or mutate historical encrypted data.

The user gets one template-compatible row per report and a clear independent catalogue count. Additional optional fields increase manual review surface; conservative blank cells expose missing evidence rather than creating plausible normal results. Existing task/authentication/model queue behavior and raw historical evidence remain in their established ownership boundaries.

The separately verified [cover-institution refinement](../bug-fix/2026-10-09-medical-cover-institution.md) narrows only the generic page-one fallback to the user-specified right-side information row and printed full branch. It retains optional fields, original source codes, manual corrections and the ledger decisions; it does not replace this note as a whole.


## Current refinement

The [biochemical summary and export refinement](../bug-fix/2026-10-09-biochemistry-ledger-export.md) adds source-backed measured liver results only when no abnormal summary or explicit conclusion exists, replaces the abnormal-entry separator with newlines and preserves manual overrides. The earlier1.16.0 measurements above remain frozen; other missing groups still abstain.


## Current refinement

For liver_function only, the [abnormal-only correction](../bug-fix/2026-10-09-liver-abnormal-only.md) supersedes automatic normal-conclusion filling. Other group conclusions, human values, template columns and independent counts remain active.

## Normal-summary refinement

The user-authorized [normal-summary fallback](../../implemented/bug-fix/2026-10-09-medical-normal-summary-fallback.md) partially replaces the original printed-conclusion-only normal rule above for the five non-liver groups. Source-backed measured rows all classified NORMAL, with nonempty results and no conflicts, can supply 未见异常 without a printed 小结. Missing/unknown groups still abstain; manual priority, unavailable confidence, original sources, independent counts and liver abnormal-only behavior remain active. The earlier rationale and release measurements above remain historical evidence.

## Later measured-group summary policy

The [measured-group summary correction](../../implemented/bug-fix/2026-10-09-medical-measured-group-summaries.md) partially supersedes normal-summary eligibility: liver and source-backed A-grade measured rows can produce 未见异常 without a printed 小结. Closed numbered native catalogues distinguish report absence from missing recognition. Abnormal details, attribution, counts, manual priority, source binding, unavailable confidence, review and immutable history remain active. The older decision and measurements above retain their original rationale; no note is archived.
