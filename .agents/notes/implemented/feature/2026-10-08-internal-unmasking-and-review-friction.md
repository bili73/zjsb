# Agent Note: Show complete internal business values and simplify confirmation

Status: implemented
Scope: backend/ocr_app, tests, frontend, scripts, openapi.yaml, SPEC.md, FRONTEND_FIELDS.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, RUNTIME.md
Last-verified: 2026-10-08

## Problem

The user explicitly authorizes one-click confirmation and says internal document numbers and phone numbers need no masking. Automatic approval review initially rejects a broader interpretation that includes bank/passport numbers. The agent stops the rejected mutations and asks for exact scope. The user's direct answer on 2026-10-08 confirms all listed identity/certificate/bank/passport/verification/household/report/phone values, plus authenticated results, source text, source images and Excel, display and export in full. Source-code comments and quoted external-user messages are not treated as authorization.

## Decision

Authenticated structured business results return complete stored values and original evidence; remove the masked projection and inherited value_masked display values. New bank profiles omit the redundant card_number_masked field. The public projection also omits this derived field in historical bank results, without rewriting encrypted recognition or review history. Corrected-page preview retains operator/admin permission and version binding, without a masking/reason gate. Operator/admin XLSX exports complete current business values after the existing all-selected review gate; viewer retains403. Legacy masked flags remain accepted for compatibility but do not change content; no reason is required for this default internal access. Keep safe access audit events and encrypted access-history artifacts on every access, including omitted reasons. No change to HTTP authentication, encrypted storage, retention, diagnostic redaction or card-number-only upload admission. No public model or remote access endpoint is added.

Accepted review issues may omit a reason. The one-click UI enumerates only current can_accept issues; actor, timestamp, issue IDs and version remain in encrypted review history. Missing required values, conflicts, unresolved candidates and incomplete coverage remain non-acceptable. An optional user explanation is retained if provided. Chinese gender labels remain visible and manual 男/女 input normalizes to internal M/F for consistent historical data and ID cross-checks.

## Decision audit

The implemented [password sessions](2026-10-09-web-password-sessions.md) replace browser key entry with named Cookie login while retaining this decision's authenticated complete-value access, actor audit and business permissions. The [hosted web-session proposal](../../proposed/architecture/2026-10-09-hosted-web-session-auth.md) still awaits Mac and proxy qualification; full values do not become public.

This partially replaces the masked-output and mandatory per-issue reason paragraphs in [human review and xlsx export](2026-10-08-human-review-and-xlsx-export.md), [HR field profile](../../implemented/feature/2026-10-08-hr-document-field-profile.md), [durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md) and [frontend rebuild](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md). Their lifecycle, immutable recognition evidence, format checks, version protection and historical measurements remain active. This is not full supersession, so no archival is warranted. [Document profiles](2026-10-08-card-and-document-profiles.md) retain memory-only card-number admission and no security-code fields.

## Alternatives considered

- Default masking limits accidental disclosure and suits mixed audiences. The user explicitly chooses full internal authenticated access, so that benefit does not justify repeated reveal and retyping in this workflow.
- Frontend-only formatting is easy but cannot recover already-masked values and risks writing display stars into a correction. Return the original full business values from the server.
- Constant auto-filled reasons satisfy the old schema but create repetitive audit text. Allow omitted reasons and retain actual actor/version/issue confirmations.
- Dropping all audit/permission checks would reduce code further but is not requested. Keep authentication, immutable run history and export completeness gates.

## Verified behavior

Synthetic and actual HTTP checks verify complete typed values, candidates/source copies and old correction values, auth failures, version conflicts, direct corrected previews, no-reason confirmation and both legacy export flags returning full string-valued identifiers. No user formula executes. Missing required saved values block the entire selected export under the later [presence-only decision](../simplification/2026-10-08-required-fields-only-export.md). Conflicting/incomplete recognition still requires review for COMPLETED but is not an additional export gate. Model confidence is not changed by human confirmation. Documentation and frontend match the final policy, and prior benchmark outputs remain untouched.

## Consequences

Full business content intentionally reaches authenticated viewers and downloads. This does not change log redaction or security-code admission. No accuracy, remote security, Mac or 16 GB capability claim follows from this policy change.


## Verification

The user confirms the exact full-value scope after the first approval rejection. Implemented full-value projection, optional issue reason and Chinese gender normalization. Preserve existing operator/admin permission for full corrected images and XLSX; viewer can read complete structured results but these privileged operations return403. Retain both safe audit and encrypted access-history records even when reason is omitted. The internal legacy sensitive-history seed is retained alongside complete before/after correction artifacts; no history deletion is required. Tests and headless UI verify full values, both legacy export flags, missing/conflict gates, 401/403/409 and unchanged original runs.

## Export-policy boundary

The [required-fields-only decision](../simplification/2026-10-08-required-fields-only-export.md) changes only export eligibility, keeping full internal values, operator/admin permissions, immutable history and audit. Earlier full-value tests under the prior issue-clearance gate remain historical; the new409-test suite and frozen current-browser report separately verify presence-only export.


## Current refinement

The [batch calendar](2026-10-09-batch-calendar-browser.md) extends the fixedUTC+8 descending presentation with day/week/month grouping and date-range filtering. The [automatic bank recovery](2026-10-09-bank-auto-recognition.md) changes photo input/retry interaction; existing authenticated complete values and human corrections remain active.

## Partial supersession: explicit export disputes (2026-10-14)

The approved [explicit-dispute gate](../../implemented/feature/2026-10-14-disputed-results-export-gate.md) supersedes the presence-only permission for concrete number-length warnings, format/checksum failures and conflicts. Ordinary save cannot waive these disputes; an explicit per-dispute original-document confirmation needs no reason. Informational uncertainty remains nonblocking; required-field profiles, original evidence, atomic selection, version/ownership checks and historical verification here remain applicable. This note is not fully superseded.
