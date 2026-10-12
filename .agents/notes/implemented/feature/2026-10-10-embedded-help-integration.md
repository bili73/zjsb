# Agent Note: Preserve the concurrent in-page help integration

Status: implemented
Scope: frontend/src/App.vue, frontend/src/components/HelpDrawer.vue, frontend/public/help
Last-verified: 2026-10-10

## Problem

During the approved account-lifecycle implementation, a concurrent frontend owner changes the help entry from a separate tab to an embedded drawer and adds the HelpDrawer component. Overwriting that work would discard the user's parallel frontend changes. Account controls and existing upload/review state must continue working with the current interface.

## Decision

Preserve the concurrent HelpDrawer integration and qualify the current build with fresh synthetic real-HTTP account acceptance. The drawer embeds the same generic static manual in an iframe and unmounts its frame when closed; opening/closing it keeps the underlying workbench mounted. Reading help does not submit pending upload files or open a new browser tab. The embedded manual hides the redundant return-to-workbench link. The separate /help/index.html URL remains readable directly. This change partially replaces only the header-navigation choice in the [web manual decision](2026-10-10-web-user-manual.md); neutral wording, generic public contents and screenshots remain active. The [account lifecycle decision](2026-10-10-account-lifecycle-management.md) remains unchanged. No note is wholly absorbed or archived.

The later [closable manual-image viewer](../bug-fix/2026-10-10-help-image-viewer-close.md) operates locally inside this iframe and preserves its reading position. It does not change the outer drawer or workbench draft ownership.

## Alternatives considered

- Restore the separate-tab entry: its earlier qualification proves state preservation and it needs no drawer state, but restoration would overwrite the concurrent frontend owner's working changes even though the current request only requires an accessible manual button. Preserve and verify the compatible integration instead.

## Verification

The final frontend passes its 87 tests and typecheck/build. A fresh isolated server with synthetic accounts passes [eight real-HTTP browser groups](../../../../output/account-lifecycle-20261010-v2/browser-report.json), repeating account lifecycle acceptance and adding help-frame opening, reading all six images, closing, pending-upload preservation, hidden redundant return link and no-popup/no-upload checks. The report records the exact frontend index hash, zero page errors, production writes and model calls, and empty persistent browser stores. The drawer screenshot is visually inspected. Production accounts and task data remain untouched by these browser checks. Earlier separate-tab and account acceptance outputs are preserved.

## Consequences

The shared frontend is being edited concurrently; verification qualifies the recorded build and does not authorize overwriting later changes. The help iframe contains only generic same-origin documentation and no business requests. Other frontend styling remains owned by the parallel UI work.
