# Agent Note: Bring portable deployment repairs back to main

Status: implemented
Scope: backend/ocr_app/diagnostic_archive.py, backend/ocr_app/diagnostic_service.py, backend/ocr_app/diagnostic_offline.py, backend/ocr_app/task_errors.py, backend/ocr_app/task_store.py, scripts/collect_diagnostics.py, frontend/src, frontend/tests, tests, SPEC.md, RUNTIME.md, openapi.yaml
Last-verified: 2026-10-16

## Problem

The user requests the general repairs from the independent Mac deployment branch in main. Main is clean at cc65498 and includes the newer detail-page decluttering and skill updates. The deployment source is 63c8f3e, with portable repairs originally committed as 84a1045 and 7f32595. A full merge would also introduce native inference ownership, Docker launchers, host/origin configuration and deployment evidence unrelated to this request.

## Decision

Main includes the portable HTTP browser and serious-query commit 84a1045 with its tests and existing decision notes. It also includes only backend/scripts/tests from 7f32595: the dependency-free TaskError contract (still re-exported by task_store), interrupt-aware diagnostic reads, and read-only serious-event export. This note and the existing local-diagnostics owner document the reusable core without importing links to Mac-only proposals or claiming native source aggregation on Windows.

The newer main UI behavior remains intact while RegionOcrDialog.vue, workbench.ts and the help page receive the portable fixes. The derived DDE index represents the resulting notes, using the repository's committed LF line endings. The pre-merge reference codex/common-fixes-before-20261016 preserves cc65498; the resulting commit records both original source IDs. This is a source integration only; it neither activates services nor changes live data, keys, retention, network settings or model environments.

## Decision audit

- [HTTP browser compatibility](../bug-fix/2026-10-15-http-browser-capabilities.md) and [serious-only queries](../simplification/2026-10-15-serious-diagnostic-query.md) own those behavioral decisions; their existing links remain intact.
- [Local diagnostics](../../implemented/feature/2026-09-30-local-diagnostics.md), [archive maintenance](../../implemented/feature/2026-10-15-diagnostic-levels-and-backup.md), and [partial recovery](../../implemented/bug-fix/2026-10-15-queued-retention-and-diagnostic-recovery.md) partially overlap; retain privacy, verification-before-delete and incomplete-result contracts.
- [Detail-page decluttering](../../implemented/feature/2026-10-16-detail-page-declutter.md) owns the newer main UI and must remain intact.
- Searches across proposed/implemented/rejected notes find no prior owner for this selective return to main. Mac and hosted-session proposals remain independent; no note is superseded or archived.

## Alternatives considered

- Merge the entire deployment branch: preserves ancestry automatically and minimizes selection work, but imports host-specific service and network behavior beyond the requested common repairs.
- Copy the current deployment files wholesale: simple and produces known deployed files, but overwrites newer main edits and brings native-source UI/API coupling. Apply the original portable changes instead.

## Testing

The 31-test targeted diagnostic run passes. The complete Windows backend regression passes all 858 tests in 305.240 seconds. The frontend passes all 224 tests, typecheck and an isolated production build at tmp/common-merge-20261016-dist; served frontend/dist is unchanged. Six actual Edge component checks cover HTTP/localhost text/date copy, bounded/cinema dialogs, diagnostic copy, modern API rejection and exactly two severity options. They issue zero business API requests and report no browser errors (output/http-browser-capabilities/attempt-MWtjId/report.json). Additional portable tests exercise cancellation metadata and the real serious-stream CLI with -I -S, checking ZIP integrity and byte-identical source files. DDE verifies 108 active notes and one sealed archive; the derived index contains 109 notes and 646 relations. Whitespace checks pass. Full suite/build logs remain in tmp/common-merge-*-20261016.log. The existing frontend chunk-size warning remains.

## Consequences

Selective application costs manual scope review and gives the same repair a different main commit identity; source commit provenance and exact patch checks support later merges. Browser clipboard policy may still require manual copying, as the original repair documents. Tests use isolated synthetic state and do not qualify real-model accuracy or activate either production installation.
