# Agent Note: Hover-only export block reason with warning styling

Status: implemented
Scope: frontend/src/components/ExportControls.vue, frontend/src/components/TaskResultDrawer.vue, frontend/src/style.css, frontend/tests/detail-loading.test.ts
Last-verified: 2026-10-20

User request: the batch toolbar's standing blocked-export sentence had to appear only when hovering the export button, with an exclamation icon and a warning-tinted background matching the app's earlier warning hints. Landed in the same batch as the help TOC grouping note ([help TOC](../bug-fix/2026-10-20-help-toc-groups.md)).

## Problem

- ExportControls rendered `blocked` (from `exportBlockReason`, review.ts) as a standing `.conf` sentence next to the toolbar whenever any task could not be exported — a permanent wall of text for a state the user fixes per-task in the detail drawer.
- TaskResultDrawer already used the intended pattern (disabled button + tooltip reason, guide.ts promises 「按钮不可用时悬停可查看原因」), but its tooltip was unstyled default dark text, visually unrelated to the app's warning family.

## Decision

- ExportControls: the button is wrapped in `el-tooltip` (`:disabled="!blocked"`, effect light, popper-class `export-tip-popper`, placement top) whose #content slot renders `.export-tip` — WarningFilled icon + the blocked text. The button itself is wrapped in a `<span>` so hover events still fire while it is disabled (disabled buttons swallow pointer events). The standing blocked `.conf` span is removed; the busy and person-package hints stay.
- TaskResultDrawer: the existing blocked tooltip gains the same popper-class and content markup, so both surfaces share one visual language.
- Styling lives in style.css (global): the popper teleports to `body`, so component-scoped styles cannot reach it. Colors come from Element Plus warning tokens (light-9 background, light-7 border, warning icon) — the same family as el-alert warning. Arrow background/border are overridden to match.

Extends the [one-row toolbar](./2026-10-16-batch-expanded-toolbar-one-row.md) precedent: disabled button + hover reason instead of standing sentences.

## Alternatives considered

- Keep the standing sentence: rejected — explicit user request to show it on hover only, and it contradicts the fewer-standing-sentences direction of the toolbar work.
- Default dark tooltip, content text only: rejected — inconsistent with the app's warning-hint family; the user asked for the icon and tinted background explicitly.
- Remove the reason entirely: rejected — the reason names the fix path (task detail → 保存修正); hiding it regresses usability for blocked exports.

## Verification

281/281 frontend tests pass; vue-tsc --noEmit and vite build exit 0. detail-loading.test.ts's icon stub gained `WarningFilled` (a grep across all compile-mount harness stubs found it the only one missing the new import — cockroach check for the same class of failure). Element Plus 2.14.7's theme CSS confirmed to carry `.el-popper.is-light` and `.el-popper__arrow::before`, so the override selectors match real markup. guide anchors `batch-export` / `detail-export` are unchanged and guide tests stay green.

Visual acceptance (icon size, tint, max-width 360px wrap) is human-checked; the compile-mount harness does not render DOM.

## Consequences

- The block reason appears exactly where the fix has to happen (the disabled button), not as ambient toolbar text.
- Batch toolbar and detail drawer show identical tooltip styling for the same condition.
- The pre-commit 3-dimension adversarial review ran as inline verification this session (Workflow/Agent tools unavailable; see the help-TOC note and handoff doc).
