# Agent Note: Distinguish recoverable audit query and export-limit failures

Status: implemented
Scope: backend/ocr_app/audit.py, backend/ocr_app/api.py, backend/ocr_app/diagnostics.py, backend/ocr_app/diagnostic_messages.py, backend/ocr_app/routes.py, frontend/src/diagnostics.ts, tests, frontend/tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-19

## Problem

INVALID_REQUEST covers invalid audit dates, filters, pagination and export above10000 rows. The frontend intentionally discards raw server messages, so operators do not learn to narrow an oversized export. The user approves dedicated safe codes on2026-10-19.

## Decision

Use AUDIT_FILTER_INVALID for audit list/export filter and paging failures, including FastAPI query validation, and AUDIT_EXPORT_TOO_LARGE when the current export snapshot exceeds10000 rows. Both remain HTTP422, with fixed Chinese backend and frontend descriptions. Non-audit invalid requests keep their existing code; authentication errors retain priority.

Keep default seven-day filtering and no mandatory31-day cap. List total and rows share a snapshot; export uses the same visibility/filter logic in its own snapshot and independently enforces the cap. Options GET stays read-only/idempotent. Export stays single-buffered and revocation is checked before returning; failure returns no successful workbook response, without claiming network delivery is atomic.

## Decision audit

[Numbered pagination](../../implemented/feature/2026-10-16-numbered-list-pagination.md) retains page/cursor compatibility, total and out-of-range empty pages. [Concise action audit](../../implemented/simplification/2026-10-16-account-action-audit.md) retains visibility, encryption and events. These partially overlap; no note is superseded. Proposed/rejected topic searches find no competing audit error decision.

## Alternatives considered

- Add details.reason under INVALID_REQUEST: preserves the code set, but requires new frontend decoding and path-specific presentation; two fixed codes fit the existing safe-message mapping.
- Add a31-day date cap: bounds requested ranges, but prevents useful cross-month audits and does not explain the existing row cap; retain the independent export gate.
- Render raw server messages: requires little mapping code, but bypasses the existing fixed safe error presentation contract.

## Testing

Four isolated HTTP groups pass for malformed/descending dates, filters, cursor/page parameters, mixed pagination, cross-month ranges and empty beyond-end pages. Exactly10000 visible rows export a10001-row workbook including its header;10001 visible rows return422 AUDIT_EXPORT_TOO_LARGE rather than a workbook. Repeated options reads do not add audit events. Non-audit validation remains INVALID_REQUEST, unauthenticated malformed queries remain401, and existing role/revocation tests pass in the109-test combined regression.

Frontend tests confirm both new codes survive safe decoding with actionable Chinese guidance while arbitrary raw server text is discarded.269 frontend tests and typecheck pass. OpenAPI header, operations and Error.code enumeration, SPEC, frontend contract and help document the same behavior; contract tests check rendition schemas and audit codes.

The complete Windows backend suite runs993 tests in462.656s (986 pass,7 existing environment skips), and the final32-test checksum/contract/audit regression passes. A16-check synthetic browser run and an isolated production build pass; the current Windows service is not switched to the staged build and Mac services are untouched.

## Consequences

Older clients may show a generic message for new codes until updated. The frontend and backend should be activated together. A displayed total is not a guarantee for a later export request.
