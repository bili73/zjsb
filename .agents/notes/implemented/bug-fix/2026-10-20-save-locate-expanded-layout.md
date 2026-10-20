# Agent Note: Wait for the expanded review panel before locating an error

Status: implemented
Scope: frontend/src/components/ReviewEditor.vue, frontend/tests/review-save-locate.test.ts, scripts/probe_review_save_locate_browser.cjs
Last-verified: 2026-10-20

## Problem

The [save-failure locate decision](../../implemented/bug-fix/2026-10-20-save-failure-locate.md) maps validation errors to the correct anchor, but `nextTick()` only commits the opening state. Element Plus schedules its height transition in animation frames. A long panel still has its collapsed scroll range when `scrollIntoView()` runs, so the browser clamps the requested scroll. A synthetic 30-item medical report reproduced this in both motion modes and in the real result drawer; drafts remained intact and no save request was sent.

## Decision

ReviewEditor keeps the existing error mapping and shared scroll/focus helper. It lets the panel enter frames start, awaits the target panel's actual animations and the resulting layout, then reveals its anchor once. Issue jumps use the same sequencing. A newer request, a new save or editor unmount invalidates pending reveals; disconnected or collapsed targets are never revealed. Smooth and reduced-motion behavior stay unchanged.

## Alternatives considered

- A fixed delay is small and needs no animation API, but it guesses when the layout is ready and can drift with CSS durations or machine load.
- Disabling collapse transitions removes the race entirely, but changes normal panel interaction unnecessarily.
- An `after-enter` listener would match Vue transitions directly, but the installed Element Plus collapse item does not expose that event. Avoid patching the dependency or depending on an event it never emits.

## Verification

- The targeted renderless test suite reproduces the timing/lifecycle defect before the change (9 pass, 7 fail), then passes all 16 cases. The full frontend suite passes 306/306; `npm run build` passes typecheck and Vite build, retaining the existing large-chunk warning.
- `node scripts/probe_review_save_locate_browser.cjs` uses real Vue/Element Plus in headless Edge, 30 synthetic medical items and an isolated local Vite server. All 9 cases pass in `output/review-save-locate/attempt-bfxdrw/browser-report.json`: both motion modes, summary error, valid revisioned save, server error, actual medical drawer, issue jump, newer jump and unmount. It records one scroll per valid reveal, no running panel animation when scrolling, preserved drafts, zero browser errors and zero business API/model calls.
- The original pre-fix browser failures remain in `output/frontend-regression-20261020-1792468218179`. The first post-fix run (`attempt-ZIHBoU`) still sampled smooth scrolling at a fixed 1.1 seconds while the 17,000-pixel scroll was in progress; its failures are retained. The permanent probe waits for actual viewport arrival instead of guessing a duration, and still requires exactly one scroll call.
- The probe accepts `PLAYWRIGHT_MODULE_PATH` and `EDGE_PATH` overrides, uses existing local tooling without adding a production dependency, and creates a fresh evidence directory for each run.

## Consequences

Error targets now use the expanded scroll range, so a long panel cannot clamp the scroll to its former collapsed maximum. Waiting costs the real expansion duration plus rendering frames, rather than a hardcoded delay. The timing bridge depends on the installed Element Plus wrapper structure and browser animation API; the retained real-browser probe guards future transition changes. Renderless component tests alone cannot establish scroll visibility. No save validation, backend API, model runtime, Mac service or existing result/correction data changes.

## Related note audit

- The existing save-failure locate note owns error mapping, focus and server-error behavior; it remains active and is refined by this timing correction.
- The review-usability feature note concerns broader review interactions and remains active; no decision is replaced or archived.
