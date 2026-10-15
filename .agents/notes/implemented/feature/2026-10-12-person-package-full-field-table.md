# Agent Note: Put every selected business field in the first person-package worksheet

Status: implemented
Scope: backend/ocr_app/exporting.py, tests, frontend/src/components/ExportControls.vue, frontend/src/diagnostics.ts, frontend/public/help/index.html, SPEC.md, FRONTEND_FIELDS.md, openapi.yaml, README.md
Last-verified: 2026-10-12

## Problem

The user rejects the six-column personnel overview because they need the exported first worksheet to contain all fields, rather than having to find them in separate type worksheets. The existing certificate worksheets already include the full current profile, but the personnel overview only contains naming and source metadata. The exact eighteen-column medical ledger intentionally omits the supporting exam_projects names. The user explicitly approves a complete first-sheet personnel table, one package per row, with optional and empty columns retained and repeated documents kept independently.

## Decision

Person-package exports use 人员信息总表 instead of 人员材料总览 as their first sheet. Personnel name and naming status come first, followed by every current profile field of each selected material type, and then package source/count/candidate metadata. Business column labels carry their material type. Repeated types use separate numbered groups, each including its own source filename. The column union and maximum multiplicity come only from selected packages/results, so each row has the same headers without leaking unselected values.

Use the same current saved field rendering as the existing detail sheets, including explicit absence text and gender labels. Include all seventeen medical profile fields, particularly the project catalogue, plus the same abnormal-indicator summary as the eighteen-column ledger. Preserve that ledger exactly and retain all existing type/member/generic detail sheets. Household members receive numbered field groups; generic reviewed text is split into bounded text segments and retains all key/value entries, including repeated keys. Empty optional fields still get columns. Removed historical fields and internal IDs, confidence/source geometry and runtime data are outside the business field contract.

Keep one row per package, not one row per recognized or guessed name. Unconfirmed names stay explicit, different source names remain in their own document columns, and name conflicts remain visible. No automatic name/field precedence or majority merge is introduced. Required-value-only eligibility, ownership, selection/version snapshots, saved corrections, string identifiers and formula-safe cells remain unchanged. Fail explicitly when Excel row width or a structured cell exceeds capacity; never truncate or overwrite a document. Freeze the first two columns and header so the person's identity remains visible while scrolling a wide table.

## Decision audit

- [Name suggestions and export](../../implemented/feature/2026-10-12-person-package-name-suggestions-and-export.md): partial overlap; replace only its six-column overview layout. Independent package intent, explicit name confirmation, selected snapshots and duplicate preservation remain.
- [Business workbook](../../implemented/feature/2026-10-09-business-xlsx-layout.md): partial overlap; a wide worksheet is now explicitly requested for a single person's package, while ordinary type batches and detail-sheet formats remain unchanged.
- [Medical ledger](../../implemented/feature/2026-10-09-medical-ledger-template.md): partial overlap; keep the eighteen-column template, additionally expose its auxiliary project catalogue in the personnel table. No clinical decisions or normal defaults are added.
- [Presence-only export](../../implemented/simplification/2026-10-08-required-fields-only-export.md): unchanged.
- Scope/topic search also finds runtime, auth and rejected clinical/location proposals; those concern different decisions and are unchanged. No prior decision is wholly superseded or archived.

## Alternatives considered

- Keep the six-column overview and direct users to tabs: preserves the already tested compact view, but does not satisfy the user's request to see every business field in the first worksheet.
- Merge identically named fields across document types: reduces width, but school, dates, numbers and even names can disagree. Keep explicit type and document attribution.
- Join repeated document values in one cell: reduces width, but null values and multiple fields can lose record relationships. Number complete document groups instead.
- Replace the medical template with a wider ledger: simplest place for the missing catalogue, but breaks the approved eighteen-column business template. Keep it and add complete medical fields in the personnel table.

## Verified invariants

1. The first sheet is 人员信息总表 and has all current fields for every selected type, including optional blank fields and medical project names/abnormal summary.
2. Repeated same-type documents, household members and generic text/key-values survive with their record relationships intact; multi-package rows share the selected-only union schema.
3. Saved corrections, explicit absence values, leading zeros/long identifiers, formula-like strings and long generic text round-trip unchanged. Input snapshots are not mutated.
4. Ordinary batch detail formats and the exact medical eighteen-column ledger remain unchanged; existing export gates and ownership/version tests pass.
5. Reopen a generated mixed workbook and visually inspect representative left/middle/right ranges. Relevant regressions, frontend build and DDE gates pass. Independent review follows the user's release-review request.

## Consequences

The first worksheet becomes wide by design. Keep document groups explicit and frozen identity columns; do not hide fields to make it look compact. Very large repeated/nested inputs can exceed Excel's 16,384-column limit and must produce a clear export error instead of an invalid workbook. This changes the personnel workbook format, not recognition, required-field configuration, stored data or deployment architecture.

## Verification

Five new regression tests reproduce the old missing-field/overview behavior before the change and pass with the complete table. Full backend660 and frontend125 tests pass; the production build passes. Real-HTTP isolated browser acceptance downloads pending/confirmed packages and reopens both workbooks, verifies every selected profile header, actual saved values, package counts, frozen identity columns and unchanged18-column medical ledger. Eight browser check groups pass with zero page errors, vision calls or production changes. Evidence: output/person-full-table-20261012-v1/browser-171537/summary.json. Read-only Artifact Tool import/render of identity, diploma and medical ranges is visually inspected; output XLSX bytes are not changed by rendering.

The independent contract reviewer runs37 focused tests plus3 probes, checking108 profile field values across10 document types, cross-package unions, repeated records, household members, long reviewed generic text/repeated keys, actual HTTP saved corrections and stale-version409. Existing ten detail sheets compare equal in values/styles/freeze/filter to ordinary exports. Evidence: output/full-table-contract-review-20261012/. No blocking finding; initial StyleProxy comparison failure is a corrected probe issue with its failed evidence preserved.

The independent export reviewer runs89 related tests and4 additional probes: actual HTTP cross-package selected-only isolation; medical manual summaries/catalogue count/abnormal-cell agreement with the ledger; exactly16,384 columns round-trip and16,385 columns fail clearly;32,767-character structured cells and repeated household-member association remain intact. Evidence: output/full-table-export-review-20261012/. No blocking finding; an initial incomplete synthetic snapshot omitted task_id, was corrected to the production snapshot contract, and its failed evidence remains.

Local activation follows an idle check, consistent SQLite backup and owned launcher stop/restart. All database tables and2555 original encrypted/key files retain exact pre-restart fingerprints, preserving262 tasks and2 accounts. Schema stays0008, both models are ready, all served frontend files match the build and the live help contains the full-table instructions. Evidence: output/person-full-table-20261012-v1/activation/verified.json. No production recognition or test account/password changes are performed, and no online/Mac deployment or desktop-Excel qualification is claimed.

## Export metadata refinement

The [source filename removal](../../implemented/simplification/2026-10-15-export-without-source-filenames.md) partially supersedes the source filename columns and filename-bearing candidate descriptions in exported workbooks. Full business values, repeated-document groups, application source evidence, naming, snapshot gates and the medical template remain active.

## Column-width refinement

On2026-10-15, nonmedical worksheets retain their existing minimum widths and expand to the longest visible line of the header or exported values, capped at64 Excel width units. 身份证号 receives the identifier minimum27; twelve-point fonts, wrapped long content, text identifiers, colors, frozen panes and the medical18-column template remain. This is a local styling refinement, with no new schema, business rule or decision note. Existing44 relevant tests pass. Synthetic export checks compare actual Microsoft YaHei12-point text metrics against the assigned column widths for identity/card/phone numbers and long school names, including personnel fields. Read-only Artifact Tool previews verify the changed views; numeric-only strings need display-only restoration after import, while the production XLSX remains unchanged with exact string values. Evidence: output/export-widths-20261015/.
