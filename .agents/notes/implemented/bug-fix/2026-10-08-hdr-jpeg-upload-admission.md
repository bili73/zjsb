# Agent Note: Admit verified HDR JPEG primary images without losing multi-picture documents

Status: implemented
Scope: backend/ocr_app, tests, scripts, SPEC.md, openapi.yaml, RUNTIME.md
Last-verified: 2026-10-08

## Problem

The reported error e_889edf82c81249b0a1537fc763968205 occurs in upload admission before persistence or OCR. The actual supplied original folder has 34 files: 28 pass and six JPG/JPEG-named files decode as two-frame MPO. Five secondary images explicitly identify the Apple HDR gain-map auxiliary type in XMP; the sixth has ISO 21496-1 APP2 metadata on both images. A seventh HDR source is initially returned as single-frame JPEG by Pillow's Adobe/Google shortcut; explicit MP-index revalidation exposes its two images and identifies the Adobe gain-map XMP profile. Both the upload whitelist and worker single-frame guard reject the original six MPO files. The formerly accepted hidden Adobe JPEG is protected against a compatibility regression introduced by MP-index revalidation. Synthetic browser acceptance used a mock API and did not exercise this decoder boundary.

## Decision

Upload and worker validation share `backend/ocr_app/image_admission.py`. The policy keeps JPEG/PNG/HEIF/HEIC single-image support and allows exactly two-image MPO only when the first MP entry is a baseline primary JPEG and the second is explicitly identified as an HDR gain map through the observed Apple XMP, ISO 21496-1 metadata, or paired Adobe version-1.0 gain-map XMP with a unique Google Primary/GainMap JPEG directory and a declared SDR base; at most one declared MotionPhoto video/mp4 item remains in the original without video decoding. Both images are decoded and bounded before restoring frame zero; OCR uses the primary SDR picture and retains the original unmodified encrypted source bytes/hash. Unknown multi-picture inputs never silently lose frames. No HDR compositing or generic MPO/animated-image support is introduced.

Existing UNSUPPORTED_FORMAT is used for unsupported encoding/multi-picture inputs with a static actionable frontend message, preserving safe diagnostic IDs and excluding arbitrary server prose. Admission byte/pixel/page limits, in-memory multipart, atomic batch rejection and declared-document-type restrictions remain in force. The 33 currently available source files undergo CPU admission; a previously observed ordinary JPEG is absent and remains not_available rather than counted as passing. The six previous failures and the formerly single-JPEG HDR source undergo actual authenticated HTTP acceptance in isolated encrypted storage and page decoding. A new browser probe exercises real routes with synthetic fixtures and no model service.

## Decision audit

The [durable task decision](../../implemented/feature/2026-09-30-durable-document-tasks.md), [diagnostics decision](../../implemented/feature/2026-09-30-local-diagnostics.md) and [temporary workbench](../../archived/feature/2026-10-08-temporary-recognition-workbench.md) partially overlap: retain their storage/privacy/UI rules and link this input-compatibility correction. Runtime scheduling and Mac qualification decisions are unrelated. No existing note owns HDR input handling and no note is fully superseded or archived.

## Alternatives considered

- Accept every MPO primary frame: Pillow already opens it as a primary JPEG, making this very small. A genuine multi-picture document would silently lose other pictures; only positively identified HDR auxiliary images may be excluded from page count.
- Convert source files to ordinary JPEG before uploading: existing admission would work without a backend change. This requires manual work and alters originals; preserve originals and decode the SDR view in memory.
- Decode all MPO frames as pages: this preserves generic multi-picture content. Gain maps are brightness data, not document pages; OCR would waste budget and create false evidence.
- Install an HDR rendering pipeline: this reproduces display brightness. Document OCR needs the existing SDR primary image; extra dependencies and compositing are unnecessary for this fix.

## Testing

- [Original-source v4](../../../../output/original-upload-acceptance-20261008-v4/summary.json) accepts all33 available inputs;7 HDR originals return202 through authenticated actual routes in isolated encrypted storage and decode to one RGB page with exact EXIF-corrected primary pixel equality. All available raw source hashes remain unchanged. A missing previously observed ordinary JPEG stays not_available. CPU-only time5.875 seconds is not model latency.
- The final [actual API Edge attempt003](../../../../output/upload-admission-browser-20261008-v1/attempt-003/REPORT.md) passes9 synthetic cases with11 source hashes unchanged:4 accepted queued tasks,5 rejection scenarios with zero task/blob increments, Chinese static messages, safe diagnostic IDs, one POST and confirmed process/thread cleanup. No models are called. Earlier browser attempts are retained; attempt002 has a comment-only source-hash change and is not the final frozen-source record.
- 284 backend CPU tests pass, including15 dedicated HDR tests;31 frontend tests and its build pass. Negative tests prove rejection of malformed MP fallback, unrelated raw MP types, UTF16/DTD/entity metadata, wrong Adobe namespace/version/base/directory, oversized or truncated images and atomic mixed batches. Apple/ISO/Adobe primary bytes and pixels remain unchanged. MotionPhoto verification is metadata compatibility only.
- The empty current local service is identity-checked and restarted. Both resident models return ready; a synthetic unknown-MPO upload returns415 with no business task added. This is live rejection validation, not document OCR accuracy. [Repair evidence](../../../../output/upload-admission-investigation-20261008-v1/REPORT.md) retains earlier failures and current safe service checks.

## Consequences

Metadata identification preserves valid phone photos without accepting generic multi-picture documents or changing originals. Raw MP types are checked because Pillow folds all unrecognized values into Unknown; JPEG MP indices are rechecked because Pillow can hide auxiliary frames or fall back after malformed metadata. XMP is restricted to UTF8 without NUL/DTD/entity declarations before parsing. Explicit ISO version-zero independent-rational metadata is validated; unsupported profiles remain visible rather than guessed.

HDR identification depends on explicit metadata and the supported two-image profile; unidentified HDR variants require conversion or a later compatibility change. The primary SDR view is used without HDR brightness reconstruction. Upload/decode success does not prove OCR field accuracy. Running launchers require restart to load new Python code. No model weights, medical mapping, confidence, business review/export or Mac deployment changes are made.

The former frontend portion is retired by the [frontend retirement](../../implemented/simplification/2026-10-08-retire-temporary-frontend.md); current Scope covers surviving code. Old UI checks describe historical acceptance.
