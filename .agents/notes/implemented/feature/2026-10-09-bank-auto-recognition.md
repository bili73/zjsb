# Agent Note: Recognize bank photos before offering per-file crop recovery

Status: implemented
Scope: ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, backend/ocr_app/business.py, backend/ocr_app/task_store.py, backend/ocr_app/pipeline.py, frontend/src, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-12

## Problem

The mandatory local number-row crop and synchronous GLM admission reject an entire batch when one prediction includes a label or is incomplete. The crop dialog clears all generated crops on the next submission, so the operator has to repeat successful work. The user explicitly requests automatic recognition first and manual cropping only when recognition fails.

## Decision

BANK_CARD accepts decoded single photographs, including full front faces, and cropped rows. Upload does not call a recognizer; encrypted source persistence and independent per-file tasks match the other document families. PDF remains unsupported for this type. Existing successful legacy admission metadata may still be reused by the pipeline when automatic preparation leaves pixels unchanged, but is no longer required. The [certificate/card orientation helper](2026-10-12-certificate-image-upright.md) requires fresh recognition after any quarter-turn or deskew correction, keeping preview and prediction consistent. Mixed OCR text is parsed by existing evidence-bound PAN extraction and offline issuer lookup; unsupported confidence and checks remain unknown.

A missing, conflicting or invalid PAN offers a single-task crop recovery and the existing manual field editor. Recognition of a PAN with unavailable confidence or an unknown BIN does not force cropping. The result drawer reads its version-bound corrected source page, supports actual pixel rotation and submits only the confirmed crop as a new task. The original task and all other tasks remain available. A failed crop upload retains the confirmed File for retry without cropping again. A successful upload returns to the task list. Account permissions, source authentication, source encryption, task version checks and existing required-field export policy remain unchanged.

Full photographs now reach the encrypted server source and OCR attempts; the previous crop-only guarantee is intentionally removed. The application does not add CVV fields or export columns. This is an input-policy change requested by the user, not a claim of universal security-code detection or improved recognition accuracy.

## Decision audit

The [card profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) are partially superseded only for mandatory local crop, pure-number admission and crop-only persistence. Its catalogue, BIN, validation, rotation and frozen manual-crop measurements remain active. The [frontend rebuild](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md), [durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md), [internal presentation](../../implemented/feature/2026-10-08-internal-unmasking-and-review-friction.md) and [review/export](../../implemented/feature/2026-10-08-human-review-and-xlsx-export.md) partially overlap and remain active. Calendar, medical extraction, model queues and hosted authentication decisions are unrelated. No note is completely absorbed or archived.

## Alternatives considered

- Mandatory crops minimize card content reaching the server and make recognition cheap, but require work for every card and reject whole batches on incidental OCR labels. The user explicitly selects automatic full-photo recognition instead.
- Automatic ROI detection before upload could retain a crop-only server boundary, but no qualified local detector exists here and an unreliable locator can omit digits. Use the existing recognizer on the photo and retain evidence.
- Replacing the original task after cropping keeps one list row, but needs new result/source mutation contracts and risks losing the original evidence. Create a new task for one cropped file.
- Reopening the batch crop dialog reuses existing UI cheaply, but repeats already completed crops and unrelated cards. Recover only the selected task and retain its generated crop on upload failure.

## Verified invariants

The [bank ROI orientation repair](../../implemented/bug-fix/2026-10-12-bank-card-roi-orientation.md) adds internal card-region direction evidence without changing upload, PAN extraction or manual crop recovery. The corrected preview and OCR still contain the complete photo; old admission reuse remains conditional on unchanged preparation pixels.

- Upload accepts full-front and row photos without model calls, rejects unsupported PDF and malformed input, and stores authenticated encrypted sources.
- Background recognition extracts a PAN from mixed card text; missing or ambiguous PAN is reviewable rather than a whole-batch admission failure.
- Legacy accepted crop results remain usable. Other document families keep their current admission and queues.
- Browser tests prove automatic upload bypasses cropping, single-file fallback retains other results, rotation remains correct and crop-upload retry does not require a second crop.
- Backend/frontend tests, production activation checks and DDE verification pass.

## Consequences

Full originals and raw OCR contain more personal card content than the previous crop-only workflow. Full-photo recognition accuracy is not qualified by synthetic flow tests. A transport failure can have an unknown upload outcome; the UI must instruct checking tasks before retrying, and the old task must stay intact.


## Release verification

The final backend suite passes477 tests in117.560s, the frontend passes70 tests and typecheck/build. The isolated real HTTP/headless Edge probe passes5 checks with zero page errors, real model calls or production writes: automatic two-photo upload, missing-PAN peer isolation, real rotation and retained crop after a synthetic503, one-crop retry with both original results unchanged, and month/week/day picker selection plus clearing. Its initial attempts expose and then fix the missing Day.js locale registration; failed logs/screenshots remain preserved.

Three native medical reports retain7 source-backed liver measurements each (21 total, page14), catalogue counts9/10/11 and abnormal counts7/6/2, with0 model calls and154 unprocessed image regions. XLSX round-trip and rendered QA verify actual liver results,7/6/2 newline anomaly entries, original string identifiers, EF760E nonmedical headers and unchanged medical blue/orange. This is mapping and layout verification, not new full-report or bank OCR accuracy.

After three idle checks, a consistent SQLite backup and confirmed exit of all12 old owned processes, Windows loopback1.17.0 serves the qualified frontend. Both models are ready. The55 existing tasks encrypted fields, one account and key files retain their previous signatures. Evidence: output/bank-auto-20261009-v1/ and output/biochemistry-export-20261009-v1/. No database migration, original sample rewrite, extra semantic model, Mac qualification, commit or push occurs.
