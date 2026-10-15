# Agent Note: Export disputes section removed from the result drawer

Status: implemented
Scope: frontend/src/components/TaskResultDrawer.vue
Last-verified: 2026-10-14

## Problem

The drawer's 导出前核对 section rendered `result.export_disputes` as a large amber card (heading, blocking explanation, one row per dispute with a 确认与原件一致 exception button). The user asked to delete it outright ("把这个东西删了"); the preceding round had already moved their preference toward the in-field red validation hints (`number-length-hint`) as the way such situations should surface.

## Decision

The section, its `confirmDispute` handler (confirmed_disputes review path) and its scoped CSS are removed. The primary remedy for a dispute is unchanged and fully intact: fix the field (pick the candidate or fill the correct value) and save — validation re-runs and the dispute clears, unblocking export. What is lost is the exception path: a dispute the operator judges to be a false positive could previously be confirmed as consistent with the original to allow export without changing the number; with the UI gone, backend `export_ready=false` for such tasks has no in-product remedy. The strongest reason for the section was exactly that exception path; it is removed because the user weighs the box's visual cost above it and the in-field red hints already explain what to fix. The `export_disputes` data contract (`business.ts`) and the server flag stay untouched, so restoring a (restyle) UI later needs no backend change. BatchBoard's dispute counts/filters keep working off task fields.

## Alternatives considered

- Keep but restyle as a slim red line: superseded by full removal at the user's explicit instruction after the styling round.
- Move the exception button next to the in-field red hint: keeps the clutter the user wants gone; revisit if operators hit unresolvable false-positive disputes.

## Verification

Frontend typecheck, node tests and production build pass; `npm run verify` passes with this note.

## Consequences

Tasks whose disputes are false positives can no longer be export-unblocked from the UI; if that surfaces in practice, the fix is a lightweight dispute indicator at the field level (red hint + confirm link) rather than resurrecting the card. No contract change: `export_disputes` still arrives and `export_ready` still governs the export button's disabled reason.


## Save interaction update

[Save-as-review](2026-10-14-save-confirms-export-disputes.md) partially supersedes the separate confirmation interaction: the bottom save now carries explicit acknowledgment in the same transaction. Existing export gates and removal of the standalone panel remain.
