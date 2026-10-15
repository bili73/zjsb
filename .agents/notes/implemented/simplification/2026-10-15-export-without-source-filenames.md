# Agent Note: Remove source filename metadata from Excel worksheets

Status: implemented
Scope: backend/ocr_app/exporting.py, tests/test_business_workbook.py, tests/test_person_workbook.py, tests/test_person_package_names.py, SPEC.md, FRONTEND_FIELDS.md, openapi.yaml, README.md, RUNTIME.md, frontend/public/help/index.html
Last-verified: 2026-10-15

## Problem

The user no longer needs the application-added source filename in exported Excel files. It currently appears in certificate, household member, generic text/key-value sheets, each repeated-document group in the personnel table, its trailing source list and its name-candidate descriptions. Removing only one header would leave other copies and risk shifting values into the wrong business columns.

## Decision

Remove source filename headers and matching values from all business worksheets. Personnel tables keep every selected current business field, numbered repeated-document groups, names/status/counts and name candidates with their material types, without filenames. Certificate/member/generic columns close up without blank placeholders. Keep existing layout styles, filter bounds, selected-only unions and frozen personnel identity columns.

This only changes newly generated workbook content. Preserve stored filenames, original evidence and UI name-suggestion sources; preserve the untitled photo-table download filename fallback. Actual recognized table cells or generic business keys named 来源文件 are source content, not application metadata, and remain intact. The medical eighteen-column ledger already has no filename column. No data migration, OCR, eligibility, authentication or audit change is needed.

## Decision audit

- [Business workbook](../../implemented/feature/2026-10-09-business-xlsx-layout.md): partially replace its source-column requirement, preserving saved fields, safe strings, layout and export gates.
- [Full personnel table](../../implemented/feature/2026-10-12-person-package-full-field-table.md): partially replace source columns and candidate filenames, preserving complete business fields and repeated-document relationships.
- [Name suggestions and export](../../implemented/feature/2026-10-12-person-package-name-suggestions-and-export.md): only the exported source metadata changes; application name evidence and confirmation remain active.
- Scope/topic search also finds medical templates, table export, runtime/auth and rejected medical/location proposals; they decide different behavior. No note is wholly superseded or archived.

## Alternatives considered

- Hide filename columns: maintains traceability and old column positions, but still leaves unwanted metadata in the downloaded workbook. Remove them entirely as requested.
- Remove filenames from storage and API: eliminates all copies, but breaks original-file navigation and untitled table filenames outside the requested scope. Change serialization only.

## Consequences

Workbook columns shift left where a source filename used to appear. Spreadsheet consumers must address the current business headers instead of historical column numbers. Original evidence remains accessible in the application; Excel no longer identifies each row by its uploaded filename. Existing downloaded files are not rewritten.

## Verification

Before implementation, four updated workbook assertions reproduced the unwanted source metadata. All139 related backend tests now pass, covering ordinary and nested/member/generic sheets, multiple personnel packages, medical18-column layout, all profile columns, saved values/absence rendering, repeated documents, text identifiers/formula safety, untitled photo-table filenames and authenticated export gates. The previous all-business fixture incorrectly included TABLE, which is forbidden in mixed/person-package API exports; the fixture now excludes it, and the column-limit fixture derives its count from business fields rather than deleted metadata. Independent read-only synthetic workbook probes confirm no filename sentinels remain, name conflicts and numbered groups survive, original business keys/headers named 来源文件 stay intact, and styles/filter bounds/input immutability hold. Existing downloads remain unchanged. No OCR accuracy measurement or Mac deployment is claimed.

Local activation followed an idle/expiry check and consistent database/material/key/static backup. All14 database tables stayed identical, preserving271 tasks,2 accounts and2976 material/key files;16 served static files match the prepared copy including the updated help. Minimal health is healthy and anonymous business/diagnostic endpoints return401. Both owned model processes are present; no independent warmup or recognition measurement is claimed. Evidence: output/export-without-sources-20261015/activation/verified.json. DDE verification and index consistency pass.
