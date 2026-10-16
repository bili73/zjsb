# Agent Note: Preserve browser operations on the approved HTTP deployment

Status: implemented
Scope: frontend/src, frontend/tests, frontend/package.json, frontend/package-lock.json, scripts, SPEC.md, RUNTIME.md
Last-verified: 2026-10-15

## Problem

The approved non-loopback HTTP deployment lacks Clipboard, crypto.randomUUID and crypto.subtle in Edge, although the same frontend works on Windows localhost. Region text/date copy falls back to manual selection, diagnostic card copy fails, diagnostic creation can itself throw, and upload hash matching silently loses the additional local-original preview. Server previews and accepted tasks are separate and must remain intact.

## Decision

Use the modern Clipboard API when available. Otherwise synchronously attempt selection-based copy inside the user click and active dialog, with temporary text removed and focus restored. A rejected modern write may attempt the same fallback only while the caller's lifetime remains current. A false return or exception is failure, preserving the existing manual selection/download guidance. No write, field application or result persistence is added.

Generate UUID v4 identifiers from getRandomValues when randomUUID is absent, retaining existing server IDs and diagnostic privacy constraints. Preserve SHA-256 content matching with native digest when available and pinned @noble/hashes otherwise; yield between bounded hash chunks so clearing previews can invalidate pending matches. Never match by filename or order.

## Decision audit

- [Region OCR copy](../../implemented/feature/2026-10-13-source-region-ocr-copy.md) and [date suggestions](../../implemented/feature/2026-10-13-region-date-copy-suggestions.md) partially overlap: manual fallback, independent date values and lifecycle fences remain; this extends the automatic HTTP path.
- [Local diagnostics](../../implemented/feature/2026-09-30-local-diagnostics.md) retains safe metadata and current-page limits.
- Proposed/rejected notes have no competing browser capability policy. No note is wholly superseded.

## Alternatives considered

- HTTPS restores standard browser APIs without compatibility code. It also changes certificate/address operations beyond the approved HTTP deployment, so defer it.
- Keep only manual copying: smallest and already safe, but it does not meet the approved one-click goal. Keep it as the final fallback.
- Match previews by filename/order avoids hashing but cannot safely handle deduplication or same-name crops. Preserve content identity with a small pinned hash implementation.

## Testing

The complete frontend suite passes 224 tests and its production build succeeds. New tests cover missing APIs, modern rejection, legacy false/throw, lifecycle invalidation and cleanup; UUID format and server-ID priority; SHA-256 vectors including the 50 MiB upload limit, duplicate filenames and preview invalidation. The complete Windows backend suite passes 854 tests. No model, database, origin or data-key changes are made.

The actual Vue dialogs pass six isolated Edge browser checks: HTTP and localhost in bounded/cinema views, plus diagnostic copy on HTTP and modern-API rejection. Click-and-paste checks preserve Chinese, newlines, leading zeros and date precision. A denied legacy copy selects the existing date field for manual copying. All checks use synthetic values and make zero business API requests. Evidence: output/http-browser-capabilities/attempt-Zi2M8i/report.json. The earlier attempt-GWCtc9 is retained: its four region checks passed before a test selector hit an overlaid dropdown input; the probe now clicks the actual select wrapper. Safari and external Internet routing are not qualified by these component checks.

## Consequences

execCommand is deprecated and browser policy may still deny copying; never claim success without API confirmation. HTTP transport remains unchanged. The hash dependency increases the bundle and must be pinned and packaged offline. A current Edge result does not qualify every browser.
