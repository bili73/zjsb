# Agent Note: Complete human review and gated Excel export

Status: implemented
Scope: backend/ocr_app, tests, frontend, scripts, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, requirements-app.lock.txt, IMPLEMENTATION_PLAN.md, RUNTIME.md, ARCHITECTURE.md
Last-verified: 2026-10-09

## Problem

Recognition results are read-only. The user approves manual entry for missing fields, source comparison, explicit review and XLSX export. Required values must be complete; optional values may be explicitly marked not printed or not applicable. Export selects the current batch or explicit tasks. The later [presence-only decision](../simplification/2026-10-08-required-fields-only-export.md) permits export once required saved values are present; unresolved review issues still govern COMPLETED, not export.

## Decision

Review binds task_id, run_id and expected_revision in a short atomic transaction. Patches accept only editable business fields, current item/finding/member IDs and explicit acceptance of currently acceptable issues. Keep raw OCR/source and original runs unchanged. Record corrected values and confirmations in encrypted review_revision artifacts, reusing existing storage and seven-day cleanup. Public audit stores safe identifiers and counts. Empty review and a note alone never approve values. Do not write masked display strings back as original values or manufacture model confidence.

A failed execution with a readable complete source and stored complete page evidence may receive a separate human correction version. Task review state may become NEED_REVIEW then COMPLETED while the original run remains FAILED with its original result/error/timing. Result metadata identifies manual completion and original recognition failure. All original pages, not merely the currently processed page_count prefix, must be verified. Unresolved missing pages, unreadable sources, conflicting values and incomplete regions cannot be accepted through accepted_issues.

Medical edits include item grades/diagnoses and report findings. Human coverage records enumerate actual source pages and corrections for unfinished regions, bound to the version. Derive statistics and abnormal facts from the reviewed full result; do not let a filtered view establish completeness. Required missing information remains blocking; report-absent optional information carries an explicit absence reason, not a invented clinical result.

Corrected-page preview binds run/revision/page to encrypted evidence. Operator/admin can access the complete image directly after authentication, while viewer retains no original-image permission. Missing fields with no bbox use a full-page fallback. The UI sends changed fields only and retains drafts on409 without automatically overwriting newer results. Source evidence and original runs remain immutable.

POST /export accepts a batch or explicit task IDs and optional expected versions. The backend snapshots unfiltered current results and either exports all selected records or returns missing-required-value blockers under the [presence-only policy](../simplification/2026-10-08-required-fields-only-export.md). It does not run review or require COMPLETED. XLSX uses type-wide document rows plus medical/member/generic sheets, review/run/revision metadata, text identifiers and no executable user formulas. User-authorized complete internal output and optional confirmation reasons are owned by [internal full values](2026-10-08-internal-unmasking-and-review-friction.md). Legacy masked flags are accepted but do not change content; existing operator/admin permission and both audit layers remain. Use openpyxl3.1.5 rather than a custom OOXML writer.


## Decision audit

The implemented [business Excel layout](2026-10-09-business-xlsx-layout.md) replaces technical worksheet/metadata dumps with saved Chinese business fields and focused medical data. Selection, snapshot/version checks, authorization, audit and string/formula protection remain.

The [durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md), [HR fields](../../implemented/feature/2026-10-08-hr-document-field-profile.md), [field mapping](../../implemented/bug-fix/2026-09-30-evidence-bound-field-mapping.md), [diagnostics](../../implemented/feature/2026-09-30-local-diagnostics.md) and [frontend rebuild](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) partially overlap and remain active. Their earlier unavailable-review boundaries are extended, not their lifecycle or frozen measurements. No archive is warranted. The [document profiles](2026-10-08-card-and-document-profiles.md) own rules and type admission.

## Alternatives considered

- Frontend-only export gating is fast and gives useful feedback, but can be bypassed and loses server-side version/permission guarantees. The server is authoritative.
- Accepting every issue with one button is convenient, but would approve missing values, conflicts and unrecognized pages. Use explicit correction and coverage confirmation.
- Requiring every optional value avoids blank spreadsheet cells, but forces fabricated diagnoses and unprinted cardholder names. Require business-required fields and explicit resolution of relevant review issues.
- A dedicated review-history schema offers SQL querying, but current low volume and encrypted artifact history need no new table or migration.

## Verified behavior

Missing fields are editable and source-linked where reliable. Low/unavailable confidence requires explicit confirmation without score inflation. Unknown keys, masked-value submission, stale versions, unauthorized access and unresolved missing/conflicting/incomplete data are rejected. Medical edits recalculate derived values. A FAILED correction does not rewrite original runs. Export is atomic over the selection and cannot bypass eligibility with filtering. XLSX preserves leading zeros and long numbers, contains no executable user formulas or security codes, and respects the current full-value access policy and authorization.

## Consequences

Manual completeness is a human attestation, not a new model accuracy claim. Full values are intentional under the later user-authorized access policy. Original and reviewed states must be labelled distinctly. Real samples remain confidential and are never sent to external recognition services.


## Confirmed interaction update

On 2026-10-08 the user explicitly authorizes the existing one-click confirmation UI from a concurrent frontend writer. Preserve that interaction. The client enumerates only current can_accept issues and submits the current issue IDs without requiring a fixed reason; an actual optional user explanation is retained; server eligibility, revision checks and safe audit remain authoritative. Missing, conflicting, multi-candidate and incomplete-output issues cannot be bulk accepted. Do not treat a source-code comment as authorization; this update is based on the user's direct answer.

Member addition/removal and summary scope/title correction complete the approved manual missing-information workflow. An empty household cannot export, and all household source pages require human coverage for review completion, independently from export eligibility. A declared finding count requires explicit follow-up title/scope and an evidence page; a count alone cannot manufacture report completeness.


## Verification

Review, missing entry, coverage, household member addition/removal, medical item/finding edits, dynamic metadata, version-bound preview and selection-atomic XLSX are implemented. The final isolated headless browser run verifies 12 UI checks plus four HTTP groups using synthetic data/FakeRuntime, zero real model calls. Full CPU regression, frontend tests/typecheck/build and contract checks are recorded in output/document-review-acceptance-20261008-v1/REPORT.md and output/review-export-browser-20261008-v1/REPORT.md. Real exhaustive HR clinical coverage and new-family accuracy remain unqualified.

## Final acceptance checkpoint

The pre-policy checkpoint passes402 tests in12.136s, including the bank FORMAT issue which cannot be accepted by one-click review and blocks the whole selected export until corrected. Unknown issuer/checksum applicability remains a separate confirmable issue. Frontend type checking and54 tests pass. Frozen synthetic review/export browser acceptance and current-build presentation smoke are recorded separately from serial real-model sample measurements in output/document-review-acceptance-20261008-v1/REPORT.md. No field fill ratio is represented as calibrated accuracy.

## Export-policy extension

The user explicitly changes export eligibility to required-value presence. The [required-fields-only decision](../simplification/2026-10-08-required-fields-only-export.md) now replaces only the export gate; review completion, versioning, source preservation and role permissions in this note remain active. The402-test checkpoint above records the prior gate.

The later [medical review-scope correction](../bug-fix/2026-10-08-medical-review-scope.md) excludes exact height/weight/小结 item rows from review targets and the default editor, including historical projected results. Excluded original recognition issues are preserved without being blockers or automatic acceptances; BMI, genuine item problems and page coverage remain reviewable. Source/version and presence-only export rules here remain active.


## Current refinement

The [bank automatic recovery](2026-10-09-bank-auto-recognition.md) offers per-file crop retries alongside the existing manual editor; original task/results stay intact. The [medical export refinement](../bug-fix/2026-10-09-biochemistry-ledger-export.md) changes content formatting and source-backed liver summaries, not required-field eligibility.


## Medical-only source navigation

The user cancels certificate positioning. The [medical navigation decision](../bug-fix/2026-10-09-medical-only-source-navigation.md) limits field/row source controls to medical reports, fixes same-page reselection and waits for corrected images to load before highlighting. Whole-page preview and manual entry remain for every material type. Existing source/version, recognition, review and export contracts here remain active.
