# Agent Note: Capture serious diagnostics with Chinese explanations

Status: implemented
Scope: backend/ocr_app/diagnostics.py, backend/ocr_app, tests/test_diagnostics.py, tests/test_diagnostic_service.py, frontend/src/components/ServerDiagnostics.vue, frontend/src/serverDiagnostics.ts, frontend/tests/server-diagnostics.test.ts, frontend/public/help/index.html, RUNTIME.md, SPEC.md, openapi.yaml
Last-verified: 2026-10-15

## Problem

The user explicitly narrows diagnostic capture to serious problems and asks for Chinese descriptions. INFO-level normal activity dominates the original log history; English technical codes alone are difficult for operators to understand.

## Decision

Default and invalid OCR_LOG_LEVEL values resolve to ERROR, retaining ERROR and CRITICAL. Explicit existing troubleshooting overrides remain available. Keep the five-level vocabulary for historical lookup; preserve existing raw logs and archives. Routine validation/permission conflicts remain WARNING and therefore are not captured by default. Failure/status alerts and business audit records keep their existing purpose.

Each new record and revalidated old record exposes a Chinese description derived only from fixed event/error/operation dictionaries. Never copy arbitrary exception messages or trust persisted descriptions. Derive legacy record IDs before adding the new display field so existing archive/live deduplication and pagination identities do not change. The UI, expanded details and diagnostic ZIP share the server-provided explanation and retain technical codes/locations.

Historical/INFO behavior is tested under an explicit test-only INFO override; production defaults, invalid configuration, no-error empty history, serious failures and safe Chinese descriptions have independent coverage. The manual and API documentation match. A startup write probe tests the directory without creating an informational record.

## Decision audit

- [Diagnostic archive extension](../../implemented/feature/2026-10-15-diagnostic-levels-and-backup.md): partially changes the default capture policy, with its best original rationale preserved below; archive/authorization/retention mechanisms remain active.
- [Local diagnostics](../../implemented/feature/2026-09-30-local-diagnostics.md): preserve safe context, independent offline collection and existing identifiers.
- Proposed and rejected notes contain no competing severity or localization policy.

## Alternatives considered

- INFO by default gives complete lifecycle and performance context for troubleshooting, but the user prefers fewer, actionable records. Keep it only as an explicit temporary override.
- Filter only in the webpage: easy and retains all context, but still writes the unwanted records and therefore does not meet the capture requirement.
- Store arbitrary translated exception text: can explain unfamiliar errors, but may include document data, paths or credentials. Use fixed Chinese explanations and safe technical frames instead.

## Testing

- Default capture excludes DEBUG/INFO/WARNING and keeps real errors, timeouts and critical service/storage failures.
- All registered event/error types have Chinese explanations; raw exception contents and persisted injected descriptions never escape revalidation.
- Empty error history is healthy; old records preserve identity and receive descriptions in queries/offline downloads.
- Relevant backend/frontend tests, build and DDE gates pass. Local activation must preserve tasks/accounts and must not depend on INFO model-loaded log records as readiness evidence.

The affected backend suites pass 37 tests, the complete frontend suite passes 215 tests and its production build succeeds. Tests cover all registered event/error translations, ignored injected descriptions, stable legacy IDs, both online/offline ZIP descriptions, ERROR/CRITICAL-only default capture, invalid level fallback, empty history and an unwritable startup probe. Evidence remains in output/diagnostic-hardening-20261015/error-only-*.log. No OCR accuracy retest is claimed.

## Consequences

Normal timing/lifecycle evidence is absent by default, so explicit diagnostic overrides may be needed for performance investigations. The current running processes only adopt the new level after restart. This change does not deploy the Mac branch or rewrite/delete historical low-level logs.
