# Agent Note: Ranked table titles and untitled Excel export

Status: implemented
Scope: backend/ocr_app/table_recognition.py, backend/ocr_app/table_export.py, frontend/src/table-review.ts, frontend/src/components/TableReview.vue, tests/test_photo_table_workflow.py, frontend/tests/table-review.test.ts, SPEC.md, FRONTEND_FIELDS.md, openapi.yaml, frontend/public/help/index.html, RUNTIME.md, README.md
Last-verified: 2026-10-15

## Problem

Multiple ranked title candidates currently leave the title blank, while the export gate requires a title even for genuinely untitled tables. The user approved adopting the best available candidate and making titles optional.

## Decision

Use the first valid, trimmed, nonempty candidate in the existing upstream ranking. Skip candidates with control characters or more than 200 characters. Preserve all original candidates and existing OCR titles. Saved human tables remain authoritative, including a deliberately cleared title. Apply this read-time projection to historical and new results without rerunning OCR or mutating revisions, history or review status.

An empty title alone does not block export. Keep header uncertainty, invalid grids, incomplete-output acknowledgement and unsaved-edit gates. Filename priority is nonempty title, original filename basename without extension, then a UTC+8 timestamp named 表格_YYYYMMDD_HHMMSS. Sanitize names and deduplicate ZIP members. An untitled workbook starts at the matrix's first row without an artificial heading; shift merges, frozen rows, filters and print headers accordingly. Existing 21/12/12 title/header/data styles remain.

## Decision audit

- Partially supersedes [direct table export](../../implemented/simplification/2026-10-14-table-export-without-confirmation.md): replace sole-candidate and mandatory-title rules only. Keep saved-value precedence and read-time export.
- Refines [table workflow](../../implemented/feature/2026-10-13-photo-table-to-excel-replan.md) and [automatic headers](../../implemented/feature/2026-10-14-auto-table-header-rows.md); no header inference or model routing change.

## Alternatives considered

- Require a title choice whenever ambiguous: makes human intent explicit, but adds the repeated save step the user rejected and blocks truly untitled tables.
- Always insert a generated title into the workbook: guarantees a visible heading, but invents document content. Use a fallback download name only.
- Ask a model to rank titles again: could use semantics, but the existing ordered candidates meet the approved requirement without extra inference latency.

## Verification

New regression cases first reproduced the old failures (one failed title assertion and fourteen title-gated export errors). All 61 relevant backend tests pass, covering ordered/invalid candidates, saved blank precedence, original preservation, untitled workbook offsets for zero/one/two header rows, merges, safe single/batch filenames, UTC+8 timestamp fallback, historical API export, ownership/revocation and remaining blockers. All 200 frontend tests and Vue typecheck/build pass.

The isolated browser test uses two synthetic tables, a separate database and a test account. It downloads an unreviewed untitled table, a table with multiple title candidates, and the same table after clearing and saving its title. The actual three workbooks have the expected filenames, first-row/header positions, text values, fonts, fills and frozen rows. Clearing without saving blocks download; saving preserves the empty title. Evidence is under output/table-title-20261015/ (browser-checks.json, copied downloads and screenshots). No recognition accuracy claim or Mac deployment change.

Windows activation backs up an idle service before replacing static assets and restarting the owned launcher tree. Both models load and warm successfully in dual_resident mode. All 14 database tables remain identical, including 307 tasks, two accounts, sessions and retention settings; all 3159 material/key files match the backup and all 13 served static files match the tested build. Anonymous business access remains denied. Evidence: output/table-title-20261015/activation/verified.json. The isolated browser server is stopped after testing.

## Consequences

The first candidate is a suggestion, not a verified document title; the UI keeps alternatives editable. Old title-only export blocks disappear without rewriting stored results. No new model calls, schema migration or automatic changes to human work.
