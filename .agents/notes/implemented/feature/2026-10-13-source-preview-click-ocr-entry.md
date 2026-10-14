# Agent Note: Open region OCR from clicking the source page image

Status: implemented
Scope: frontend/src/components/SourcePreview.vue, frontend/src/components/RegionOcrDialog.vue
Last-verified: 2026-10-13

## Problem

The region re-recognition entry lives only in SourcePreview's toolbar. Staff already click a page image to view the original full screen, so the toolbar detour feels redundant; the user asks to fold recognition into that click-to-view path — keeping the previous fullscreen viewing style, not replacing it with the bounded dialog.

## Decision

For materials with trusted corrected pages (`ocrEnabled`), clicking a source page image opens the region OCR dialog in a new `cinema` variant: a fullscreen dark backdrop (82% black modal mask, like the retired stock viewer) with the corrected page fit to the viewport, a translucent floating bar (page switcher, reload, zoom state, exit) and no dialog chrome. Drag-selection, the viewport-aware recognize chip, the floating result panel and cursor-anchored wheel zoom all work unchanged inside it. The toolbar button keeps the bounded dialog variant. Materials without trusted corrected pages keep the stock viewer via `preview-src-list`, and hints (toolbar line, figure cursor/title) describe the merged entry.

This refines [source-region OCR copy](2026-10-13-source-region-ocr-copy.md): entry placement and presentation only — its fenced dialog flow, request contract and clipboard behavior are untouched. An earlier cut of this note widened the bounded dialog for the click entry; the user rejected replacing the fullscreen viewing style, so the cinema variant supersedes it.

## Alternatives considered

- Reuse the bounded dialog for clicks: rejected by the user — the click-to-view path must stay a fullscreen original viewing experience.
- Inject selection into the Element Plus viewer: its transform state is not exposed and it allows no custom overlays; not viable.
- Custom standalone fullscreen component: duplicates the dialog's zoom/selection/fence plumbing; the cinema variant of the existing component shares all logic via one template with shell-level CSS.

## Verification

Frontend typecheck, node tests and production build pass; `npm run verify` passes with this note. A local Edge harness confirmed: clicking a synthetic source page opens the fullscreen cinema viewer on that page, selection plus recognize from that entry produces the floating result, the toolbar button still opens the bounded dialog, and `ocrEnabled=false` keeps the stock preview viewer.

## Consequences

Staff on `ocrEnabled` materials lose the single-click stock fullscreen viewer; the cinema viewer is the viewing path (fit-to-screen, wheel zoom, page switching). Clicks on the medical bbox overlay also open the cinema viewer (same page). The bounded dialog remains for the toolbar entry. No API, permission or storage change.

[Date clipboard suggestions](2026-10-13-region-date-copy-suggestions.md) extend the current result card with separate selectable date formats, preserve the editable OCR text and the current non-closing copy controls, and retain its existing request/permission/version fences. The earlier copy-and-close label does not describe the current result card.

Dismissible locate highlight (2026-10-14): the red bbox overlay stayed forever after a field locate until another field was located or the drawer closed, obscuring the corrected page ("定位之后区域会变红，然后就一直不消失"). Clicking blank space now clears it — first only inside the preview section, then drawer-wide at the user's request ("需要点击任意空白处，比如右边的字段的空白处"): TaskResultDrawer binds a click handler on `.drawer-body`, and both it and SourcePreview's section handler share `interactiveTarget.ts`'s `isInteractiveClickTarget` predicate (unit tested), which treats clicks on interactive controls (buttons, inputs, textareas, selects, labels, links, collapse headers, Element Plus editors) and page images (`.img-wrap`/`.el-image`) as carrying their own semantics — everything else (field-pane gaps, static text, paddings, edges) clears `activeSource`. All locate triggers are el-buttons, so no locate path can be clobbered by the clear; re-locating the same field re-scrolls and re-highlights because the drawer assigns a fresh source object per locate. The tools-line hint ("点击空白处可取消红框") shows while a highlight is active.
