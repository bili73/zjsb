# Agent Note: Source preview scroll performance and bbox overlay positioning

Status: implemented
Scope: frontend/src/components/SourcePreview.vue
Last-verified: 2026-10-18

## Problem

The user reported janky scrolling on the medical-report detail drawer (体检报告详情页上下滑动卡顿). Measurement with a scripted-scroll harness (tmp/perf-drawer.cjs: real components, 12 canvas-generated A4 pages at 2480×3508, 40 medical items; metrics = rAF gaps, longtasks, layout-shift) showed:

- Zero long tasks on both scroll surfaces — the main thread is never the bottleneck, so this is not a Vue/render-loop problem.
- Layout-shift score 0.138 on the left page list during a single down-up scroll: pages lazy-load into a 160px skeleton/holder and then grow to full page height on image load, pushing all content below down mid-scroll (scrollbar jumps, content moves under the operator = perceived 卡顿, amplified by real network latency on multi-MB scans).
- A related latent bug: `.bbox-overlay` is `position: absolute` but no ancestor up to the drawer establishes the containing block, so the red source-highlight box was positioned against the drawer, not the page image — misplacing the overlay whenever a field is located on a page.

## Decision

- All page placeholders share one A4 aspect-ratio reservation: `.img-wrap`, `.page-holder`, `.page-skeleton` get `aspect-ratio: 210 / 297`, and `.page-image` fills the reserved box (`height: 100%`). The list reaches final height before any bytes arrive, so image completion causes zero shift; the scrollbar is accurate immediately.
- `.page-item` gets `content-visibility: auto; contain-intrinsic-size: auto 820px` — offscreen pages skip layout and paint entirely, so long reports cost little to scroll. The existing IntersectionObserver lazy-load still fires (placeholder boxes keep geometry valid), and `scrollIntoView` (跳页/定位) forces layout as needed.
- `decoding="async"` is set on both `el-image` variants (attrs pass through to the inner img), moving full-size PNG/JPEG decode off the main thread where the browser supports it.
- `.img-wrap` gets `position: relative`, anchoring the red bbox overlay to the page image it belongs to.

## Alternatives considered

- Shrink or downscale preview images server-side (smaller preview rendition): the real fix for decode/raster cost, but backend-owned (preview.py) — flagged for the backend agent; the client-side changes here are correct regardless.
- Virtual scrolling (render only a window of pages): rejected — the existing IntersectionObserver lazy-load plus content-visibility achieves the same skip-offscreen-work effect with far less churn to the page-list DOM and scroll restoration.
- Reduce the lazy-load rootMargin (150% → smaller) to load fewer pages ahead: rejected — pre-loading pages before the operator arrives is deliberate; with stable aspect-ratio placeholders there is no longer a jump penalty for it.

## Verification

Perf harness re-run after the change: layout shift 0.138 → 0 on the left list (0 on body both runs), long tasks 0 throughout, body-scroll dropped frames 1 → 0. rAF-gap count on the image-list run rises only because stable placeholders lengthen the scroll distance and put more pages in the preload zone (12 images decoded vs 8); decode is off-main-thread and dominates only in headless software rendering. The 15-screen UX audit harness re-rendered without page errors (SourcePreview error/holder/loaded paths intact); frontend typecheck, 246 node tests, production build and `npm run verify` pass with this note. Screenshot of the stressed drawer confirms images letterbox correctly inside the reserved A4 boxes.

## Consequences

- Scrolling no longer reflows the page list when images finish loading; the perceived jump/卡顿 driver is gone. Remaining scroll cost is image decode/raster, which is hardware- and image-size-bound; if operators still see heaviness on very large scans, the next lever is a downscaled preview rendition from the backend (preview.py), not more frontend work.
- Non-A4 materials (square photos, landscape pages) now reserve an A4 box first and settle to the true aspect on load — a one-time small shift for those types instead of the current always-shift behavior; medical reports and scans (the dominant case) are A4 and see none.
- The red source box now lands on the located region of the correct page instead of a drawer-relative approximation. Any code that relied on the old mispositioned overlay (none known) would see the overlay move.
- `content-visibility: auto` skips paint for far-offscreen pages; find-in-page and scrollIntoView still work (the browser forces layout), and IntersectionObserver continues to gate network loads.
