# Agent Note: Keep source navigation for medical reports only

Status: implemented
Scope: frontend/src, frontend/tests, backend/ocr_app/routes.py, requirements-app.lock.txt, SPEC.md, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-10

## Problem

The user cancels certificate positioning and only needs medical source navigation. The experimental [certificate helper](../../rejected/feature/2026-10-09-certificate-field-localization.md) has not been activated in the production backend. Existing SourcePreview watches the selected page only, so changing or reselecting fields on the same medical page does not scroll again. The default figure margin can displace the image/overlay wrapper.

## Decision

The application has no experimental certificate helper, endpoint or added positioning dependencies. Field-level positioning/source controls appear only for medical reports; all document types retain whole-page image preview and manual editing. Medical primary, related, item, diagnosis and report-finding source controls remain. Each selection creates a fresh source object and independent bbox. SourcePreview responds to selection identity and actual image-load completion, waits for DOM layout, then scrolls to the current highlight or whole-page fallback. A selection counter prevents an older page load from scrolling after a newer click. Selection clears on result-version changes and drawer close. One full-width, margin-free corrected-image wrapper supplies the overlay reference area. Existing sources keep their declared granularity; no coordinates are manufactured. Recognition, review, exports and original sources remain unchanged. No API or database schema addition remains. The frontend-only activation preserves old assets and atomically replaces the index after new resources are copied; the existing backend/models keep running.

The [lazy-page layout correction](2026-10-10-medical-navigation-layout-race.md) extends navigation with cancellable alignment across page reflow. Waiting for the selected image alone is insufficient when preceding pages expand during smooth scrolling. Medical-only controls, source identity, trusted overlays and whole-page certificate previews remain governed here.

## Decision audit

The [human-review contract](../../implemented/feature/2026-10-08-human-review-and-xlsx-export.md) and [frontend rebuild](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) partially overlap: narrow field navigation to medical reports while preserving whole-page evidence preview, version binding and manual entry for all documents. Both decisions remain active; no implemented note is wholly superseded or archived. The certificate proposal is rejected at the user's request, rather than claimed complete.

## Alternatives considered

- Finish the CPU certificate helper: can produce observed line positions for many certificates, but adds latency, dependencies and maintenance for low-priority functionality the user cancels.
- Keep certificate buttons with whole-page boxes: needs no additional backend work, but suggests a precision that certificate sources do not supply. Keep plain page preview instead.
- Remove all source navigation: smallest code surface, but discards medical row/cell evidence the user explicitly retains.

## Verification

72 frontend tests, vue-tsc/Vite and53 focused backend tests pass. CUA passes8 checks with synthetic diploma/household/medical materials and0 browser errors: same-page switching, reselecting after jumping away, missing-box fallback, latest selection after delayed image loading, editable certificate preview without source controls, household-member controls and medical item-row positioning. The isolated server makes0 business-model requests and is stopped.

The original 2026-10-09 activation serves the then-verified frontend asset hashes: API1.17.2 and both models ready without restart.64 tasks,1 account, all task columns/account rows and protected key-file hashes match around that frontend change. Evidence: output/medical-source-navigation-20261009-v1/REPORT.md. Current layout-race activation evidence is owned by the linked correction. The rejected helper replay remains preserved separately and is never described as current recognition accuracy.

## Consequences

Certificate positioning no longer adds latency or deployment dependencies, at the cost of whole-page-only comparison for those fields. Medical navigation retains existing row/cell/region/block granularity; this change improves navigation, not medical recognition accuracy or coordinate extraction. Missing/whole-page sources remain coarse. Real Mac behavior remains unqualified.

The [field-region OCR](../feature/2026-10-13-field-region-ocr.md) adds manually selected transcription for editable scalar fields across document types, without restoring automatic certificate localization.
