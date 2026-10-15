# Agent Note: Keep twelve visible cards independently of the type catalogue

Status: implemented
Scope: frontend/src/workbenchEntries.ts, frontend/src/components/UploadPanel.vue, frontend/tests/workbench-entries.test.ts, scripts/probe_account_layout.py, scripts/probe_interview_browser.py, SPEC.md, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-14

## Problem

The interview implementation incorrectly raises the visible-card limit with the thirteen-type catalogue. The user clarifies that the workbench stays capped at twelve and all other cards go into storage. The null/default branch also bypasses the cap.

## Decision

Cap splitEntries at twelve for default, inherited and personal layouts. Preserve order and put every remaining catalogue key in the hidden set, still selectable under More Types. Add-to-workbench cannot exceed twelve; explain the need to tuck a card first when full. Keep reading the existing thirteen-key server preference contract to avoid breaking accounts that saved the preceding version; do not mutate stored data or restart models. Explicit UI edits save only the visible list.

## Related-note audit

[Original customization](../../implemented/feature/2026-10-14-workbench-entry-customization.md) owns the twelve-card requirement. [Account layouts](../../implemented/feature/2026-10-14-account-workbench-layout.md) retain ownership and revisions. [Interview extension](../../implemented/feature/2026-10-14-interview-registration-and-shared-upright.md) keeps all thirteen document types but its display-cap decision is superseded by this correction. No other decision or record is archived.

## Alternatives considered

- Reduce wire validation to twelve too: uniform limits, but rejects existing thirteen-key responses and makes accounts unable to load their layouts. Separate stored compatibility from visible capacity.
- Only cap customized layouts: smallest constant change, but new and inherited-default accounts would still show thirteen cards.
- Rewrite all stored layouts: makes storage match rendering, but needlessly mutates user preferences; render the first twelve and retain the remaining types as hidden instead.

## Validation

Default and explicit thirteen/future-type lists render twelve; excess remains reachable. Legacy thirteen-key responses parse; duplicates and malformed responses still fail. Actual browser checks cover twelve defaults, hidden interview access, full-grid add prevention, tuck/add and account/default persistence. Publish verified static assets without touching accounts, tasks or model processes.

## Consequences

An existing saved thirteenth card becomes hidden. Its type remains usable through More Types and can be moved back after tucking another card.


The183 frontend tests, typecheck and Vite build pass. Nine actual Edge account-layout checks pass, including12 default cards, hidden interview access, add prevention at capacity, tuck/add/reload, account isolation and administrator defaults. The separate interview browser probe uploads through More Types and passes candidate source geometry, manual save, full-field XLSX and authorization checks. [Publication verification](../../../../output/workbench-twelve-20261014-v1/publication/verified.json) confirms13 HTTP static files match and live model processes are unchanged; no backend restart or data migration occurs.
