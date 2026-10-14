# Agent Note: Remove the system-layout reset entry

Status: implemented
Scope: frontend/src/components/UploadPanel.vue, frontend/public/help, scripts/probe_account_layout.py, SPEC.md, FRONTEND_FIELDS.md

Last-verified: 2026-10-14

## Problem

The administrator default feature added a second reset action that the user finds confusing. The user explicitly requests removing it.

## Decision

The 恢复系统默认 button and its confirmation branch are removed. Administrator saving of the visible layout and personal 恢复默认 inheritance remain unchanged. Persisted layouts and nullable API compatibility are preserved; this change does not reset settings or modify the database.

## Related-note audit

Partially replaces the UI reset decision in [administrator defaults](../../implemented/feature/2026-10-14-admin-workbench-default.md); that note's inheritance, authorization and revision rules remain. [Account isolation](../../implemented/feature/2026-10-14-account-workbench-layout.md) and [entry customization](../../implemented/feature/2026-10-14-workbench-entry-customization.md) remain in force. Related proposed deployment and rejected OCR notes are unrelated. No note is fully superseded.

## Alternatives considered

- Keeping the button gives administrators a quick way to recover the original catalogue, but adds a second meaning of default that the user has explicitly rejected.
- Removing nullable backend support would narrow the API too, but it is unnecessary for removing the UI and would change existing default-state compatibility.

## Verification

Frontend typecheck, build and 11 layout tests pass. [Eight real HTTP/Edge acceptance groups](../../../../output/account-layout-20261014-v3/browser-151200/browser.json) pass, including absence of the removed button, preserved personal overrides and explicit personal reset/save inheriting the administrator default. Tests use isolated synthetic accounts and no OCR calls.

[Local static publication](../../../../output/layout-reset-removal-20261014-151417/verified.json) verifies 13 served files against the tested build, backs up the previous static directory and retains old hashed assets. Public health remains healthy. The update does not restart models or write the business database.

## Consequences

The edit toolbar exposes one personal reset and one administrator default-setting action. Administrators can still rearrange the catalogue and save it as the shared default. Old tabs need a refresh to see the removed button; nullable backend semantics remain compatible. Help and field documentation describe the remaining actions.
