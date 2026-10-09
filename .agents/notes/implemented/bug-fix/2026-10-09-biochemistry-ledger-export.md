# Agent Note: Show measured biochemical liver results and readable Excel anomalies

Status: implemented
Scope: backend/ocr_app/medical_ledger.py, backend/ocr_app/exporting.py, tests/test_medical_ledger.py, tests/test_business_workbook.py, backend/ocr_app/api.py, tests/test_runtime_api.py, tests/test_document_contract.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user sees an empty liver_function field and locates its values under 生化检验报告单. Read-only inspection and previous native replay show seven measured liver rows per source already attributed to that group, all graded A, with no explicit clinical conclusion. The mapper's abnormal-or-conclusion-only summary therefore remains empty. Adding a duplicate heading alias would not fix this. The user also requests one abnormal indicator per line in Excel and nonmedical headers filled with #ef760e.

## Decision

Keep existing 生化检验报告单 source attribution and its liver-name/abbreviation whitelist; never treat every biochemical or hepatitis measurement as liver function. When liver_function has no abnormal summary or explicit conclusion, serialize the actually observed, source-backed group measurements as names, values and units. This describes observed results, does not assert 正常, completeness or exactly five indicators. Unknown, missing, conflict and manual values retain their existing semantics. Manual absence must not be replaced. Other groups' summary rules remain unchanged, and the abnormal export still excludes normal measurements.

Change only the Excel abnormal-cell entry separator from the ideographic comma to a newline. Keep linked diagnosis/result association, de-duplication, original order, literal string safety and one report per row; existing wrap/row-height calculation must show the lines. Change all nonmedical worksheet header fills to EF760E, preserving medical template colors and saved values. No extra model call, required-field change, queue change, automatic medical judgment or database migration.

## Decision audit

- [Medical ledger](../../implemented/feature/2026-10-09-medical-ledger-template.md): partial overlap; retain source-bound groups, human overrides, eighteen columns and independent counts. Add only observed-result fallback for the liver group and replace the abnormal-cell delimiter.
- [Business workbook](../../implemented/feature/2026-10-09-business-xlsx-layout.md): partial overlap; retain per-type saved fields, string safety, layout and linked findings; refine requested header fill.
- [Cover institution](../../implemented/bug-fix/2026-10-09-medical-cover-institution.md): unrelated extraction location; retain unchanged.
- [Presence-only export](../../implemented/simplification/2026-10-08-required-fields-only-export.md): no eligibility change.
- Mac/session-auth proposals and the rejected automatic medical threshold decision are unrelated. No note is wholly absorbed or archived.

## Alternatives considered

- Add 生化检验报告单 as a generic liver heading: simple, but this heading is already handled and unrestricted assignment could include glucose, lipids or hepatitis markers.
- Fill 正常 whenever no abnormal liver row appears: concise, but absence/incompleteness is not normal evidence. Show actual measurements without inventing a conclusion.
- Keep the column blank and require manual entry: avoids rule changes but hides seven already recognized source-backed values in these samples.
- Write each abnormality as a separate workbook row: readable, but breaks the approved one-report-per-row template. Use wrapped newlines in the existing cell.

## Verified invariants

Reproducing tests demonstrate populated source-backed liver measurements with no fabricated normal, no unknown biochemical/viral rows, preserved manual values/absence and abnormal/conclusion priority. Workbook round-trip confirms newlines, wrap/height, nonmedical EF760E and unchanged medical colors. Three original PDFs replay without model calls or production writes; original hashes, project and anomaly counts stay unchanged. Appropriate backend regression and DDE verification pass, and the idle identity-verified service is refreshed with original tasks/accounts/keys preserved.

## Consequences

Observed-row summaries can be longer than a one-word conclusion and do not prove a whole report is complete. Unknown names outside the whitelist remain reviewable rather than guessed. Revisit aliases only with real source evidence. No new GPU accuracy or Mac qualification is claimed.


## Release verification

The final backend suite passes477 tests in117.560s, the frontend passes70 tests and typecheck/build. The isolated real HTTP/headless Edge probe passes5 checks with zero page errors, real model calls or production writes: automatic two-photo upload, missing-PAN peer isolation, real rotation and retained crop after a synthetic503, one-crop retry with both original results unchanged, and month/week/day picker selection plus clearing. Its initial attempts expose and then fix the missing Day.js locale registration; failed logs/screenshots remain preserved.

Three native medical reports retain7 source-backed liver measurements each (21 total, page14), catalogue counts9/10/11 and abnormal counts7/6/2, with0 model calls and154 unprocessed image regions. XLSX round-trip and rendered QA verify actual liver results,7/6/2 newline anomaly entries, original string identifiers, EF760E nonmedical headers and unchanged medical blue/orange. This is mapping and layout verification, not new full-report or bank OCR accuracy.

After three idle checks, a consistent SQLite backup and confirmed exit of all12 old owned processes, Windows loopback1.17.0 serves the qualified frontend. Both models are ready. The55 existing tasks encrypted fields, one account and key files retain their previous signatures. Evidence: output/bank-auto-20261009-v1/ and output/biochemistry-export-20261009-v1/. No database migration, original sample rewrite, extra semantic model, Mac qualification, commit or push occurs.


## Current refinement

The [liver abnormal-only correction](2026-10-09-liver-abnormal-only.md) partially supersedes the measured-result fallback above after the user clarifies the column is for abnormalities. Normal/unknown measurements and normal conclusions no longer automatically fill liver_function. The old fallback and verification describe1.17.0; newline anomalies, EF760E headers and source attribution remain active.
