# Agent Note: Export complete recognized tables without a mandatory review save

Status: implemented
Scope: backend/ocr_app/table_recognition.py, backend/ocr_app/table_export.py, backend/ocr_app/exporting.py, frontend/src, frontend/tests, tests/test_photo_table_workflow.py, SPEC.md, FRONTEND_FIELDS.md, openapi.yaml, frontend/public/help/index.html, README.md, RUNTIME.md
Last-verified: 2026-10-14

## Problem

The table UI fills title and header drafts, but export requires reviewed_tables even when nothing is missing. The batch board incorrectly calls this missing required information. The user approves removing the mandatory first save, retaining actual missing/partial blockers and saved human precedence.

## Decision

Use one server effective-table helper for eligibility and serialization. An existing reviewed_tables value is authoritative, including intentionally blank titles, null/zero headers and an unfinished draft. Otherwise clone the original matrix, adopt a sole distinct nonempty title candidate and a supported complete header suggestion. Multiple distinct title candidates remain a visible choice; do not arbitrarily choose the first. Never persist this projection as a human review or change status, revision, source values or history. Current and historical tasks use the same read-time rule, without rerunning OCR.

Valid title, header count and matrix permit direct export. Truncated/structurally incomplete originals still require a saved explicit partial acknowledgement. Empty source, invalid grids and uncertain metadata block the entire selection with precise reasons. Unsaved local edits still block drawer export. UI defaults follow the same selection rules; table-specific batch labels say export needs attention, not all missing required values. Unchanged tables do not need the save button.

## Decision audit

- [Photo-table workflow](../../implemented/feature/2026-10-13-photo-table-to-excel-replan.md) partly overlaps: replace only the mandatory saved-table export rule; retain source preservation, formats, limits, permissions and partial-output acknowledgement.
- [Automatic header drafts](../../implemented/feature/2026-10-14-auto-table-header-rows.md) partly overlaps: supported suggestions now also feed export; preserve conservative inference and saved null/zero precedence.
- [Required-value export](../../implemented/simplification/2026-10-08-required-fields-only-export.md) remains the shared state-preserving and whole-selection contract; no changes to other document types.
- [Withdrawn table implementation](../../rejected/feature/2026-10-13-photo-table-to-excel.md) remains rejected. Other proposed runtime/auth and medical notes do not decide table confirmation.

## Alternatives considered

- Automatically call the review/save endpoint: reuses the previous gate, but falsely attributes untouched OCR to a human and needlessly changes revisions.
- Keep mandatory confirmation with a renamed button: clearer wording and explicit checking, but retains the extra click the user asks to remove.
- Export any first candidate: maximizes automatic downloads, but hides ambiguous titles and incomplete output; retain actionable blockers instead.

## Verification

Regression tests first reproduced direct-export rejection (10 failed assertions in the new cases), then all 26 table tests passed. Complete unsaved originals export exact cells/merges and expected header styling with no review/state/revision mutation; saved edits always win; absent/ambiguous title, unsupported header, invalid/partial output block with precise reasons. Single and batch exports, stale versions, cross-account/read-only/revoked-session protection are covered. All 163 frontend tests and Vue typecheck/build pass. An initial frontend assertion failure was an outdated message substring; preserve the established required-field phrase while making table reasons specific.

The isolated 8767 browser probe downloads a complete recognized table before any save, then verifies unsaved cell changes block export and saved manual values appear in the second actual XLSX download. Both files are parsed to verify leading zeros, orange headers and white data cells. Evidence: output/table-direct-export-browser-20261014/ (synthetic inputs, separate accounts/database, screenshots, browser-checks.json). No production login or recognition request is used.

The user also requests white backgrounds for data cells in every Excel type. The shared business serializer drops alternating row fills; the table serializer already uses white data cells. Header fills and 21/12/12 title/header/data sizes remain. Existing workbook assertions cover the changed styling.

Full backend regression passes 717 tests in 252.659 seconds. All 163 frontend tests pass, and DDE verifies 81 notes. The isolated browser server is stopped after validation; its synthetic evidence is retained. No real model inference or new accuracy benchmark is performed.

Windows local activation first verifies idle work and backs up the consistent database and owned files, then restarts the inspected launcher tree in dual_resident mode. Both models load/warm successfully, public health is ok and anonymous protected endpoints return 401. All 11 database tables remain identical (270 tasks, 2 accounts), all 2800 material/key files match and 14 build assets match their HTTP bodies. See output/table-direct-export-activation-20261014/verified.json. Production sessions are preserved; the Mac deployment copy is not changed.

## Consequences

Exportability is structural completeness, not proof of OCR accuracy or human approval. Keep warnings and NEED_REVIEW state. Conservative title ambiguity may require selection even though a previous draft silently picked the first. This change adds no model calls, accuracy claims, deployment changes or audit features.
