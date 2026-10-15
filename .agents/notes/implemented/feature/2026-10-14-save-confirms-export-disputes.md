# Agent Note: Confirm reviewed export disputes through the ordinary save action

Status: implemented
Scope: backend/ocr_app/review.py, backend/ocr_app/task_store.py, backend/ocr_app/routes.py, frontend/src/review.ts, frontend/src/components/ReviewEditor.vue, tests/test_export_disputes.py, frontend/tests/review.test.ts, scripts/probe_interview_browser.py, SPEC.md, FRONTEND_FIELDS.md, openapi.yaml, frontend/public/help/index.html, ARCHITECTURE.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-15

## Problem

The user explicitly wants the existing bottom save button to finish human review without a second confirmation button or reason. Removing the separate confirmation panel leaves false-positive disputes impossible to resolve in the UI.

## Decision

The ordinary non-table review editor sends confirm_export_disputes=true with its existing version-bound save. Apply all edits and current validation first, then acknowledge every remaining confirmable dispute against that resulting value/context in the same authorized transaction. Preserve original evidence and private actor/time fingerprints. Missing required fields and conflicts without a selected value remain blocking. No confirmation dialog is introduced. Requests without the flag retain patch-only semantics, and the existing confirmed_disputes API stays compatible.

A save with acknowledgment but no data edits can preserve a failed task's execution state/error; it does not claim full-page coverage or recovery. Actual data edits to failed results retain the existing coverage requirement. Values changed without a new acknowledgment and recognition reruns invalidate old fingerprints.

## Decision audit

- [Disputed export gate](../../implemented/feature/2026-10-14-disputed-results-export-gate.md): partially superseded only for the confirmation interaction. Shared gating, evidence, ownership and revision fences remain.
- [Removed confirmation panel](../../implemented/feature/2026-10-14-export-disputes-section-removed.md): removal remains; this decision replaces its lack of an exception remedy. Keep the panel removed.
- [One-click review](../../implemented/feature/2026-10-08-internal-unmasking-and-review-friction.md): consistent with save-as-review; explicit disputes now have separate private fingerprints rather than accepted_issues.
- Broad scoped deployment/queue notes and rejected model/localization proposals are unrelated. No complete supersession or archive.

## Alternatives considered

- A separate per-dispute confirmation provides more granular intent, but the user explicitly rejects the additional click.
- Treat every API patch as acknowledgment is a smaller backend rule, but old callers and internal correction tools would silently waive disputes. A boolean on the existing user save expresses the intended review without another UI control.

## Verification

71 focused export/review/authorization/settings/table regressions pass. After adding explicit TABLE rejection, 48 final dispute/API/contract tests pass. Frontend passes 194 tests and typecheck/build. Eleven isolated real-HTTP/Edge workflow groups verify one ordinary save with edits and without edits, later unacknowledged mutation blocking export again, batch filter removal, source preservation, Excel downloads and account isolation. Browser evidence is [recorded here](../../../../output/save-confirms-20261014/interview-browser-210327/browser.json). No production recognition or accuracy benchmark is performed.

## Consequences

[Selection integrity repairs](../bug-fix/2026-10-15-review-integrity-and-table-performance.md) enforce the existing unselected-value rule for medical findings/items and historical acknowledgments. Metadata edits preserve unresolved selections; the ordinary save interaction remains unchanged.

Saving now attests to the current displayed content, including numbers outside reference rules; operators must inspect before saving. Confirmation is not an official authenticity check. Table structure and coverage controls remain unchanged.

## Local activation

After confirming idle queues and no expired tasks, the owned Windows launcher tree is replaced using a consistent database/artifact/key/static snapshot. Both resident models load and warm up successfully. All 13 database tables, 291 tasks, 2 accounts and 2941 material/key files remain unchanged, and all 13 served static files match the verified build. Anonymous business requests remain unauthorized. [Activation evidence](../../../../output/save-confirms-20261014/activation/verified.json) records the checks. Git commit/push and Mac deployment are outside this change.
