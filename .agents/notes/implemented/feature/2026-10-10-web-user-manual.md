# Agent Note: Publish the operator manual inside the workbench

Status: implemented
Scope: frontend/src/App.vue, frontend/public
Last-verified: 2026-10-10

## Problem

The operator manual currently exists only as a Word deliverable under ignored output files. The user requests a webpage and a visible button so users can consult it during upload and review without finding a separate document.

## Decision

A 使用说明 entry beside 诊断 in the authenticated workbench header is available to every account role. The initial separate-tab navigation is partially replaced by the later [embedded-help integration](2026-10-10-embedded-help-integration.md), which owns the current drawer interaction and preserves the underlying workbench state. The existing manual is published as semantic static HTML with a chapter directory, readable narrow-screen layout and six synthetic screenshots. Vite copies frontend/public/help into dist; the existing backend static mount serves it without new endpoints, routing packages or model requests.

The help page is generic public static documentation, containing no real material, credentials, task identifiers or business API calls. It uses the department-neutral title 使用说明 and addresses operators without emphasizing a specific department. This does not change authentication or access to business results. Its version/date identify the documentation snapshot; future visible workflow changes require updating the page and illustrations together.

The v1.18.0 snapshot explains the [account lifecycle controls](2026-10-10-account-lifecycle-management.md), including self-service password change, administrator reset/disable/delete, session expiry and retained history. The neutral Word companion and web instructions share the same content; six existing synthetic illustrations remain applicable. The embedded integration adds only local presentation script for its return link and active chapter highlighting, without business API calls.

## Decision audit

The [frontend workbench](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) partly overlaps in header integration and static deployment; its monitor and draft ownership stay active. [Password sessions](../../implemented/feature/2026-10-09-web-password-sessions.md) and [required-field settings](../../implemented/feature/2026-10-10-configurable-required-fields.md) remain the source of the explained login and export rules. The proposed hosted deployment and rejected clinical automation/certificate positioning do not own documentation navigation. Topic and scope searches across proposed, implemented and rejected reveal no previous manual-entry decision to replace or archive.

## Alternatives considered

- Embed the complete manual in a Vue dialog: matches the workbench styling and keeps one tab, but a long manual obscures the material being reviewed and adds application state for static reading.
- Link only to the Word file: reuses the existing layout exactly, but requires download and a compatible document viewer instead of the requested browser-readable explanation.

## Verification

All 87 frontend tests, TypeScript checking and production build pass. The earlier [separate-tab probe](../../../../output/web-manual-20261010-v3/report.json) verifies operator/viewer entry, a null opener, all nine chapters plus quick start, every chapter anchor and six illustrations; the 390px medical table and FAQ have no page-wide overflow. After concurrent drawer integration, the final [real-HTTP probe](../../../../output/account-lifecycle-20261010-v2/browser-report.json) verifies embedded reading, all six images, no popup, no uploads and preservation of the pending file. Desktop/mobile and drawer screenshots are visually checked, with zero page errors, production writes or model calls. The neutral Word companion renders as eleven pages, all visually inspected; no department-specific wording remains in its XML or the HTML. Earlier probe/selector failures are preserved. A read-only local service check returns HTTP200 for /help/index.html. Static help itself needs no new backend endpoint; account lifecycle activation is verified separately.

## Consequences

Operators can read operating instructions beside their work without downloading a separate viewer or losing the active form. Static documentation adds no model startup or API dependency. The HTML is a documentation snapshot and can drift when workflow rules change; maintain its wording and illustrations with relevant workflow changes. Illustrations remain demonstrative rather than real employee data. The static manual is intentionally readable without business authentication, so future additions must retain this generic-data boundary.
