# Agent Note: Persist workbench layouts per authenticated account

Status: implemented
Scope: backend/ocr_app, backend/migrations, frontend/src, tests, frontend/tests, scripts/probe_account_layout.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-14

## Problem

Workbench entry customization uses one browser storage key. Different accounts on the same origin inherit the previous operator's layout; one account cannot recover its preferences in another browser. The user approved server-side isolation, explicit save, failure recovery and stale-tab conflict detection.

## Decision

Store one ordered nullable list plus revision per immutable named account in SQLite. Null means catalogue defaults; an empty list means all entries tucked. Retain a revision after restoring defaults to prevent stale writes. A self-only GET/PUT endpoint derives ownership from the live session and rechecks it in the write transaction; no supplied user ID or administrator override. Viewer accounts may edit their own presentation preferences without gaining business write access. Delete preferences with the account; name/password changes preserve them.

Keep dragging and tucking as an in-memory draft. Save once on 完成, preserving drafts on failure/409. Explicit reload discards the draft; failed reads cannot be saved over the server. Session/client changes abort requests and clear drafts; late responses cannot cross identity boundaries. Do not import the unowned legacy browser key. Preserve existing default/new-type/tucked semantics; no model, task or export changes.

## Related-note audit

Partially replaces the browser persistence decision in [entry customization](../../implemented/feature/2026-10-14-workbench-entry-customization.md); drag mechanics remain. [Account ownership](../../implemented/feature/2026-10-10-account-owned-batches.md) and [lifecycle](../../implemented/feature/2026-10-10-account-lifecycle-management.md) supply immutable identities and transaction/session checks. Proposed deployment/auth work and rejected OCR decisions are unrelated. No note is fully superseded or archived.

## Default-layout extension

The [administrator default](2026-10-14-admin-workbench-default.md) extends null semantics to inherit the shared default. Personal arrays and account boundaries remain unchanged; the previous system-default interpretation above records the original decision.

## Alternatives considered

- Account-prefixed localStorage is a smaller change and isolates a shared browser, but loses preferences across browsers and storage clearing. Use server persistence as approved.
- Import the shared key preserves an existing layout, but cannot establish which account created it. Keep it untouched and unused; each account starts with defaults.
- Save on every pointer swap preserves each intermediate arrangement, but increases writes and races during gestures. Save the finished draft once, with revision checking.

## Verification

The full backend suite passes761 tests in258.107s, including the expanded endpoint authorization inventory and interrupted0009 migration. Six focused account tests cover independent operator/admin/viewer preferences, reset revisions, invalid/forged bodies, committed session revocation before the write transaction, concurrent saves and rename/restart/delete/recreate. The focused suite passes again after strengthening the revocation test. The frontend suite passes177 tests; typecheck and isolated Vite build pass. Ten focused layout/parser/API/state tests cover drafts, failures, conflicting revisions and ignored late responses across account changes.

The [isolated real HTTP and Edge acceptance](../../../../output/account-layout-20261014-v1/browser-142944/browser.json) passes six groups: ignoring the legacy shared key, real drag/tuck/save/refresh, stale-tab draft preservation and confirmed reload, save500 recovery, same-browser account switching, reset and new-browser restoration. It uses synthetic named accounts and zero OCR calls. The first browser attempt failed because an exact text selector included a sibling reload button; its report and screenshot remain preserved. Neither business assertions nor implementation were loosened.

## Consequences

The first upgrade resets unowned local layouts to defaults. A failed save may already have committed; reload reconciles rather than automatically replaying it. Existing account/task/sample data and unrelated working-tree edits must be preserved.

The [interview and shared-upright extension](../feature/2026-10-14-interview-registration-and-shared-upright.md) adds the five-field profile and raises the shared entry capacity to13; the original rule and scope owned here remain in force.

The [twelve-visible-card correction](../bug-fix/2026-10-14-workbench-twelve-visible-cards.md) enforces12 visible entries for every layout independently of the13-type catalogue. Existing13-key preferences remain readable; excess cards are hidden rather than removed. This supersedes the interview extension display-cap increase, retaining the wire compatibility and original account rules.
