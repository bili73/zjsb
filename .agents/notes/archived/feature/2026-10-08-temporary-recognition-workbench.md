# Agent Note: Add a temporary source-comparison workbench for recognition testing

Status: implemented
Scope: frontend, RUNTIME.md, scripts/probe_workbench_browser.cjs
Last-verified: 2026-10-08
Archived: 2026-10-08

## Problem

The user requests a simple usable frontend to test recognition before a later UI rewrite. Existing Vue components already support authenticated three-type upload, polling, cancellation/rerun, partial results and diagnostics. Rebuilding those flows would add cost without improving verification. Results are long and have no original comparison, medical row source locations are not displayed, and cancelled/rerun waiting notices can remain after the operation finishes.

## Decision

Reuse the existing same-origin business API and components. Add a local-only source preview tied to the explicit task IDs returned for the most recent uploaded batch, using the submitted files in request order and checking count/identity consistency. Retain at most one submitted batch of object URLs and revoke replacements, logout and unmount. Do not match private filenames or recover a source for older tasks by guessing. A result source page can select that page in the browser PDF viewer; image preview is the original selected image without claiming corrected-source bbox alignment. Unavailable HEIC/browser preview remains an explicit fallback.

Allow selected files to be removed before upload; manual task selection and upload navigate to the detail without polling stealing scroll. Medical name/alias/category search and local status filters operate only on the returned items, displaying matched/returned counts without filling null coverage stats. Show medical row source pages. Keep successful results NEED_REVIEW and preserve confidence unavailable. Server-masked numbers remain masked; local original display is not a backend reveal/preview API.

Fix operation notices so a previous cancellation or rerun wait is not shown for a completed/new execution. Add brief startup/key instructions and the temporary test label. Preserve authentication, bounded read retries, run/revision guards and diagnostic redaction. Do not implement business editing/export, server-side preview, additional document admission or remote deployment in this slice.

## Decision audit

The [durable task decision](2026-09-30-durable-document-tasks.md) partially overlaps and retains API, masking, version and review semantics. The [local diagnostics](2026-09-30-local-diagnostics.md) retain safe errors and exclude materials/keys. The [runtime lifecycle](../architecture/2026-09-29-local-dual-model-lifecycle.md) retains serial startup and supervision; separate [independent queues](../architecture/2026-10-08-independent-model-queues.md) own cross-model inference. The [Mac proposal](../../proposed/architecture/2026-10-08-mac-studio-inference-service.md) remains unimplemented. Nothing is absorbed or archived.

## Alternatives considered

- Replacing the frontend framework or adding a component library can improve long-term UI consistency. The user explicitly intends a later rewrite, so retain the current lightweight components.
- Implementing full authenticated backend preview/reveal would support historical tasks and complete identifiers. It needs artifact permissions, masking and audit contracts; local supplied-file comparison gives immediate utility without representing those endpoints as implemented.
- Keeping every uploaded file enables comparison across all session history. Its retained memory grows with uploads; keep only the most recent submitted batch and clearly explain that limit.
- Displaying file-list length as full coverage is convenient. The server has not proved full medical coverage, so retain null stats and label local returned-item counts separately.

## Testing

- All31 frontend tests and TypeScript/build pass. New tests cover task ID association, URL lifecycle, invalid geometry, filters and operation notices, preserving masks/null confidence/stats.
- [Final browser attempt003](../../../../output/workbench-browser-20261008-v1/attempt-003/summary.json) passes12 synthetic Edge checks with0 pageerrors: removal, identical filename/explicit ID mapping, decoded PNG blob hash/size, page requests, projection filters, notices, URL cleanup, unsupported preview, no guessed historical source and no automatic write retry.390px viewport has no whole-page horizontal overflow. Earlier attempts001/002 remain separate; none uses private real material or real Key.
- Browser API is synthetic; these checks do not qualify real backend recognition or model concurrency. PDF#page/input association is verified, but the Edge plugin's final rendered page is not independently verified. Screenshots and limits are in the [browser report](../../../../output/workbench-browser-20261008-v1/REPORT.md).
- Existing input/storage/older measurements remain outside this UI change. DDE verification runs separately at delivery.

## Consequences

Browser PDF and HEIC support varies. Native PDF page selection cannot prove corrected bbox alignment. Refreshing loses local originals and the API key; task results persist through the existing service. This UI remains a test slice, not complete human review or export. Cross-model concurrency is a separate scheduling decision.

The [HDR JPEG admission repair](../bug-fix/2026-10-08-hdr-jpeg-upload-admission.md) shares upload/worker image validation, preserves encrypted original bytes and replaces generic unsupported-image errors with actionable safe format rejection. Its actual-route browser acceptance supplements the earlier synthetic mock API checks; admission success is separate from OCR accuracy.
