# Agent Note: Review usability fixes from the 2026-10-18 visual audit (batch C)

Status: implemented
Scope: frontend/src/components/TaskResultDrawer.vue, frontend/src/components/ReviewEditor.vue, frontend/src/review.ts, frontend/tests/review.test.ts, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-19

Third slice of the 2026-10-18 visual audit (after batch A/B, same audit), done as a frontend-only surgical batch while the backend thread worked in parallel on unrelated files.

## Problem

- (audit #15) ReviewEditor and ResultView emit 查看来源 for HOUSEHOLD_REGISTER fields, but `TaskResultDrawer.locate` still dropped the event for that doc_type — the click did nothing, while FRONTEND_FIELDS' locate whitelist includes 户口本 alongside medical/bank/interview.
- (audit #5) On NEED_REVIEW tasks the header's solid-blue 导出 Excel was the most visually dominant control while the red notice says 核对后再使用； the actual primary action in that state is 保存修正 (already primary inside the editors), so export outranked the action the screen is asking for.
- (audit #2, second half) The red notice named the first two blocking issues as plain text; there was no way to reach the offending field/item/finding/member in the editor below without hunting for the label by eye.
- IMPLEMENTATION_PLAN.md's frontend row still described source preview as 点击/双击进全屏缩放查看器 — stale since the 2026-10-13 region-OCR dialog landed.

## Decision

- `locate` allowlist adds HOUSEHOLD_REGISTER: page-level source navigation only. The rejected certificate helper (../../rejected/feature/2026-10-09-certificate-field-localization.md) was about manufacturing bbox coordinates for certificate fields and stays rejected; household keeps coarse whole-page comparison (no bbox in its sources), and SourcePreview's red-box overlay gating is deliberately untouched — still corrected-page types only. Known contract gap carried into this batch: FRONTEND_FIELDS.md's locate clauses do NOT yet authorize household (line 241, written in the medical-only era, still names 户口本 as excluded; per-type rows cover only TABLE/GENERIC/BANK_CARD/INTERVIEW_FORM), and that file is in the backend thread's in-flight edit set so this batch cannot sync it — the code comment at the allowlist flags the pending doc sync, and the sync itself is handed to the backend coordination list. Household remains without real samples (FRONTEND_FIELDS.md line 269), so this is page-scroll behavior only, unvalidated on real materials.
- The enabled export button drops to a normal button while `task.status === 'NEED_REVIEW'` and returns to primary otherwise; the export gate (`exportBlocked`, tooltip-disabled branch) is unchanged, so this is visual hierarchy only — NEED_REVIEW export stays one click away when eligible, per the audit decision that export readiness is export_ready's business, not the notice's.
- `collectIssues` rows carry an optional `jump` anchor (field key / item_id / finding_id / member index; task-level rows carry none). The drawer renders the first two notice segments as buttons (non-TABLE results only; TableReview has no matching editor anchors) and passes the clicked anchor down as a `focus` prop `{kind,id,seq}` — seq increments so repeated clicks on the same target re-trigger. ReviewEditor expands the containing collapse (items/findings via a new controlled `openPanels`; members via the existing `memberOpen`), then scrolls the anchored element into view and flashes it once (warning ring), and hands focus to the anchor (`tabIndex=-1` + `focus({preventScroll:true})`) so the next Tab continues from the target instead of pulling the drawer back to the top. Scroll behavior honors prefers-reduced-motion via matchMedia ('instant' instead of 'smooth', same pattern as OperationGuide) — the CSS media query alone cannot govern JS scrollIntoView. Empty `blockingIssues` keeps the old parenthesis-free notice.
- IMPLEMENTATION_PLAN.md row reworded to 点击页面进入原图框选识别（个别状态退为全屏缩放查看器）； header date/version lines were already current (2026-10-19, SPEC v1.33 / OpenAPI 1.27.0) and untouched.

## Alternatives considered

- Route the jump to the source image/bbox instead of the editor: wrong target — the notice points at editor content, and household/finding rows have no bbox by design; page-level locate already exists separately via 查看来源.
- Global event bus or `document.getElementById` from the drawer: rejected — collapse open state lives inside ReviewEditor, so the drawer cannot expand panels it does not own; a focus prop keeps ownership local and the seq counter makes re-triggering testable.
- Make the whole notice one button: rejected — with two named issues plus a tail there is no single honest target; per-segment buttons name theirs.
- Demote export permanently or move it: rejected — for reviewed/export-ready tasks export IS the primary action; tying the demotion to live `task.status` keeps both states correct without touching the gate.
- Give TABLE results jump buttons too: deferred — TableReview's grid has no per-issue anchors; the notice stays plain text there rather than jumping to an approximate cell.

## Verification

vue-tsc clean; frontend node:test suite 269 pass in the shared working tree (includes a new review.test.ts case asserting field/item/finding/member rows carry the expected jump ids and task rows carry none); production build passes (chunk-size warning is the known noise); `npm run verify` green with this note. Gates ran on a tree that also carries the backend thread's in-flight edits in unrelated files — the commit stages only the files in Scope. Before commit the diff also went through a 3-dimension adversarial review workflow (6 agents); all 3 confirmed findings were fixed in this batch: jump focus stays on the out-of-viewport notice button (fixed via anchor focus handoff), smooth scroll ignoring prefers-reduced-motion (fixed via matchMedia 'instant'), and a false FRONTEND_FIELDS whitelist reference in the locate comment (fixed by stating the real contract gap; doc sync deferred as above).

## Consequences

- 户口本 查看来源 now scrolls the left pane to the field's source page like bank/interview; no red bbox appears (household sources carry none), matching the coarse whole-page comparison contract.
- The red notice's first two issues are one-click reachable in the editor for non-TABLE results; the tail (另有…) stays plain text and TABLE notices stay entirely plain until TableReview grows anchors.
- When a NEED_REVIEW task is export-eligible, export remains available but no longer visually outranks 保存修正； once status leaves NEED_REVIEW the primary export look returns.
- Household locate does not change what the server returns or what is audited; it only stops dropping an event the code already renders. The FRONTEND_FIELDS.md sync (household page-level locate clause + correcting line 241's medical-only wording) is owed by whoever touches that file next — until then the code comment is the only pointer.
- Keyboard/screen-reader users activating a jump button land with focus on the target entry itself; mouse users see the same scroll plus a one-shot flash.
