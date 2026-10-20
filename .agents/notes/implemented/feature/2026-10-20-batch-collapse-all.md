# Agent Note: Collapse all expanded batches with one click

Status: implemented
Scope: frontend/src/components/BatchBoard.vue
Last-verified: 2026-10-20

## Problem

Batches expand one title click at a time and stay open; after working through several batches the board stays a wall of expanded tables, and folding them back requires one click per batch. The user asked for a one-click control that collapses every expanded batch (2026-10-20, during the batch-board declutter pass).

## Decision

Add a 「全部收起」 button in the board toolbar's actions cluster, left of 「刷新」. It renders only while at least one listed batch is expanded (v-if on `expandedNames.length`), so the toolbar gains nothing in the resting state. The click assigns `expandedNames = []`; `expandedNames` is the existing writable computed whose setter folds each entry through `monitor.setExpanded` — the same path the collapse component's own v-model uses, so optimistic entries follow existing semantics with no new state. The adversarial review caught that the setter spanned only `listedIds` while the getter spanned `state.order`, so an expanded batch that had fallen off the current page or date filter left the button a visible no-op; the setter now iterates `state.order` as well, folding every session-known batch (`setExpanded` guards missing entries) and folding stale entries as a side effect of ordinary header write-backs.

## Alternatives considered

- An expand-all/collapse-all toggle pair: expand-all across paginated, not-yet-loaded batches is ill-defined (loading side effects for off-screen groups); the user asked only for collapse.
- Per-date-group collapse headers: finer control but more standing UI; one flat affordance matches the request.

## Verification

vue-tsc --noEmit exit 0; full frontend suite 306/306; vite build exit 0 (known large-chunk warning); root npm run verify green (152 notes). An adversarial three-dimension review (correctness/contract/test-quality, per-finding independent refutation) ran on the combined follow-up diff and confirmed this defect plus an unsynced-copy defect recorded in the trim note; both were fixed before committing. A new mounted regression (batch-board-visuals.test.ts) pins that collapse-all folds a stale off-list expanded entry and that a single-header write-back keeps its own members open; the suite passes 307/307.

## Consequences

Operators can flatten the board in one click during the polling view; the button appears and disappears with expansion state. No API, monitor state shape, persistence or backend change — expansion remains view-local. The renderless test harness does not render templates, so the button wiring is covered by vue-tsc and manual acceptance like the other template-level toolbar changes.

## Related note audit

- [Standing hints trim](../../implemented/simplification/2026-10-20-batch-board-copy-trim.md) is the same-day declutter pass this control belongs to; both touch the board toolbar area without overlapping decisions.
- [Numbered list pagination](../../implemented/feature/2026-10-16-numbered-list-pagination.md) owns the pager; collapse-all deliberately folds only listed batches and does not change paging.
