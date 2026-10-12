# Agent Note: Close enlarged manual images without leaving the reading page

Status: implemented
Scope: frontend/public/help/index.html
Last-verified: 2026-10-10

## Problem

All seven manual illustrations open bare image documents in another tab. There is no in-page close control, especially confusing inside the workbench help drawer. The user explicitly requests a visible close cross.

## Decision

Open an illustration in one native modal dialog in the same manual document. Keep a visible 44px close button outside the scrollable image area, support native Escape and backdrop dismissal, and show the image at its original dimensions in a scrollable area. Lock background scrolling while open, reserve the scrollbar gutter and restore focus and the exact reading position when closed. The viewer preserves the underlying workbench draft; no new tabs, navigation, dependencies or business API requests are needed.

The [web manual](../feature/2026-10-10-web-user-manual.md) partially overlaps: this replaces only its image-link navigation, while public generic contents and screenshot assets stay. The [embedded help](../feature/2026-10-10-embedded-help-integration.md) keeps ownership of the outer drawer. Searches across proposed, implemented and rejected find no other image-viewer decision; no note is fully superseded or archived.

The user-requested [fit-image correction](2026-10-10-help-image-fit.md) partially replaces the original-size scrolling presentation above. The current viewer fits the complete illustration within a bounded window. This note still owns closing, focus and reading-position restoration; its earlier scrolling measurements remain historical evidence.

## Alternatives considered

- Keep native image tabs and add instructions to close the browser tab: preserves the browser's free image zoom with no custom viewer, but still lacks the explicit exit requested by the user and separates the image from its reading context.
- Route image clicks through Vue and Element Plus: reuses the application viewer controls, but couples a public static manual to its authenticated parent through a new communication contract. A native dialog works both directly and inside the existing iframe with less code.

## Verification

The [browser report](../../../../output/help-image-viewer/report.json) verifies all seven links open the same dialog without navigation. The cross stays visible while the 1600px-wide raw image scrolls. Cross, Escape and backdrop dismissal restore body scrolling and retain the exact reading position; focus returns to the source link. The iframe check preserves the parent synthetic draft and embedded presentation. There are no console errors, model calls or business-data writes. The first browser check exposed a 61px scrollbar-induced reading shift; its failure is retained before adding the stable gutter and explicit scroll restoration. The preceding live HTML is backed up before qualified static publication, with source/served hash equality checked. DDE verification is required before delivery.

The local served manual also opens and closes correctly with the cross visible, and its [screenshot](../../../../output/help-image-viewer/close-button.png) is retained. DDE verification passes for 57 notes; the changed files pass the whitespace check. The temporary static probe is stopped after acceptance.

## Consequences

Native modal support is confirmed in the current browser. Raw-size large images require scrolling; the toolbar explains this and remains outside that scrolling area. Existing outer help-drawer behavior remains independent. A browser with JavaScript disabled retains the ordinary image link fallback.
