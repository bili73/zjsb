# Agent Note: Preserve smooth movement when medical source geometry changes

Status: implemented
Scope: frontend/src/components/SourcePreview.vue, scripts/probe_source_navigation_browser.cjs
Last-verified: 2026-10-10

## Problem

The user confirms that the [layout-race correction](../../implemented/bug-fix/2026-10-10-medical-navigation-layout-race.md) reaches the selected medical source on the first click, but its immediate corrective scroll interrupts the visible animation. The user requests both one-click arrival and smooth movement.

## Decision

The existing latest-selection intent, lazy loading, layout observation, scheduled-frame cancellation and manual-browsing cancellation remain active. Every alignment, including one triggered by page expansion, requests native smooth scrolling toward the latest observed geometry. An immediate correction no longer interrupts the visible movement; the obsolete first-position flag is removed. Actual intermediate scroll positions and final arrival are verified in addition to the smooth-scroll option. No model, recognition, saved result or backend changes are involved.

## Decision audit

This partially replaces the immediate-correction choice in the [layout-race note](../../implemented/bug-fix/2026-10-10-medical-navigation-layout-race.md). Its source/version safety, explicit cancellation, lazy loading and failed-preview retry decisions stay active. [Medical-only navigation](../../implemented/bug-fix/2026-10-09-medical-only-source-navigation.md) retains control visibility and trusted overlay rules. No note is wholly superseded or archived; scope/topic searches reveal no separate competing animation decision.

## Alternatives considered

- Keep immediate corrective scrolling: already passes first-click and late-layout arrival checks, but interrupts the animation the user explicitly prefers.
- Add a custom frame-by-frame scrolling engine: gives complete control over duration and retargeting, but duplicates browser scrolling and adds lifecycle/state code before native smooth retargeting has been tested.
- Wait a fixed delay before one smooth scroll: reduces early retargeting with a small patch, but preview completion has no fixed timing and slow pages can still invalidate the destination.

## Verification

The [immediate-correction baseline](../../../../output/source-navigation-layout/attempt-Ktiswz/report.json) fails all three cold-navigation smooth-only assertions, while retaining the previously qualified arrival behavior. The [corrected thirteen-case run](../../../../output/source-navigation-layout/attempt-EOmDSE/report.json) passes the three delayed-page response orders, last-selection safety, reselection, width changes, manual wheel/jump cancellation, fallback, version/unmount cancellation and preview failure. Warm navigation traverses8504 pixels and records36 distinct intermediate positions between10% and90% of its travel, without a single-frame jump exceeding40% of travel. It reaches the target. There are zero page errors, production API requests or model calls, and owned browser/server resources close.

All87 frontend tests, typecheck and production build pass. The [built-workbench HTTP run](../../../../output/source-navigation-layout/integration-b8ee0f81506744058bcfd36d67a724b4/report.json) verifies actual drawer first-click arrival on page five, switching to page seven, and smooth-only navigation calls. It uses an independent synthetic account/store/eight-page PDF, records no page errors or production/model writes, and closes its owned resources.

The [local activation](../../../../output/source-navigation-layout/activation-smooth.json) serves the qualified index and referenced asset hashes. Old resources and the prior entry backup remain available. API stays1.18.0, both models stay ready, task/account fingerprints match before/after, and no backend restart occurs.

## Consequences

First-click automatic alignment remains functional in the tested loading orders while movement stays smooth. Native retargeting converges in the regression cases, so a custom animation engine or destination-deduplication state is unnecessary. New layout events may extend the animation until geometry settles; this preserves lazy loading rather than waiting for the entire report. Browser acceptance qualifies the tested Windows Edge rather than promising untested browser behavior.
