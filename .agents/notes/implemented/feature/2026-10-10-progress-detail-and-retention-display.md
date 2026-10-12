# Agent Note: Surface measured progress detail and the 7-day retention expiry

Status: implemented
Scope: frontend/src/business.ts, frontend/src/presentation.ts, frontend/src/components/BatchBoard.vue, frontend/tests/business.test.ts, frontend/tests/presentation.test.ts
Last-verified: 2026-10-10

## Problem

The batch board's progress column read the legacy integer `progress` field, which the pipeline filled with fixed stage percentages; users saw a frozen or jumpy bar that looked fabricated, contradicting the no-fake-progress rule (SPEC). Separately, recognition records are deleted 7 days after task creation, but no UI showed when a batch would expire, so users could not tell why older batches disappear.

## Decision

The board consumes the measured progress contract in [the backend progress note](../bug-fix/2026-10-10-measured-task-progress.md). It derives OCR work solely from physical region counts (`processed_regions/total_regions`), never the legacy integer `progress`. The later [phase-aware correction](../bug-fix/2026-10-10-phase-aware-progress-display.md) limits numeric bars to known OCR totals, displays page counts during preparation and uses stage text/activity icons during unknown plans, mapping and validation. Queue has no activity bar; stopped tasks retain counts and incomplete warnings. A tooltip explains page/region breakdown and the difference between work units and time/accuracy. Region totals are rendered verbatim; the frontend adds no estimates or time-based extrapolation.

Batch headers append the retention expiry, derived client-side as `created_at + 7 days` formatted in Asia/Shanghai, labelled 到期清理. The server does not currently expose an `expires_at` field; SPEC documents 7 days as the default retention covering business files, results and run history. If retention ever becomes configurable server-side, the backend must publish the real deadline and this derivation must be replaced — recorded here as the trigger. `parseTask` validates `progress_detail` strictly: non-negative integer counts, nullable totals only, string stage.

## Alternatives considered

The [phase-aware correction](../bug-fix/2026-10-10-phase-aware-progress-display.md) narrows measured bars to the OCR phase, replaces the earlier unknown-total sweep with a Loading icon, and keeps counts visible after stopping. It also enforces the implemented backend DTO rather than accepting partial count objects. This note continues to own the retention label and original component integration; current progress behavior and qualification are recorded in that correction.

- Keep the integer bar with CSS smoothing: hides the fabrication instead of removing it; rejected because the contract explicitly deprecates UI use of `progress`.
- Show a percentage derived from `processed/total` regions only when the plan is complete and otherwise freeze the old bar: still displays a stale number during preparation; the stage word plus indeterminate sweep states the truth without a fake denominator.
- Wait for a backend `expires_at` field before showing any expiry: leaves users blind to a real data-deletion deadline that SPEC already fixes at a 7-day default; derivation is honest today and flagged for replacement above.

## Verification

`npm run typecheck`, the node test suite (new cases: progress_detail accepts measured counts with nullable totals and rejects negative/fractional/typed garbage; expiry text crosses Shanghai date boundaries and returns empty on invalid input) and `npm run build` all pass before landing. Visual states follow runningStatuses: queued text, indeterminate during unknown totals, measured `x/y` once the plan exists.

## Consequences

Bars hold still between region checkpoints and unknown totals never animate toward a number. The phase-aware correction owns strict validation of the implemented backend contract; a future incompatible shape must update parser and display together. The client-side `created_at + 7 days` expiry matches only the default retention; a configurable retention without a published `expires_at` would silently mislabel deadlines, so the backend must publish the real field if retention becomes configurable.
