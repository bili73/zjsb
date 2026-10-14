# Agent Note: Let administrators set the inherited workbench default

Status: implemented
Scope: backend/ocr_app, backend/migrations, frontend/src, tests, frontend/tests, scripts/probe_account_layout.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-14

## Problem

While the account-isolation change was being qualified, the user additionally requested administrator control of the default layout. Personal settings must still remain separate.

## Decision

Persist a singleton default layout and independent revision. Personal null now means inherit that default; default null means the system catalogue order. Personal arrays, including an empty array, override the shared default. Return both personal and default snapshots in one self-only read. Resetting personal layout restores inheritance, not a copied list.

Add an administrator-only versioned write with transaction-time role/session validation. In entry edit mode, administrators can confirm saving the current visible arrangement as the shared default or restoring the system default. These operations do not save or overwrite a personal draft. Normal 完成 continues to save only the current account. Changes affect inherited layouts on the next read; no live pushes or forced rearrangement during editing. Conflicts retain the draft and require explicit reload. Both preference tables land in migration0009; the administrator addition was requested before the initial activation, so no already-applied schema version is rewritten.

## Related-note audit

The system-reset UI described above is partially superseded by [removing the confusing reset entry](../../implemented/simplification/2026-10-14-remove-system-layout-reset.md). The other default-layout decisions and historical verification remain valid.

Extends [account isolation](../../implemented/feature/2026-10-14-account-workbench-layout.md), partially replacing the meaning of its null default with inheritance; identity, explicit personal save and stale-response rules remain. [Entry customization](../../implemented/feature/2026-10-14-workbench-entry-customization.md) retains drag mechanics. Account/required-field notes provide existing administrator authorization patterns but do not confer access to others' personal layouts. Proposed deployment and rejected OCR decisions are unrelated; no note is fully superseded.

## Alternatives considered

- Replacing all users' layouts makes the organization uniform immediately, but violates personal isolation and overwrites deliberate arrangements.
- Copying defaults into each new account avoids inheritance, but later administrator changes would not reach unchanged accounts and restoring defaults becomes ambiguous.

## Verification

Eight focused backend tests pass for account/default isolation, inherited versus personal/empty layouts, reset revisions, permission denial and role demotion committed before the save transaction, concurrent versioned saves, rename/restart/delete/recreate, invalid/forged requests and committed session revocation. Eleven frontend layout/controller tests and typecheck pass; the complete frontend suite passes182 tests, including concurrently developed independent source-preview checks.

[Real HTTP/Edge acceptance](../../../../output/account-layout-20261014-v2/browser-144250/browser.json) passes eight groups, retaining the six account-isolation groups and adding confirmed administrator default writes, newly inheriting accounts, unaffected custom accounts, no accidental personal save and system-default restoration. It uses isolated synthetic accounts and zero OCR calls. Earlier account-only measurements remain historical evidence; they do not include administrator default behavior.

## Consequences

Default changes intentionally affect multiple accounts after refresh/login; confirmation explains this scope. Reused revision checking and no auto-retry protect against stale tabs. No business records, account credentials, OCR models or exports change.


Final regression passes763 backend tests in260.493s and182 frontend tests, with typecheck/build and DDE verification. The final parser/controller subset passes11 tests after adding invalid-default contract assertions. [Local activation evidence](../../../../output/account-layout-activation-20261014-v1/verified.json) confirms schema0009, both supervised model warmups, unchanged10 pre-existing business tables,283 tasks,2 accounts and2881 material/key files. The served static tree matches the eight-group browser-tested build; anonymous personal/default endpoints remain401. No production preference was assigned during activation. The Mac deployment and Git push are not part of this change.
