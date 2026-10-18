# Agent Note: Floating scroll navigation (back to top / jump to bottom)

Status: implemented
Scope: frontend/src/App.vue, frontend/src/components/BatchBoard.vue, frontend/src/components/AccountManagement.vue
Last-verified: 2026-10-16

## Problem

The workbench pages grew long (paginated batch collapse list, audit/account tables); the user asked for a back-to-top and a jump-to-bottom control floating on the right, and for the batch and account pagers to look like the audit one.

## Decision

- App shell gains `el-backtop` (right 32 / bottom 48, default 200px visibility) plus a companion 跳转到底部 circular button stacked above it, styled after el-backtop (white circle, primary arrow, hover tint). The bottom button appears once the page is scrollable by more than ~240px and hides within 160px of the bottom (where it would be a no-op); visibility updates on scroll and resize, listeners are passive and removed on unmount. Both live inside the authenticated `.app-shell`, so the login page stays clean.
- BatchBoard's pager (added by the numbered-pagination round) and AccountManagement's pager get the `background` attribute, matching the audit pager: all three lists now render the identical filled Element Plus pagination.

## Alternatives considered

- One combined FAB with a menu: two taps for the common action; the flat pair keeps both one tap away.
- Show 跳转到底部 unconditionally: on short pages it scrolls nothing; hiding it near the bottom keeps the pair honest.

## Verification

Frontend typecheck, node tests and production build pass; `npm run verify` passes with this note. scripts/probe_numbered_pagination_browser.cjs (batch/account pager DOM) and scripts/probe_operation_audit_browser.cjs remain the acceptance contracts for the pagers; the floating buttons are window-level fixed elements outside those selectors.

## Consequences

The jump button's visibility reacts to scroll/resize events only; content that grows without either (e.g. an in-place expansion with no scrolling) refreshes on the next scroll tick. el-backtop and the companion button sit at z-index 5, below drawers and dialogs, so they never float over the result drawer.
