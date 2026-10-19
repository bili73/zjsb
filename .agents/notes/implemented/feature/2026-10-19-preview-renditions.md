# Agent Note: Serve a bounded display preview and retain original evidence pixels

Status: implemented
Scope: backend/ocr_app/preview.py, backend/ocr_app/routes.py, backend/ocr_app/region_ocr.py, frontend/src/api.ts, frontend/src/components/SourcePreview.vue, frontend/src/components/RegionOcrDialog.vue, tests, frontend/tests, scripts/probe_source_navigation_browser.cjs, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-19

## Problem

Preview re-encoding retains all corrected-page pixels, so large scanned pages still cost browser decoding and raster work after client lazy loading and short SQLite writes. On2026-10-19 the user approves display downsampling on Windows main without changing Mac online services or OCR evidence.

## Decision

GET/POST preview accept rendition=original|display, default original. Display returns metadata-free corrected PNG with longest edge at most1800 pixels and unchanged aspect ratio, never upscaling. Original retains existing dimensions. X-Preview-Rendition identifies the response alongside existing stage/revision headers. Resizing remains outside the writer transaction; authorization, owner and version are checked again before publication.

SourcePreview opts into display for its page list. Region OCR and enlarged views explicitly request original; closing or changing context cancels/revokes the enlarged image. Fractional overlays/bbox remain relative to the complete corrected page. RapidOCR continues cropping the stored original, never the display response. Existing callers keep original by default; missing rendition headers from an older server mean original, while an explicit display response cannot satisfy an original request.

The user also approves keeping the local upload section collapsed by default: local image/PDF elements mount only after opening it, and unmount when closed. This prevents a hidden full-pixel local image from erasing the page-list decoding savings.

## Decision audit

[Read-cost fixes](../../implemented/bug-fix/2026-10-19-preview-and-diagnostic-read-cost.md) retain short write locks. [Client scroll work](../../implemented/bug-fix/2026-10-18-source-preview-scroll-performance.md) retains lazy loading, layout and navigation. [Authorization](../../implemented/bug-fix/2026-10-13-api-authorization-boundaries.md) retains final checks. These are partial overlaps; no note is replaced or archived. Topic searches find no conflicting proposed/rejected rendition design.

## Alternatives considered

- Always downsample: smallest server change and helps old clients automatically, but silently reduces enlarged-view quality and changes the existing full-pixel contract.
- Add a persistent rendition cache: can save repeated decode work, but adds ownership, retention and invalidation state before measuring need; generate the explicitly requested rendition first.
- Further client-only optimization: retains server compatibility, but cannot remove full-resolution download and decode cost.

## Testing

Six isolated real-HTTP preview tests pass: dimensions, no upscale, text/EXIF/ICC metadata removal, default/original behavior, GET/POST validation, immutable source bytes, original-resolution normalized crop, and final revocation/revision rejection with staged-history cleanup. Frontend tests verify display/original selection, old-server compatibility, mismatched rendition rejection, original URL cleanup and stale/cancelled responses. The frontend suite passes269 tests and typecheck; its build is staged under tmp rather than served to the running Windows process.

The combined Windows backend suite runs993 tests in462.656s:986 pass and7 are skipped by their existing environment conditions (tmp/preview-checksum-audit-backend-full.log). The final32-test checksum/contract/audit run includes the actual frontend confirm_export_disputes=true save flag, preserving existing actor/time without creating replacement confirmations. [Acceptance evidence](../../../../output/preview-renditions-20261019-164009/ACCEPTANCE.md) collects logs, source hashes and the non-activation boundary.

The browser harness passes16 synthetic checks in output/source-navigation-layout/attempt-bhOS5J, repeated against final source in output/source-navigation-layout/attempt-JeEFTr: collapsed image/PDF elements are absent until expanded, original enlargement uses3000px pixels after1800px list display, closing revokes its URL, and delayed first-click/smooth navigation, resize, cancellation and failures retain their behavior. Both browser/server resources close successfully, with no business API or model call.

The independent synthetic endpoint measurement is [retained here](../../../../output/preview-renditions-20261019-164009/REPORT.md). A2480×3508 textured table becomes1273×1800:8,699,840→2,291,400 pixels (73.7percent reduction),6,407,454→1,689,778 PNG bytes. Three sequential requests per rendition have median0.899s original and0.551s display, including temporary encrypted storage/access-history and HTTP-client overhead. The source hash is unchanged. This is one synthetic sample, not browser-FPS, OCR accuracy or production-throughput evidence.

## Consequences

Small text may be unreadable in the display image; original remains available on demand. The server still decodes the original and this design does not claim a cache or production throughput improvement.

The existing two-request bound applies to background page loading; an explicitly opened original uses its own cancellable request, as the existing region-OCR dialog does. Local files remain available through their session-bound URL but do not mount hidden image/PDF elements while collapsed. No service activation or Mac operation is implied by the isolated tests.

## Windows activation

On2026-10-19 the user explicitly requests restarting the Windows service to try the approved changes. No queued/active task is present and the accepted source hashes match. Typecheck and a fresh isolated production build pass. The verified owned launcher tree is stopped after a consistent SQLite/key/static backup; new assets are copied with index last and old assets retained, then the launcher starts hidden on127.0.0.1:8765 with dual residency.

[Restart evidence](../../../../output/windows-preview-restart-20261019-165010-7b364d/verified.json) verifies all15 table fingerprints,388 tasks,4 users,1 existing session,2 key hashes and4046 referenced-blob size/mtime records against the pre-restart snapshot. SQLite quick_check isok, all16 new static files match HTTP response hashes and anonymous task deletion remains401. No login or password is used to replace an existing session; protected model readiness is not checked by this preservation probe. Mac services remain untouched.
