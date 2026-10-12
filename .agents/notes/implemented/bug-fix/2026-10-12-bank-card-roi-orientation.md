# Agent Note: Judge bank-card orientation on the detected card rather than its background

Status: implemented
Scope: backend/ocr_app/image_preprocessing.py, backend/ocr_app/documents.py, backend/ocr_app/pipeline.py, scripts/probe_image_upright.py, tests, openapi.yaml, SPEC.md, RUNTIME.md
Last-verified: 2026-10-12

## Problem

The user needs bank photos to turn upright automatically, including two sideways originals on wood-grain backgrounds. Applying the certificate helper to whole photos restores only3/9 nonzero synthetic quarter-turns of three cards. One photo's center and full-photo views disagree; another agrees but scores below the unchanged0.90 threshold. The [read-only exploratory prototype](../../../../output/bank-upright-research-20261012-v1/matrix-prototype.json) restores8/9 rotated inputs and leaves all3 normal controls correct, but is not deployed or held-out OCR accuracy.

## Decision

BANK_CARD uses a dedicated classifier path, selected by an optional internal doc_type keyword on prepare_image. Bounded CPU OpenCV contour analysis operates on a maximum1000-pixel thumbnail: blurred gray dark Otsu, saturation Otsu and Canny masks,7x7 closing, at most20 large contours per mask, then card-like area/aspect/extent filters. The geometric candidate is independent of recognition output. That candidate is cropped in memory solely for orientation evidence; the actual corrected page and OCR source remain the complete photo.

The existing fixed PP-LCNet ONNX classifier retains center/full-view agreement and0.90 score/0.25 margin thresholds. The card crop is tried first. If uncertain, its long side is normalized to landscape and only0/180 classification is accepted; if still uncertain,12 white pixels are added for one retry. Normalization and inferred correction compose modulo360. The number of views is bounded; GLM/Paddle results never guide selection, thresholds are not lowered and no additional model is introduced. When geometry finds no card, the existing full-photo classifier remains the fallback. Uncertain direction preserves pixels and warnings. Small-angle deskew stays the existing conservative full-photo step, with no perspective rectification.

The pipeline passes doc_type through the first preprocessing dictionary and reuses the first decision on pass two, including bank-card-upright-v1 version metadata. Existing warning/score/angle shapes and the changed-pixel legacy-admission guard remain unchanged. Original encrypted inputs, history and manual crop/rotation recovery are preserved. Model execution stays CPU-only, offline, within existing cancellation/deadline checks.

## Decision audit

- [Generic certificate/card preparation](../../implemented/feature/2026-10-12-certificate-image-upright.md) partially overlaps. Its fixed weights, thresholds, full-page pixel contract, EXIF, deskew, two-pass reuse and nonbank behavior remain active; this replaces bank whole-photo-only direction evidence.
- [Automatic bank recognition](../../implemented/feature/2026-10-09-bank-auto-recognition.md) partially overlaps. Upload, crop recovery, legacy prediction reuse constraints and preserved original tasks remain active.
- [Card profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) partially overlaps and retains fields, PAN/BIN validation and frozen measurements.
- [Durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md) partially overlaps and retains encryption, budgets, sources and revisions.
- Rejected certificate field localization remains rejected: an internal orientation crop is not a field-location UI. Medical clinical decisions and proposed Mac/auth changes are unrelated. No note is wholly absorbed or archived.

## Alternatives considered

- Lower the whole-photo confidence threshold: smallest edit and allows more corrections, but weak background-dominated predictions can misrotate valid originals. Keep the same thresholds and improve the direction input instead.
- Recognize four rotations with GLM/Paddle: uses existing recognizers and may resolve ambiguous digits, but multiplies expensive requests and readable/card-valid output does not prove physical orientation. Use only the small CPU direction classifier.
- Add a trained card detector or text-line direction model: likely more robust to diverse backgrounds/layouts, but adds weights and qualification without enough source cards. Start with the existing dependencies and measure geometry failures honestly.
- Crop and perspective-rectify the actual OCR page: removes background and can improve recognition, but may cut digits and changes the approved complete-photo source contract. Use a crop only as direction evidence.

## Verification

The9 new regression tests cover geometric background separation, crop direction, composed quarter-turn/flip, white-padding retry at the unchanged thresholds, low-score/margin/disagreement abstention, full-photo fallback, uncropped preview/OCR identity, single preparation across two passes, doc_type forwarding, nonbank exclusion and cancellation during geometry. The [before log](../../../../output/bank-card-upright-validation-20261012-v1/before-tests.log) retains15 missing-helper errors across9 tests; all9 pass after implementation. The [full backend log](../../../../output/bank-card-upright-validation-20261012-v1/backend-tests.log) records600 passing tests in35.795s, including existing legacy-admission, narrow-strip, PDF and medical/generic exclusions.

The [fresh CPU comparison](../../../../output/bank-card-upright-comparison-20261012-v1/summary.json) freezes the previous helper and uses the same3 stored originals, their18 derived0/90/180/270/±5 inputs, and42 before/after variant records. Original orientation correctness increases1/3 to3/3: both previously failing sideways photos now receive270 and90 degrees respectively, and the upright card stays unchanged. Nonzero quarter-turn recovery increases3/9 to8/9, with1 abstention (sample-01 at180 degrees), zero wrong nonzero corrections and no misrotation/deskew on3 normal controls. All6 added ±5-degree inputs retain conservative no-deskew behavior; arbitrary small-angle correction is not established by this repair. Anonymous [CSV](../../../../output/bank-card-upright-comparison-20261012-v1/cases.csv) retains all rows, failures and timings; encrypted previews and mappings stay outside Git. Original input and saved task result hashes remain unchanged.

Mean helper time is0.068s before and0.098s after on this Windows host. After time includes its own first dependency/model initialization (first0.171s, warm mean0.094s, maximum0.203s); decode/EXIF/PNG/storage/second-pass replay/OCR are excluded. This is preparation overhead, not recognition throughput. There are zero real GLM/Paddle requests, no held-out card/PAN accuracy claim and no Mac performance claim.

The [four real-source integration checks](../../../../output/bank-card-upright-validation-20261012-v1/real-pipeline.json) use actual preparation and synthetic recognizer callbacks for all3 bank originals plus the Xuexin control. They verify expected angles, complete preview pixels, OCR thumbnails, one preparation across two passes, forwarded doc_type, identical attempt/page metadata and the actual TaskResult schema. Source bytes and stored revisions/results remain unchanged. The original before/after previews are also visually inspected in memory.

The [idle service activation](../../../../output/bank-card-upright-activation-20261012-v1/activation.json) backs up SQLite, confirms12 old owned processes stop and restores GLM/Paddle dual readiness. All243 tasks, two accounts, existing database rows, encrypted materials and keys are unchanged. No new preview audit activity occurs during verification; all13 served static assets match and anonymous settings writes remain401. Application/API version stays1.21.0; bank-card-upright-v1 identifies this preparation path without a data migration or history rewrite.

## Consequences

Three horizontal-front bank layouts do not qualify all designs, white cards on white backgrounds, multiple overlapping cards or severe perspective. Contour scoring can select a rectangle that is not a card; require classifier evidence rather than long-side geometry alone. Confidence remains uncalibrated. The existing small-angle estimator may abstain on full-photo backgrounds. Windows CPU measurements are not Mac measurements.
