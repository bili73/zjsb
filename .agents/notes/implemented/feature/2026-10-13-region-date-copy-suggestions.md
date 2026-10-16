# Agent Note: Offer date-only clipboard suggestions alongside region OCR text

Status: implemented
Scope: frontend/src/regionOcr.ts, frontend/src/components/RegionOcrDialog.vue, frontend/tests, SPEC.md, FRONTEND_FIELDS.md, RUNTIME.md, frontend/public/help/index.html
Last-verified: 2026-10-13

## Problem

Region OCR returns Chinese-formatted dates, while existing business fields accept YYYY-MM or YYYY-MM-DD. The user approves keeping the editable OCR text and providing an additional, independently copyable date suggestion. Overwriting text or supplying a missing day would lose evidence or change date precision.

## Decision

A small deterministic browser helper extracts explicit four-digit-year Chinese dates from the current editable OCR text. Accept Arabic/full-width digits and common Chinese digit/year and ten-based month/day notation; whitespace between recognized characters is tolerated. Validate the actual Gregorian calendar, retain month/day precision and preserve source order. Distinct suggestions remain separate; identical formatted values need only one copy control. Invalid or incomplete dates, ambiguous two-digit years, and arbitrary numbered strings are not repaired. A bad day must not fall back to a valid-looking month. The user explicitly clarifies that complete numeric dates missing only 日 must use the existing certificate-footer tolerance. Accept the complete day at an unambiguous boundary, and retain existing year-only O/o-as-zero compatibility; masked/missing digits and unknown suffix text remain rejected. This adjusts the initial mandatory-suffix proposal before implementation is completed, not the source date-role or field-validation rules.

The existing text box and copy-text action remain. A labelled date-suggestion list has readonly selectable values and independent copy actions. Editing text recomputes suggestions; copying them does not fill fields, save results or change the OCR score. Clipboard failure selects the requested suggestion for manual copying, including nonsecure HTTP deployments. Existing permission/version/page/client/close fences still discard late OCR and clipboard completions. Keep the floating panel within the viewport with scrolling when necessary. No API, storage, inference model, dependency or backend change.

## Decision audit

- [Source-region copying](../../implemented/feature/2026-10-13-source-region-ocr-copy.md): partial overlap; retain original text, manual paste/save and lifetime fences, adding only format suggestions.
- [Click-to-view OCR](../../implemented/feature/2026-10-13-source-preview-click-ocr-entry.md): partial overlap; preserve its current cinema and bounded entry variants while extending their shared result card.
- Existing certificate date normalization and field validation establish YYYY-MM / YYYY-MM-DD and calendar validity. This helper does not change extraction or decide admission/graduation/issue-date roles.
- Proposed hosted authentication and rejected certificate localization/clinical interpretation are unrelated; no note is wholly superseded or archived.

## Alternatives considered

- Replace the OCR text with the normalized date: requires one fewer choice, but removes original evidence and can mislead users when several dates are selected. Preserve both representations.
- Return date suggestions from an OCR API or language model: centralizes normalization and could support more semantic cases, but adds a wire contract or inference cost for deterministic formatting. Keep the feature local to the temporary copy UI.
- Complete missing days or pick the last date: reduces typing, but invents precision or confuses document date roles. Keep source precision and separate suggestions.

- Require 日 on every day-precision date: avoids ambiguous suffix parsing, but rejects the user-approved certificate behavior when only that printed marker is obscured. Accept a complete valid day at a clear boundary; do not complete digits.

## Verification

All151 frontend tests pass (145 before the change), with successful typecheck/build. Date helper tests cover calendar precision, common glyphs, missing 日 at clear boundaries, ranges/order/deduplication and invalid or masked dates. Actual SFC tests cover independent copying, reactive suggestions, unchanged OCR text/reference score, correct manual-copy selection and success/rejection after all account/task/version/page/permission/close/unmount fences. Eighteen explicit inputs agree with the existing _certificate_date(..., allow_missing_day_suffix=True) implementation; arbitrary prose and extraction roles are outside that parity check.

The isolated real Edge/API probe passes6 scenarios in both bounded and cinema modes, including a390px result card with twelve dates and scrollable copy controls. Saved run/revision/result ciphertext and existing unsaved school-name correction remain unchanged. OCR output is deterministic synthetic text; no real model inference, business accuracy benchmark or production business/account change is performed. The current local service serves13 files matching the build without a backend/model restart. Mac/external deployment is not updated. [Verification report](../../../../output/region-date-copy-20261013/REPORT.md) retains results, screenshots and failed attempts.

## Risks

A format suggestion is not proof of OCR correctness or a decision about the target field. Explicit dates may still be misread, so users must compare the original image. Native Clipboard APIs may be unavailable over HTTP; the readonly value remains selectable. Large selections can contain many dates, requiring bounded visual scrolling.

## Consequences

The UI adds deterministic formatting and calendar validation only; it does not infer field roles or improve the OCR itself. Users retain editable text, independent selectable suggestions and manual save. Date precision is never increased beyond observed digits; missing only the day marker follows the user-approved certificate compatibility. Clipboard failure leaves the requested representation available. A long list scrolls inside the result card. No API, backend, model, schema or dependency change is introduced; concurrent source-view presentation changes remain intact.

The [HTTP browser compatibility extension](../../implemented/bug-fix/2026-10-15-http-browser-capabilities.md) extends automatic copying without changing date precision, original text or draft ownership.
