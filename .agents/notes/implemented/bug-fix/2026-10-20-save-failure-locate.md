# Agent Note: Locate save failures by expanding and scrolling to the error block

Status: implemented
Scope: frontend/src/reveal.ts, frontend/src/components/ReviewEditor.vue, frontend/src/components/TaskResultDrawer.vue, frontend/tests/review-save-locate.test.ts, frontend/tests/detail-loading.test.ts, frontend/tests/backpressure-components.test.ts
Last-verified: 2026-10-20

Visual review finding #14 remainder (save failures did not locate the problem); the per-code copy half had landed earlier via the 107e7ac checkpoint batch, this batch lands the locate half. (frontend-handoff next-step candidate)

## Problem

- ReviewEditor's local save validation showed the per-code message next to the save button but never pointed at the offending block: SUMMARY/COVERAGE/MEMBER_SOURCE told the operator to expand a collapsed panel and find it by hand, and an invalid added item left them hunting through the item list.
- The summary-edit / new-members / coverage collapse panels were uncontrolled (no v-model), so no code path could expand them programmatically.
- TaskResultDrawer's server-side save failure (reviewError) renders in the alert fixed at the top of the drawer body: an operator scrolled to the bottom of a long report who clicked save saw loading stop with no visible feedback and was invited to resubmit blindly — the copy literally asks them not to.

## Decision

- New shared helper `revealAnchor(el, { block, flash })` in reveal.ts (scroll with prefers-reduced-motion handling; optional focus handoff plus jump-flash), extracted from ReviewEditor's issue-jump watch so both locate surfaces share one mechanism.
- ReviewEditor: the save catch now calls revealSaveError(code), which maps each validation code to a block (INVALID_ITEM → first offending added row `rev-added-N`, GENERIC_MASKED → `rev-generic`, MEMBER_SOURCE → `rev-new-members`, SUMMARY* → `rev-summary`, COVERAGE → `rev-coverage`), opens the owning collapse through the shared openPanels state, then scrolls and flashes exactly like the red-text issue jumps.
- Panel-dependent reveals wait for the actual expansion layout and discard stale requests as specified in the [expanded-layout correction](2026-10-20-save-locate-expanded-layout.md). `nextTick()` alone does not establish a usable scroll range.
- The three previously uncontrolled collapses are now v-model bound to openPanels; anchor ids ride on the el-collapse-item / h4 roots, which are single-root Element Plus components whose attrs fall through (verified in the compiled EP output, so document.getElementById works on the live DOM even while collapsed).
- Generic masked full_text / key_values now throws GENERIC_MASKED (same copy as MASKED_VALUE) so only the generic section is targeted; MASKED_VALUE from field/item/finding/member changes stays message-only because changedValues can throw from several sites and a guessed target would misdirect.
- SUMMARY_SOURCE / SUMMARY_COUNT / SUMMARY_TITLE sub-codes gained their own copy (they previously fell to the generic fallback line) plus the summary block jump.
- TaskResultDrawer: saveReview's catch scrolls to the top alert (`id="drawer-review-error"`, block 'start', no flash) so the failure reason is on screen no matter how far down the operator was when clicking save.

## Alternatives considered

- Scroll to the message alert instead of the offending block: rejected — the message renders right above the save button where the click happened, so it is already visible; the missing piece was reaching the block to fix.
- Guess a target for MASKED_VALUE field throws: rejected — the throw site cannot be located unambiguously, and a wrong guess misdirects worse than no jump.
- try/catch-guarding revealAnchor for non-browser environments: rejected — tests stub document/matchMedia instead of production code pretending browsers might not exist.

## Verification

- vue-tsc --noEmit exit 0; full suite 299/299 pass (289 before this batch + 9 in the new review-save-locate.test.ts + 1 drawer scroll case appended to detail-loading.test.ts). backpressure-components.test.ts needed the same document/matchMedia globals (surfaced by the suite, fixed in the same batch). vite build exit 0 (chunk-size warning = known noise). Root npm run verify green with this note.
- The initial renderless tests did not verify real scroll geometry. The [expanded-layout correction](2026-10-20-save-locate-expanded-layout.md) records the subsequent failing browser reproduction and passing 9-case real-browser regression; the updated frontend suite passes 306/306.

## Consequences

- A local save rejection now takes the operator to the place to fix: the panel opens, scrolls into view centered and flashes once, with keyboard focus handed to the anchor.
- Server-side save failures are always on screen after the click; the silent-resubmit failure mode is gone.
- The issue jump and the save-failure locate share revealAnchor; future locate surfaces should reuse it instead of re-implementing reduced-motion and focus handling.
- Finding #14 now has real-browser coverage for long expanded panels as well as error mapping; the initial 299-test result alone was insufficient evidence of scroll visibility.
