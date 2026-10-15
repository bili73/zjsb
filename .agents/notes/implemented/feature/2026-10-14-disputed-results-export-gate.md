# Agent Note: Block exports with explicit unresolved recognition disputes

Status: implemented
Scope: backend/ocr_app, frontend/src, frontend/tests, tests, scripts, SPEC.md, FRONTEND_FIELDS.md, openapi.yaml, frontend/public/help, ARCHITECTURE.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-15

## Problem

The user now requires explicit recognition disputes to block export and appear in batch summaries beside missing required fields. The previous presence-only gate allows invalid identifiers to export, and the existing ordinary save automatically accepts some validation issues.

## Decision

Keep required-value and table-structure gates. Add one server projection for explicit number-length warnings, current format/checksum failures and unresolved recognition conflicts. Uncalibrated confidence, no official lookup and uncovered rules alone are informational. Current and historical saved results use the same projection for task summaries, detail and atomic exports; original OCR evidence remains immutable.

Provide a separate version-bound confirmation action, without a required reason, for a saved value checked against the original. Ordinary save cannot confirm disputes. Store actor/time and a semantic fingerprint privately in the encrypted result. Value/context changes and reruns invalidate confirmation; no automatic digit repair or inferred authenticity. Unselected/empty candidate conflicts require an actual value or explicit optional absence first. Missing required values cannot be waived.

Task summaries expose safe DISPUTED field paths; detail exposes opaque dispute IDs and explanations. The UI distinguishes missing values from disputes, supports filtering and lets the operator confirm each saved dispute with no unsaved edits. Keep ownership, session validation, revision fencing and whole-selection export semantics.

## Decision audit

- [Presence-only export](../../implemented/simplification/2026-10-08-required-fields-only-export.md): partially superseded only for explicit disputes; required profiles, atomic snapshots and frozen measurements remain.
- [Number hints](../../implemented/feature/2026-10-14-number-length-review-hints.md): partially superseded because warning-level hints now have a backend gate; informational legacy/unknown rules remain informational.
- [One-click review](../../implemented/feature/2026-10-08-internal-unmasking-and-review-friction.md): still applies to informational issues, not explicit disputes.
- [Table export](../../implemented/simplification/2026-10-14-table-export-without-confirmation.md): remains unchanged; complete tables need no extra confirmation.
- Other scoped deployment proposals and rejected localization/medical-threshold/model-table approaches are unrelated. No note is fully absorbed or archived.

## Alternatives considered

- Blocking all NEED_REVIEW results is simpler and conservative, but confidence is uncalibrated across essentially all OCR fields and would require unrelated confirmations.
- Auto-accepting disputes on ordinary save reuses existing behavior, but silently bypasses the user's new export gate.
- Requiring valid-format corrections only provides a strict rule, but historical documents and stale BIN references need explicit human exceptions. The user authorizes confirmation without a reason.
- Frontend-only blocking is smaller, but direct exports and historical records could bypass it.

## Verification

The full backend suite passes792 tests. After the final recovery-status refinement,83 focused export/review/authorization/settings/table regressions also pass. The frontend passes193 tests and typecheck/build. Eleven isolated real-HTTP/Edge workflow groups verify direct API409 and disabled export buttons, batch dispute counts/filter, ordinary-save bypass resistance, separate confirmation without a reason, source preservation, identifier corrections, Excel download and account isolation. Browser evidence is [recorded here](../../../../output/disputed-export-20261014-v1/interview-browser-193149/browser.json). Initial failures remain preserved: historical presence-only expectations were updated, and two browser selectors were corrected (disabled button wrapper and Element Plus hidden native checkbox).

A read-only projection over291 production tasks (282 saved results) finds22 tasks with explicit disputes in0.406 seconds, without changing original result JSON. This measures projection overhead, not OCR accuracy. Clinical inference and new model benchmarks are not part of this change. Failed partial results retain their FAILED state and error on exception confirmation; a confirmation does not claim page coverage. Raw OCR, human values and private confirmation history remain encrypted.

## Consequences

[Selection integrity repairs](../bug-fix/2026-10-15-review-integrity-and-table-performance.md) make unselected medical values unconfirmable, including when old acknowledgments exist. Detail obtains blockers and dispute explanations from one analysis of the unfiltered saved snapshot; other callers retain the blockers-only interface.

Reference checks are not authenticity decisions. Human confirmation permits an unchanged source exception and does not improve model confidence. New gates can block previously downloadable historical results; operators must correct or explicitly confirm them. No new OCR accuracy claim or production inference benchmark is made.


## Local activation

The Windows queue is idle before activation. A consistent database, encrypted-artifact/key and static-file snapshot is retained under output/disputed-export-20261014-v1/service-snapshot. Only the verified owned launcher tree is stopped; the replacement uses dual_resident. Both model load/warmup events succeed, public health is ok, anonymous business endpoints return401, and13 served static files match the final build. All13 database tables,291 tasks,2 accounts and2916 artifact/key files match the pre-restart snapshot. [Activation verification](../../../../output/disputed-export-20261014-v1/activation/verified.json) records the checks. No Mac deployment, Git commit or push occurs.


## Save interaction update

[Save-as-review](2026-10-14-save-confirms-export-disputes.md) partially supersedes the separate confirmation interaction: the bottom save now carries explicit acknowledgment in the same transaction. Existing export gates and removal of the standalone panel remain.
