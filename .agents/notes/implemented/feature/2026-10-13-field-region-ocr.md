# Agent Note: Fill field drafts from operator-selected OCR regions

Status: implemented
Scope: backend/ocr_app, frontend/src, frontend/tests, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, frontend/public/help/index.html
Last-verified: 2026-10-13

## Problem

Readable values can be missing or incorrectly mapped in full-page GLM/Paddle results. Re-running a document is unnecessary for one visible value. The user approves camera buttons beside editable scalar inputs for ordinary OCR transcription, with draft review and existing manual save. The obsolete twelve-hour login explanation is removed as a mechanical correction.

## Decision

The field-button placement and automatic draft application described below are the original decision, partially replaced by [source-region text copying](2026-10-13-source-region-ocr-copy.md). The current component is `RegionOcrDialog.vue`; the source toolbar opens general transcription with optional/null field_key and editable copyable text. CPU execution, corrected coordinates, authorization/version fences and existing manual save remain active. Retain the original UX rationale and verification below as historical evidence, not the current entry contract.

`FieldOcrDialog.vue` opens the authenticated corrected source for the exact task/run/result revision. Page selection and a drag rectangle produce normalized xyxy coordinates relative to the actual displayed image; the server crops stored corrected pixels. Images fit the dialog, including a 1000x720 viewport. The operator checks/edits raw text and applies it to the selected field draft. Empty drafts fill directly; nonempty drafts require confirmation. Existing manual review save remains the only business write and performs normal validation. OCR does not approve issues, change raw evidence, create a task or manufacture business confidence.

`POST /tasks/{task_id}/ocr-region` accepts run_id, expected_revision, page, field_key and bbox and echoes task/version/field/page/selection with bounded text and local OCR reference confidence. The route allows operators on their own tasks and admins on all tasks, denies viewers, and requires the existing same-origin/CSRF checks for cookie sessions. Fresh authorization, ownership and task version are checked before reading and again after OCR, including concurrent session revocation, edits and deletion. OCR holds no database transaction. Only value-free access audit records field key, page and revision; crop and text are never persisted by this action.

`region_ocr_worker.py` reuses the installed RapidOCR3.10 CPU engine and pinned wheel assets from `document_classification.py` in a short-lived child. One local lock permits one in-flight request without a queue. Crops have at least eight pixels per side and at most two million pixels; text has at most 4096 characters. The [process/package repairs](../../implemented/bug-fix/2026-10-13-region-ocr-and-package-repairs.md) use the existing native Windows JobProcess for the complete redirector/worker tree, retaining ten seconds for execution and the supervisor's five-second termination confirmation. Release the slot only after cleanup; unconfirmed cleanup blocks future region workers until restart. The client waits twenty seconds. Busy, timeout, empty and unavailable outcomes are explicit and leave drafts intact. No GLM/Paddle inference, dependency downloads or plaintext temporary files are involved.

The UI cancels/ignores responses after dialog/drawer close, account/client change, task/run/revision change, page change or a different field. A field edited since the camera opened cannot be overwritten by a late result or confirmation. Number fields require finite valid numeric input; dates and identifiers remain literal editable strings, including leading zeros. Top-level text/number inputs, both required and optional, receive cameras. Gender/boolean selection controls, derived fields, medical item cells, household members and generic key/value editors retain their existing controls.

## Decision audit

- [Human review](2026-10-08-human-review-and-xlsx-export.md): partial overlap; reuse corrected-page access, drafts, encrypted manual revisions and existing export validation.
- [Medical navigation](../bug-fix/2026-10-09-medical-only-source-navigation.md) and [cancelled certificate localization](../../rejected/feature/2026-10-09-certificate-field-localization.md): related but not superseded. Explicit manual region transcription does not restore automatic certificate positioning or matching.
- [Mixed upload classification](2026-10-12-person-package-single-submit.md): partial overlap; reuse the pinned CPU asset loader without changing classification semantics or suggestions.
- Existing account ownership and single-session fences remain active. No prior note is wholly absorbed or archived.

## Alternatives considered

- Re-run GLM/Paddle on the entire document: contextual extraction is preserved but expensive work repeats for one value and can change unrelated output. Use bounded selected-region transcription.
- Automatically write OCR text to saved results: removes a click but persists labels, wrong digits or the wrong field without review. Fill a draft and use existing save.
- Crop a browser screenshot: simple, but loses source resolution and risks zoom/scroll coordinate errors. Crop stored corrected pixels from normalized coordinates.
- Add another OCR dependency: can provide specialization but duplicates an installed CPU capability. Reuse current bundled RapidOCR assets and pins.

## Verification

673 backend tests, 142 frontend tests and typecheck/build pass. Eleven focused backend tests cover exact crops and page-two PDF evidence, invalid input/fields/pages, version conflict, leading zeros, unchanged task/run results, ownership/roles/CSRF, concurrent disable/new login/deletion, busy/empty/unavailable/timeout, slot release and real sleeping-child cleanup. Seven frontend tests use the actual SFC setup/lifecycle code to cover scaling, reverse drags, literal values, API echo identity, late responses, draft replacement/cancellation and newer-edit preservation.

The isolated real-browser test `output/region-ocr-20261013/browser-082715/summary.json` passes six checks, with no page errors: login text removal, page-two scaled drag and real CPU OCR, compact viewport fit, draft-only changes, normal versioned manual save and cancelled replacement. Synthetic stores are separate from production. Screenshots contain only synthetic material. Initial fixture peer-address, loading-mask timing and unhandled-promise failures remain in earlier output directories; they are not counted as passes.

`output/region-ocr-20261013/cpu-probe.json` records two serial synthetic-image CPU smoke calls including child initialization: an eighteen-digit leading-zero identifier at 3.887 seconds and a Chinese school name at 1.547 seconds, both exact. This does not establish real-material accuracy, typical latency, production throughput or Mac performance. Validation details are in `output/region-ocr-20261013/validation.json`.

## Consequences

Single-field transcription avoids a full model rerun and preserves saved corrections until an explicit save. A bounded helper adds initialization cost while avoiding another resident recognition model. CPU OCR can misread blur, occlusion or selected labels; the operator remains responsible for checking/editing text. Unknown, missing or abnormal medical information is not interpreted by this tool. Existing schema and account settings need no migration. The source and API changes require rebuilding the frontend and an idle backend restart before use; running-service evidence is recorded separately from code/test completion. The manual and API/field/runtime contracts document scope and failure behavior.
