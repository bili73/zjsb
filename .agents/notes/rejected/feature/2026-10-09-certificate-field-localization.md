# Agent Note: Match certificate fields to observed text-line coordinates

Status: rejected — The user cancels certificate positioning and keeps medical navigation only.
Scope: backend/ocr_app, backend, frontend/src, frontend/tests, tests, requirements-app.lock.txt, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user confirms the localization investigation and authorizes text-position detection, coordinate matching and the same-page frontend fix. Existing certificate field sources are whole-page OCR input regions; 30 saved diplomas have290 such sources and four degrees have33. SourcePreview only watches page changes, so another field on the same page does not scroll again.

## Proposal

Keep GLM/Paddle as the business recognizers. Use pinned rapidocr-onnxruntime1.4.4 with its bundled PP-OCRv4 detector/recognizer and direction classifier as a CPU-only positioning helper. Independent line text is needed to match values reliably; a detector's reading order alone cannot establish field identity. The helper never supplies or changes business field values, clinical summaries, confidence or review state. Match normalized literal field/source text only inside its original page/region. A unique observed line or adjacent-line block yields bbox_kind=row or block; uncertain, duplicate, low-score or absent matches retain their original coarse source. Do not manufacture character boxes by dividing a line into equal widths.

Run the helper in a short-lived subprocess with an8-second hard wait and explicit cleanup, single CPU request at a time, bounded16-page in-memory line cache by corrected-image hash. No model download occurs at runtime. Helper failure is nonfatal and visibly leaves coarse localization. CPU workers use limited ONNX threads; business model FIFO queues/residency remain unchanged. Both new and old results request localization on demand without changing recognition task budgets, using a new authenticated operator/admin POST endpoint bound to task/run/revision/page, with permission/version checks before image access and another version check after detection. Read-only projections do not migrate or rewrite saved results.

The frontend passes field identity when locating, requests old/coarse coordinates on demand and retains full-page fallback on unavailable/busy responses. Version-bound page results can be reused within the open drawer. Selecting the same or another field creates a fresh source selection, loads its page and scrolls the actual highlighted line after DOM update. Images and overlays share one sized corrected-page wrapper. Stale requests cannot replace a newer selection or revision. Existing missing-field full-page and medical row/cell sources remain supported.

## Decision audit

The [human-review contract](../../implemented/feature/2026-10-08-human-review-and-xlsx-export.md) and [durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md) partially overlap: keep original evidence, version guards, operator permissions and coarse fallback, adding source refinement only. The [layout experiment](../../implemented/testing/2026-09-29-automatic-layout-evaluation.md) warns that detected regions can omit certificate text; use the helper only for localization, never crop recognition input or claim full coverage. The [independent queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) remain active. Medical, export, Mac and auth decisions remain unchanged; automatic clinical grading stays rejected. No note is wholly superseded or archived.

## Alternatives considered

- Change GLM to Paddle: reuses an existing model but both adapters currently return text/input-region coordinates; switching cannot by itself supply field geometry and would change recognition behavior.
- Match detected boxes by reading order alone: needs only detection, but document layouts, skipped lines and repeated values can silently associate the wrong field.
- Re-run GLM for every detected text line: ties coordinates to the same recognizer, but adds many large-model requests and queue latency to a simple positioning action.
- Require users to rerun old documents: needs no new endpoint, but is unnecessary for source positioning and repeats expensive recognition. Use a version-bound read-only old-result projection.

## Acceptance criteria

Reproducing backend and frontend tests fail before the fix and pass after it. Test exact matching, repeated/unknown/missing values, low scores, original-region constraints, dates/identifiers, transformed-image geometry, stale versions, role/CSRF, unavailable helper, cleanup and repeated same-page selection. Real saved diploma/degree/bank corrected images provide separate CPU timing and visual overlays without business-model recognition or task writes; preserve all prior evidence. Frontend typecheck/build and relevant backend suites pass. CUA verifies actual same-page scrolling/highlights and fallback. DDE gates pass; refresh the idle local service only after backup and preserve all task/account/key signatures.

## Risks

The positioning recognizer can disagree with GLM; exact matching intentionally abstains rather than using fuzzy substitutions, especially on long identifiers. Box granularity is a detected text line, not guaranteed character-level precision. Helper inference is an additional CPU cost and must not consume unbounded request/task time. Mac behavior remains unqualified. The old-result localization endpoint returns coordinates for the requested current version and never changes saved human values.


## Rejection evidence

The CPU helper can attach observed positions without changing GLM values. Serial replay localizes59/68 eligible saved diploma/degree fields and0/4 bank-number fields; this is localization coverage, not recognition accuracy or measured box precision. Detection takes approximately0.9–4.3 seconds per sampled page including helper initialization. Evidence and unsuccessful probes are preserved in output/localization-20261009-v1/. No large-model recognition or production task rewrite occurs in the replay.

The user explicitly cancels certificate positioning because it has low business value. Remove the experimental backend endpoint, worker, matching module and helper dependencies from the application; retain the isolated experiment outputs. The narrower [medical navigation fix](../../implemented/bug-fix/2026-10-09-medical-only-source-navigation.md) retains existing medical sources and fixes repeated same-page scrolling without another recognition model. This rejected proposal is not archived or treated as implemented.
