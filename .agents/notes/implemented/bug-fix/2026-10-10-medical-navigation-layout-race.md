# Agent Note: Keep a selected medical source visible while lazy pages settle

Status: implemented
Scope: frontend/src/components/SourcePreview.vue, scripts/probe_source_navigation_browser.cjs
Last-verified: 2026-10-10

## Problem

The selected image can finish before earlier lazy pages. Expanding those pages during smooth scrolling invalidates the scroll destination. A synthetic eight-page browser probe reproduces an off-screen fifth-page highlight with three different image response orders; the component scrolls only once. Waiting for the selected image alone does not guarantee stable page geometry.

## Decision

SourcePreview keeps the latest medical source as a cancellable navigation intent. After its image loads, it scrolls to its highlight or existing whole-page fallback. Page-load and preview-size changes coalesce into animation-frame alignment. The initial correction uses immediate scrolling for later alignments to avoid retaining a destination calculated before reflow; this animation choice is partially replaced by [smooth medical navigation](2026-10-10-smooth-medical-source-navigation.md), which owns current movement. New selections replace old intent. Manual wheel, touch, pointer or keyboard interaction with the preview viewport, explicit page jumps, reloads, result-version changes and unmount cancel it, including an already scheduled frame. ResizeObserver tracks the page list and preview wrapper, and all observers/listeners are removed on unmount. There is no unconditional animation loop or fixed loading delay. Loading-state changes can request alignment but do not start another fetch, so a failed selected preview retains its explicit retry control instead of repeatedly fetching from its status watcher. Preview loading stays lazy and source coordinates, recognition, saved results and exports do not change.

## Decision audit

The existing [medical-only navigation](../../implemented/bug-fix/2026-10-09-medical-only-source-navigation.md) remains active for source selection identity, version binding, overlay trust and certificate whole-page previews. This correction adds layout tracking and explicit cancellation; it does not reverse that decision or revive the rejected certificate helper. The frontend monitor and review contracts remain unchanged. Scope/topic searches find no competing layout-stabilization proposal to retire.

## Alternatives considered

- Wait a fixed number of seconds before scrolling: smallest timing patch and may hide the observed race, but neither fast nor slow preview requests have a fixed completion time.
- Load all PDF pages before enabling source controls: guarantees known heights once decoding finishes, but delays a simple field lookup and discards lazy loading for long reports.
- Rely on browser scroll anchoring: needs no extra component state and preserves the target when images expand after scrolling, but the reproduced expansion during smooth scrolling defeats it.

## Verification

The repository browser probe exercises the actual Vue component and real Edge with eight synthetic pages. The [failing baseline](../../../../output/source-navigation-layout/attempt-UMODxh/report.json) retains all three initial-click races and the original component hash. The [corrected run](../../../../output/source-navigation-layout/attempt-law5KA/report.json) passes all eleven initial checks: three response orders, latest selection after an older response, same-page reselection, manual wheel and jump cancellation, whole-page fallback, version/unmount cancellation and failed-preview retry. It records zero page errors, business API requests and model calls; owned preview/browser resources are closed. Highlight screenshots are visually checked.

The [final twelve-check run](../../../../output/source-navigation-layout/attempt-7OZPP9/report.json) repeats those checks and adds preview-width reflow without any new image-load event, verifying ResizeObserver alignment independently. All twelve pass with the same component hash, zero page errors/business requests/model calls and closed owned resources.

All 87 frontend tests, TypeScript checking and the production build pass. A separate [real-HTTP built-workbench run](../../../../output/source-navigation-layout/integration-3885b592d4904d0181838c867ef53040/report.json) verifies the actual TaskResultDrawer with an independent synthetic eight-page PDF/account/store and delayed previews. The first click reaches page five, then another field reaches page seven. Both highlights are inside the preview pane, the screenshot is visually checked, and there are zero page errors, production writes or model calls. The only HTTP mutation is the synthetic login. Its service/browser are stopped.

The [local activation](../../../../output/source-navigation-layout/activation.json) serves the same qualified index hash and matching referenced asset hashes. Old assets and the previous index backup remain available. API version stays1.18.0, both models stay ready, task/account table fingerprints match around the idempotent activation check, and no backend restart occurs. The initial post-activation diagnostic fails on the Windows GBK default when reading UTF-8 HTML; its record remains, and explicit UTF-8 fixes the diagnostic without a product-code change.

## Consequences

An early field click remains effective while preceding lazy images expand, without loading the entire report first. The selected source stays anchored across observed layout changes until explicit browsing or another selection cancels the intent; cancellation avoids fighting the user and invalidates queued work. Observation is event-driven rather than a continuous frame loop. This qualifies the tested Windows Edge/component/built-drawer behavior; Mac/Safari and touch hardware are not independently qualified. Existing source granularity and medical interpretation remain unchanged.
