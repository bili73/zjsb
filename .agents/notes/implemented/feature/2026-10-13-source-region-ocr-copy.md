# Agent Note: Copy selected-source OCR text from the original preview

Status: implemented
Scope: backend/ocr_app/region_ocr.py, backend/ocr_app/routes.py, frontend/src, frontend/tests, tests/test_region_ocr.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, frontend/public/help/index.html
Last-verified: 2026-10-13

## Problem

Field-adjacent camera buttons clutter the review form and require choosing one field before transcribing. Staff also need text for medical details or several fields. The user approves moving the entry to original-source comparison and displaying editable OCR text for copying, replacing automatic field application.

## Decision

Put a labelled camera button in SourcePreview's toolbar. It opens the existing bounded page/rectangle dialog at the most visible corrected page, with manual page selection. OCR text appears in the same dialog as an editable textarea. Copy and close writes the checked text to the clipboard and closes only on success; failure leaves text available for manual selection and copying. Staff paste where needed and use the existing manual save. Remove camera controls and automatic field-application state from ReviewEditor. Temporary crops never alter originals or create tasks.

The request's field_key becomes optional: omitted/null means general transcription and returns null; a supplied legacy key retains the previous editable-field checks and response echo. Frontend general requests omit it. Preserve fresh authorization/ownership/version checks before and after OCR, source-page uniqueness, short-lived CPU worker, one in-flight request, ten-second budget and bounded crop/text. No extra model or schema migration. Dialog/request state is fenced on close, account/client/task/version/page change, stale result or lost permission. Copy failure does not discard text or drafts.

## Decision audit

- [Field-region OCR](2026-10-13-field-region-ocr.md): partial replacement of entry placement and automatic field binding only. CPU execution, corrected coordinates, permission/version fences and bounded failure behavior remain.
- [Medical navigation](../bug-fix/2026-10-09-medical-only-source-navigation.md): partial overlap; preserve navigation and source overlays. Manual selection does not restore rejected automatic certificate localization.
- [Human review](2026-10-08-human-review-and-xlsx-export.md): partial overlap; drafts and save remain independent of temporary OCR text. No current note is wholly absorbed or archived.
- Existing account/session and medical interpretation decisions remain unchanged; proposed Mac deployment is unrelated.

## Alternatives considered

- Keep field buttons and direct draft filling: saves paste actions for a single known field, but clutters every input and cannot conveniently serve multiple fields or medical rows. Replace with a general source transcription tool.
- Select rectangles directly in the narrow preview: avoids a larger dialog but makes small characters hard to select and competes with click-to-enlarge and medical source navigation. Reuse the larger bounded dialog.
- Add a destination-field dropdown: can avoid pasting but adds another mapping step, complicates row/member destinations and risks filling the wrong field. Provide editable copyable text and preserve manual control.

## Verification

674 backend tests and 142 frontend tests pass, including general omitted/null field keys for diploma, medical, generic and household documents, legacy field validation, multiline text, leading zeros, unchanged encrypted results, ownership/CSRF and stale authorization/version fences. The actual dialog setup tests cover current-page initialization, late OCR responses, clipboard success/failure/unavailability, copy reentry and late completion after reopen. Frontend typecheck/build pass with the existing bundle-size advisory.

The isolated browser report `output/source-region-copy-20261013/browser-085929/summary.json` passes seven checks using real CPU OCR and synthetic two-page evidence: source toolbar/no field cameras, actual visible page two on first open, page switching and scaled crop, editable multiline text, compact viewport, successful clipboard without draft writes, denied clipboard with selectable text, and explicit manual save preserving an earlier manual draft. Windows clipboard CRLF is normalized only in the browser assertion. Thirteen existing source-navigation browser checks pass in `output/source-navigation-layout/attempt-vvAxcu/` with no model or business requests. These are functional tests, not real-document accuracy or Mac measurements.

The initial page-two test exposed an immediate-watcher registration bug; registering the page watcher first resolves it. Initial synthetic browser probes retain failures from scroll/focus/animation setup and the Windows clipboard newline assertion. The browser fixture blurs the editor and uses a wheel before checking the visible page. Failed outputs remain separate and are not counted as passes. Idle backup/restart and `output/source-region-copy-20261013/activation/verified.json` confirm both models ready, unchanged database tables (262 tasks and two accounts), 2567 unchanged encrypted/key files, thirteen matching static files and anonymous region OCR rejected with401. No production recognition or business edits are used for validation.

## Consequences

Clipboard APIs can be blocked or absent on nonsecure sites; leave selectable text and a manual-copy message. Recognition remains transcription, not semantic interpretation or field validation. Source pages must be uniquely stored corrected evidence. Preserve all previous test outputs and failed probes; report new synthetic tests separately from material accuracy.

[API authorization boundaries](../bug-fix/2026-10-13-api-authorization-boundaries.md) extend the live transaction session check to material operations, add default route authentication and protect full health/slow responses; this note retains its remaining decisions.

[Date clipboard suggestions](2026-10-13-region-date-copy-suggestions.md) extend the current result card with separate selectable date formats, preserve the editable OCR text and the current non-closing copy controls, and retain its existing request/permission/version fences. The earlier copy-and-close label does not describe the current result card.
