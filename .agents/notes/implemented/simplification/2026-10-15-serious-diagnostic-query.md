# Agent Note: Limit product diagnostic queries to serious events

Status: implemented
Scope: backend/ocr_app/diagnostic_service.py, backend/ocr_app/routes.py, frontend/src/serverDiagnostics.ts, frontend/src/components/ServerDiagnostics.vue, frontend/tests, tests, SPEC.md, RUNTIME.md, openapi.yaml, frontend/public/help/index.html
Last-verified: 2026-10-15

## Problem

ERROR/CRITICAL-only capture is already the default, but the UI still offers five severity levels and unfiltered queries/downloads include old lower-level records. The user explicitly requests just the two serious levels and preservation of existing data.

## Decision

Expose only ERROR and CRITICAL in product filters and records. The empty filter means both serious levels. Apply the restriction before pagination and ZIP construction in the shared service record iterator; reject low-level filter values in HTTP validation and direct service calls. Preserve raw/archived files, identifiers, low-level parsing, offline collection and explicit troubleshooting capture overrides. This changes visibility, not log retention or severity classification. Administrator authorization and partial-result/truncation signals remain unchanged.

## Decision audit

- [Error-only capture](../../implemented/feature/2026-10-15-error-only-chinese-diagnostics.md) partially overlaps; its original five-level historical lookup is narrowed for the product, while safe descriptions and capture remain.
- [Archive/query policy](../../implemented/feature/2026-10-15-diagnostic-levels-and-backup.md) and [recovery](../../implemented/bug-fix/2026-10-15-queued-retention-and-diagnostic-recovery.md) retain backups, privacy, permissions and partial-result semantics.
- No proposed/rejected note specifies a competing two-level product policy. Nothing is archived.

## Alternatives considered

- Remove only three dropdown options: the smallest UI edit, but old INFO records would still appear in default results and downloads.
- Delete or relabel old lower-level records: makes storage look uniform, but destroys or falsifies retained evidence. Filter at the product read boundary instead.

## Testing

The targeted diagnostic service/recovery suites pass 32 tests; the complete Windows backend suite passes 854 tests and the complete frontend suite passes 224 tests. Mixed-severity live and archived fixtures produce only ERROR/CRITICAL in lists, pages and ZIPs; exact filters still work, and low-level filters return 422. Tests compare raw/archive bytes before and after queries. Recovery fixtures now explicitly contain serious events so partial-result and truncation checks remain meaningful under the new read policy. Browser checks confirm exactly two translated choices. The production frontend build succeeds.

## Consequences

The web UI intentionally no longer retrieves historical low-level diagnostics; maintainers can still use preserved files and offline collection. Stale clients requesting an obsolete level receive an explicit validation error and should refresh.
