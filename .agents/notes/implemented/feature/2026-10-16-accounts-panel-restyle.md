# Agent Note: Accounts panel rebuilt as a creation toolbar plus a list section

Status: implemented
Scope: frontend/src/components/AccountManagement.vue
Last-verified: 2026-10-16

## Problem

The accounts panel stacked two heavy cards: a permanently-expanded 创建账号 form (five top-labeled fields in a two-column grid) above the account list. Feedback for every action — create, disable, delete, reset, rename — rendered inside the creation card, so a delete confirmation appeared next to the create form, far from the row the user acted on.

## Decision

The presentation and full-list account operations remain; paging follows [direct numbered pagination](2026-10-16-numbered-list-pagination.md):

- One feedback strip at the top of the panel (`error` XOR `success`, they are never set together) carries the result of every action, so the message always appears in the same predictable place.
- The creation form collapses into a single flex toolbar (`.create-bar`, light card background, placeholder-driven inputs 登录账号 / 姓名 / 密码（至少 8 位） / 确认密码, role select, Plus-icon submit). Enter still submits via the wrapping el-form.
- The list becomes its own section: a slim header row (已有账号 · N 个 · 刷新列表 pushed right), a striped table (same columns and row actions), and the protection hint line. Guide anchors kept in place and unique: account-create on the bar, account-list on the list header, account-protection on the hint.
- The users endpoint returns the full account list, so pagination is a pure client-side slice: el-pagination (total / sizes 20·50·100 / prev / pager / next / jumper) under the table, visible even for a single page; list shrink clamps to the valid last page, and page-size changes reset to page one.

## Alternatives considered

- Move creation into a dialog behind a 创建账号 button: fewest pixels, but account creation is a first-run admin task where seeing the fields immediately matters; the slim bar keeps it visible at one row's cost.
- Toast (ElMessage) instead of the inline strip: toasts vanish and the panel is also used read-only after actions; the persistent strip is auditable.

## Verification

Frontend typecheck, node tests and production build pass; `npm run verify` passes with this note. No browser probe or unit test asserts this panel's DOM (checked scripts/ and frontend/tests), and the three guide anchors survive unchanged, so the anchor-existence guide test needed no update.

## Consequences

Adding fields to the creation bar means keeping placeholder text meaningful (there are no standing labels) and remembering the bar wraps rather than stacks on narrow widths.
