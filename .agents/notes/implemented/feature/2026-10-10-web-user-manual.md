# Agent Note: Publish the operator manual inside the workbench

Status: implemented
Scope: frontend/src/App.vue, frontend/public
Last-verified: 2026-10-10

## Problem

The operator manual currently exists only as a Word deliverable under ignored output files. The user requests a webpage and a visible button so users can consult it during upload and review without finding a separate document.

## Decision

A 使用说明 entry beside 诊断 in the authenticated workbench header is available to every account role. The initial separate-tab navigation is partially replaced by the later [embedded-help integration](2026-10-10-embedded-help-integration.md), which owns the current drawer interaction and preserves the underlying workbench state. The existing manual is published as semantic static HTML with a chapter directory, readable narrow-screen layout and seven synthetic screenshots. Vite copies frontend/public/help into dist; the existing backend static mount serves it without new endpoints, routing packages or model requests.

The help page is generic public static documentation, containing no real material, credentials, task identifiers or business API calls. It uses the department-neutral title 使用说明 and addresses operators without emphasizing a specific department. This does not change authentication or access to business results. Its version/date identify the documentation snapshot; future visible workflow changes require updating the page and illustrations together. The [contextual operation guide](2026-10-15-contextual-operation-guide.md) supplements the original seven illustrations with three synthetic tour screenshots and reorganizes task guidance; this static-page and public-content boundary remains active.

The v1.21.0 web snapshot explains the [account lifecycle controls](2026-10-10-account-lifecycle-management.md), [account-owned batches](2026-10-10-account-owned-batches.md), uploader labels and historical/deleted-account attribution, display-name editing, [measured progress](../../implemented/bug-fix/2026-10-10-phase-aware-progress-display.md), batch expiry/deletion and medical result/preview troubleshooting. Role instructions distinguish viewer result access from operator material processing. Name editing and login deletion preserve ownership; a recreated username cannot read the old account's material. Seven synthetic illustrations include the qualified current account-management screen. The earlier neutral Word companion remains the v1.18.0 deliverable; the current in-workbench HTML owns the updated instructions. The embedded integration adds only local presentation script for its return link and active chapter highlighting, without business API calls.

The later [closable image viewer](../bug-fix/2026-10-10-help-image-viewer-close.md) replaces bare image-tab navigation with a native in-page dialog for all seven illustrations. Its visible cross, Escape and backdrop dismissal preserve the reading position; the outer help drawer and public-content boundary stay active.

## Decision audit

The [frontend workbench](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) partly overlaps in header integration and static deployment; its monitor and draft ownership stay active. [Password sessions](../../implemented/feature/2026-10-09-web-password-sessions.md) and [required-field settings](../../implemented/feature/2026-10-10-configurable-required-fields.md) remain the source of the explained login and export rules. The proposed hosted deployment and rejected clinical automation/certificate positioning do not own documentation navigation. Topic and scope searches across proposed, implemented and rejected reveal no previous manual-entry decision to replace or archive.

## Alternatives considered

- Embed the complete manual in a Vue dialog: matches the workbench styling and keeps one tab, but a long manual obscures the material being reviewed and adds application state for static reading.
- Link only to the Word file: reuses the existing layout exactly, but requires download and a compatible document viewer instead of the requested browser-readable explanation.

## Verification

All 87 frontend tests, TypeScript checking and production build pass. The earlier [separate-tab probe](../../../../output/web-manual-20261010-v3/report.json) verifies operator/viewer entry, a null opener, all nine chapters plus quick start, every chapter anchor and six illustrations; the 390px medical table and FAQ have no page-wide overflow. After concurrent drawer integration, the final [real-HTTP probe](../../../../output/account-lifecycle-20261010-v2/browser-report.json) verifies embedded reading, all six images, no popup, no uploads and preservation of the pending file. Desktop/mobile and drawer screenshots are visually checked, with zero page errors, production writes or model calls. The neutral Word companion renders as eleven pages, all visually inspected; no department-specific wording remains in its XML or the HTML. Earlier probe/selector failures are preserved. A read-only local service check returns HTTP200 for /help/index.html. Static help itself needs no new backend endpoint; account lifecycle activation is verified separately.

The later user-requested v1.21.0 text supplement changes only static HTML and adds the existing qualified synthetic account screenshot. Its [publication check](../../../../output/web-manual-20261010-v4/static-report.json) verifies12 internal anchors, nine chapters plus quick start, all seven illustrations over HTTP and exact served/source HTML equality. A browser confirms the three-role table, directory jump, loaded account illustration, readable1280px layout without horizontal page overflow and no console errors. The initial static-check fixture misinterprets the URL-root favicon as a filesystem-relative path; its failure is preserved and browser-style URL resolution corrects the fixture without changing the product URL. The previous served manual is retained before atomic static replacement. No service restart, model request, business-data write or application bundle rebuild is required for this text-only publication; previous functional test results remain historical evidence rather than newly rerun tests.

## Consequences

Operators can read operating instructions beside their work without downloading a separate viewer or losing the active form. Static documentation adds no model startup or API dependency. The HTML is a documentation snapshot and can drift when workflow rules change; maintain its wording and illustrations with relevant workflow changes. Illustrations remain demonstrative rather than real employee data. The static manual is intentionally readable without business authentication, so future additions must retain this generic-data boundary.
