# Agent Note: Export saved business fields and focused medical abnormalities

Status: implemented
Scope: backend/ocr_app/exporting.py, backend/ocr_app/task_store.py, backend/ocr_app/extraction.py, tests, scripts/replay_oct9_repairs.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user rejects the current Excel output and asks for filled document fields, medical personal information, major examination projects and abnormal indicators with a usable layout. Read-only serialization of Zhang's saved revision produces Tasks, MEDICAL_REPORT, MedicalItems (67 measurements) and MedicalFindings (six findings), exposing internal UUID/run/revision columns and English field keys. Header cells have default style 0; there are no configured column widths or filters. This is verified serializer behavior; the user's particular downloaded file was not supplied or found in Downloads.

## Decision

Replace the technical workbook with business worksheets grouped by material type. A document row contains its latest saved field values in profile order with Chinese labels, plus a readable source filename to distinguish repeated names/materials. Keep removed principal/study-mode/medical-profile fields absent. For household records and generic text, retain their necessary business details without dropping supported material types.

Medical export has two focused worksheets: 体检汇总 (one source/report row, current personal fields and the printed examination-project catalogue) and 体检异常指标 (one eligible abnormal row, person/source association, project, result, unit, reference range, report grade and abnormal diagnosis). Use the current saved correction, never the original recognition run as a replacement for edits. Exclude height, weight and exact 小结; retain BMI. Reconcile printed follow-up entries with measurements through their source-backed links: do not duplicate linked entries, and include an unlinked printed abnormal entry with a clear missing-result label rather than silently dropping it or inventing a measurement. Printed follow-up lists are not exhaustive laboratory counts.

Use Chinese worksheet/header names, a restrained colored header, readable font and column widths, wrapped long project/diagnosis text with suitable row heights, filters, frozen headers and sensible landscape print setup. Identifiers remain explicit strings with leading zeros and full precision; untrusted content never becomes an Excel formula. Internal UUIDs, runtime/status/debug columns and normal-test dumps do not appear in the business workbook; server audit/history remains intact.

Preserve current export selection and eligibility: current batch or selected tasks, all selected required saved fields present, otherwise block the whole selection. Low confidence or unresolved optional/coverage issues do not create a new export gate. Long-field capacity failures remain explicit; no silent truncation. Export still uses a consistent saved snapshot and existing authorization/version checks.

## Decision audit

The user keeps this layout temporarily and will provide a business template later. After inspection of the source standard, the user explicitly assigns judgment to humans; the [automatic threshold review proposal](../../rejected/feature/2026-10-09-medical-threshold-review.md) is rejected. The medical summary adds only 人工录取意见 with 待人工判断 as an Excel placeholder for HR to fill after download. It is not a new required extraction field, a saved application decision or an automatic conclusion, and the export gate remains unchanged. The future business template is not implemented.

[Review/export](2026-10-08-human-review-and-xlsx-export.md) partly overlaps: selection, saved snapshots, string identifiers, formula protection and audit remain, while the technical worksheet layout is replaced. [Presence-only export](../simplification/2026-10-08-required-fields-only-export.md) remains unchanged. [Medical catalogue](2026-10-08-medical-project-catalogue.md) supplies the major projects. [Native continuation](../bug-fix/2026-10-09-native-medical-table-continuation.md) supplies the missing urine measurements. No complete supersession or archive is appropriate.

## Alternatives considered

The approved [medical ledger template](../../implemented/feature/2026-10-09-medical-ledger-template.md) partially supersedes medical two-sheet output and the temporary opinion placeholder with the supplied eighteen-column ledger. Other document sheets, saved corrections, literal values, overflow failure, snapshot gates and historical verification remain active; no automatic employment grading is introduced.

- Style the existing sheets only: smallest visual change, but leaves the wrong content and technical columns. Change layout and content together.
- Export every original row for traceability: retains detail, but the user explicitly requests abnormal indicators. Preserve originals in application evidence/history instead of the default business workbook.
- Export printed follow-up findings only: yields the six visible rows, but can omit additional real abnormalities and missing-result evidence. Reconcile both sources without fabricating links.
- One wide mixed-material sheet: easy to create, but different document schemas leave most columns blank. Group by material type and separate medical summary/detail.

## Verified invariants

- Manually corrected document fields export exactly as saved, with Chinese profile labels and no retired/internal columns. Multi-type, household and generic selection remains supported.
- Medical summary includes personal information and the examination catalogue; abnormalities include source/person association, value and report diagnosis/grade, no normal/height/weight/小结 rows and no duplicated linked findings.
- Full selection gates, version consistency, leading zeros/long identifiers, malicious formula-like text, long-cell failure and zero/missing values pass regression tests.
- Reopen the actual XLSX and visually render every generated sheet at normal zoom. No clipped headers, values or diagnosis text; filters/frozen headers work. Real-source output and synthetic multi-type fixtures are inspected separately.

## Verification

Three dedicated workbook tests, existing business/review/export tests and all 447 backend tests pass. The actual real-source replay workbook has three business sheets; the separate synthetic workbook covers all 11 material types across 14 sheets. Reopened XLSX cells retain string type and text format for leading-zero/long identifiers and +3/+1; there is no formula execution. All 17 generated sheets were rendered and visually inspected at normal zoom. The QA renderer coerces numeric-looking imported strings, so its preview alone needed the exact values restored with display-only zero-width prefixes; the XLSX bytes were not modified. Real-source replay is a demonstration, not a newly approved saved production revision. Browser Cookie/CSRF export separately downloads two medical sheets with six abnormal rows. Evidence is in [replay](../../../../output/repairs-20261009-v1/replay/summary.json) and [browser acceptance](../../../../output/repairs-20261009-v1/browser-4/summary.json).

## Consequences

The user-approved [complete personnel table](2026-10-12-person-package-full-field-table.md) partially extends the grouped-only layout for explicit person packages: their first sheet contains every selected current business field. Ordinary batches and all existing type/member/generic detail sheets remain unchanged, including safe saved values and required-only selection gates.

The workbook layout is an externally visible format change; technical-sheet tests and contracts are explicitly updated. Unlinked findings carry a readable missing-result label without changing the approved required-value export gate. Existing downloaded workbooks are preserved, and the still-running old service must be restarted before it uses the new exporter.


## Current refinement

The [biochemistry/export refinement](../bug-fix/2026-10-09-biochemistry-ledger-export.md) changes nonmedical header fill to EF760E and places each medical abnormal entry on its own line. Template colors, saved fields, literal string safety and association rules stay active.


## Current refinement

The [workbench filename policy](2026-10-09-material-time-download-names.md) adds Chinese type plus Shanghai export time to single, batch and selected download names. Workbook layout, saved-value gates and backend API bytes remain unchanged.
