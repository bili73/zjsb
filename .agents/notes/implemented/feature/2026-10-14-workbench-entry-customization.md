# Agent Note: Customizable workbench entry layout

Status: implemented
Scope: frontend/src/components/UploadPanel.vue, frontend/src/workbenchEntries.ts, frontend/tests/workbench-entries.test.ts
Last-verified: 2026-10-14

## Problem

The workbench renders one card per supported material type (twelve today); every future type adds another card until the grid gets crowded. The user asks for operator-customizable entries: choose which types sit on the workbench (max 12), reorder them, and tuck the rest away while keeping them reachable.

## Decision

Split the type-card grid into an ordered visible set plus a tucked "更多类型" collapsible section whose cards behave identically. A 自定义入口 dialog manages both panes: drag-and-drop reorder within the visible pane, drag across panes to 移出/放回 (native HTML5 DnD with an insertion indicator, cap-aware — a full workbench offers no drop hint), plus 上移/下移/移出/放回 buttons kept for keyboard and precision use, capped at 12 visible entries, with 恢复默认. The layout persists in the browser's localStorage under `ocr-workbench-entries-v1` as a JSON array of doc_type keys; parsing failures or malformed records fall back to the default (all types, catalogue order). Once a customization exists, catalogue types not listed stay tucked — future backend types default to tucked, which is the crowding motivation. Stale keys of retired types are purged from the stored layout when the catalogue loads non-empty; the first catalogue load (empty list) never rewrites storage. Pure logic lives in `src/workbenchEntries.ts` (`splitEntries`, `loadWorkbenchLayout`, `saveWorkbenchLayout`) and is unit tested. If the currently selected type is tucked with no files chosen, the selection moves to the first visible entry; with files chosen the selection is kept.

## Alternatives considered

- Server-side per-account preference (settings API): survives browser switches but adds a contract, migration and auth surface for a personal layout preference; localStorage matches the LAN single-machine usage. Revisit if operators roam machines.
- Drag-and-drop reordering: initially skipped for focus/touch pitfalls, then implemented at the user's explicit request using native HTML5 DnD (no dependency), with the insertion indicator and the buttons retained as the keyboard/precision path.
- Hide tucked types entirely: smallest grid, but operators would lose discoverability of rarely used types; the collapsible section keeps them one click away.

## Verification

Frontend typecheck, node tests and production build pass; `npm run verify` passes with this note. Node tests cover default/full display, unknown and duplicate keys, the 12-entry cap, storage roundtrip, malformed storage fallback, null-save clearing and quota-failure tolerance.

## Consequences

The layout is per browser profile, not per account: switching machines or clearing site data resets to the full grid. New types land tucked for customized browsers, so release notes should mention where to find them. `splitEntries` silently drops unknown keys, so a retired doc type cannot break rendering. No API, permission or server-storage change.
