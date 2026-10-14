# Agent Note: Extract source-bound dynamic form pairs through the existing Paddle pipeline

Status: implemented
Scope: backend/ocr_app, frontend/src, tests, frontend/tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, README.md, frontend/public/help/index.html
Last-verified: 2026-10-14

## Problem

GENERIC currently uses the GLM lane and recognizes only whole-line colon pairs or exactly two HTML cells. It flattens table content and lacks pair sources. The user approves optimizing forms, applications and registration sheets with existing PaddleOCR-VL, subject detection and adaptive fields.

## Decision

Retain reliable native PDF evidence, otherwise use the current Paddle model, with one GLM fallback per region and a 40-second generation soft budget inside the existing 180-second task budget. GENERIC shares the Paddle document lane with MEDICAL_REPORT/TABLE; no third model, worker or queue. Photos reuse the installed CPU upright model. Subject planning uses existing CPU text boxes and ruled-table geometry, crops only blank margins and otherwise keeps the full region. Split an unambiguous ruled table band from surrounding text without dropping the margins; ambiguous layouts use whole-region OCR. Retain original full corrected pages, source coordinates, attempts, truncation and failures.

Dynamic extraction uses explicit labels, cell structure and supported positional relationships, not a fixed field dictionary. Preserve repeated labels, empty values, multiline content, all original text and ambiguous tables. Native text overlapping a native table is not emitted twice as pairs; duplicate removal requires same-page source geometry AND containment of its text in the decoded table, not equal text or geometry alone. Table/cell coordinates remain honest: use observed cell boxes when available and the enclosing region otherwise. Confidence stays null. Initial pairs have immutable IDs and sources. Human patches may reference an original pair ID, never submit forged coordinates; manual keys/values remain editable and old key/value-only patches remain valid. Saved text and every saved pair, including repeated names, continue to export.

## Decision audit

- [Card/document profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) partly overlaps: replace the minimal GENERIC extraction only; retain all certificate rules, complete internal values and model limits.
- [Independent queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) remains authoritative; only GENERIC's primary lane changes.
- [Required-value export](../../implemented/simplification/2026-10-08-required-fields-only-export.md) retains reviewed_generic precedence, saved-version gates and atomic selection exports.
- [Photo-table workflow](../../implemented/feature/2026-10-13-photo-table-to-excel-replan.md) contributes existing CPU geometry and strict table decoding, but TABLE keeps its separate editable matrix/export contract.
- [Upright photos](../../implemented/feature/2026-10-12-certificate-image-upright.md) is extended to GENERIC; PDF processing remains native-first.
- Prior rejected certificate positioning, third-party table implementation and clinical interpretation decisions are not revived. Mac/runtime proposals remain outside this local implementation.

## Alternatives considered

- Ask the OCR decoder for arbitrary JSON: looks direct, but the installed element-recognition prompts are not a verified general semantic API; use its actual text/table output and source-bound parsing.
- Add a language/layout model: could improve semantic ambiguity, but expands deployment and introduces an unapproved model; reuse installed models and leave ambiguity visible.
- Keep whole-page GLM plus colon regex: smallest change and retains current behavior, but fails the explicit request for Paddle and layout-aware fields.
- Crop only the largest table: reduces OCR input, but can drop the title and notes; preserve every nonblank surrounding band and keep the whole region when unsure.

## Verified scope

Tests cover multiple pairs per line, empty and repeated labels, multiline/merged forms, header-over-value layouts, record tables that must not become false pairs, source-bound deduplication, PDFs without model calls, photo upright/Paddle routing, bounded fallback/partial evidence, independent queues, original-ID review validation, legacy review preservation and complete safe Excel exports. Frontend validates optional sources, exposes original/pair locations and retains IDs through edits. Browser smoke uses isolated synthetic data/accounts; no production credentials or accuracy claims. Relevant regression, typecheck/build and DDE verify pass.

## Consequences

OCR geometry is not semantic certainty. Pure-text tables, faint handwriting and multiple forms can remain ambiguous. Recognition still needs human checking; partial extraction never means the source is complete. Public additions are optional and require no database migration. New business accuracy needs independently annotated real forms.

## Verification

14 focused form tests cover paired/empty/repeated labels, layout ambiguity, merged multiline and rowspan values, native PDF without model calls, precise native cell sources, original-ID review validation, safe complete Excel, Paddle-to-GLM fallback, malformed tables, retained partial output and deadlines. Queue routing and public OpenAPI tests extend existing suites; frontend source-link and legacy draft tests pass. The first full regression had one outdated test asserting GENERIC photos never use upright preparation; the approved feature now enables that path, so the fixture covers medical photos and all PDFs and the new form test verifies one upright decision reused across both decoding passes.

An isolated synthetic browser workflow verifies six pairs, source overlay, manual edits, unsaved-export blocking, persistence after reopen and actual XLSX download with all six saved pairs, leading-zero text and white data rows. Source screenshot/download/checks live under output/generic-forms-browser-20261014; this uses a fake recognition result and is not OCR accuracy evidence. A separate actual installed CPU layout run on the synthetic page found six text lines in 1.391 seconds; this is only layout timing, not end-to-end inference performance. No independent real-form accuracy labels or Mac verification were produced. Runtime activation evidence and final full-suite totals are recorded in RUNTIME.md.

Final verification: all 733 backend tests passed in 313.187 seconds; 166 frontend tests, typecheck/build and 82-note DDE verification passed. Local Windows 1.24.0 activation verified both model warmups, 11 unchanged business tables, 271 tasks, 2 accounts, 2814 material/key files and 13 served build assets. Original first-run failure evidence is preserved. No Git commit/push or Mac deployment was performed in this change.
