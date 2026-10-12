# Agent Note: Fit manual illustrations inside a bounded viewer

Status: implemented
Scope: frontend/public/help/index.html
Last-verified: 2026-10-10

## Problem

The user rejects the raw-size manual viewer: it is unnecessarily large and requires scrolling to assemble the full illustration.

## Decision

The entire illustration fits proportionally inside a centered viewer capped at 1000px width and 86 percent of the viewport height. Image scrolling and its explanatory text are removed. The existing cross, Escape, backdrop dismissal and reading-position restoration stay. This correction is explicitly requested by the user.

The [closable viewer](2026-10-10-help-image-viewer-close.md) partially overlaps: only its original-size presentation is replaced. The [web manual](../feature/2026-10-10-web-user-manual.md) and [embedded help](../feature/2026-10-10-embedded-help-integration.md) retain content, drawer and state ownership. Scope and topic searches across proposed, implemented and rejected find no other full-image presentation decision; no note is fully superseded.

## Alternatives considered

- Keep raw-size scrolling: maximizes small-text readability, but contradicts the requested complete view and oversized presentation complaint. The viewer instead fits the image without adding zoom controls.

## Verification

The [browser report](../../../../output/help-image-fit/report.json) checks all seven existing illustrations and their different aspect ratios at the default 1280 by 720 viewport. The modal is 1000 by 619px; object-fit contain preserves the complete image and its aspect ratio without internal scrollbars. Every cross is visible and restores the reading position. Escape also closes correctly. In the 1000 by 640px iframe the modal stays inside its viewport without scrolling; closing restores reading position and preserves the parent draft. One unknown-origin MutationObserver error is retained in the first probe; the manual contains no MutationObserver and the final direct-page check adds no errors. There are no model calls or business-data writes. Static publication retains the previous live HTML and checks exact source/served equality.

## Consequences

Images with a large natural size have smaller text when fitted; the user prioritizes seeing the complete image. This change adds no business API, model call or account interaction.
