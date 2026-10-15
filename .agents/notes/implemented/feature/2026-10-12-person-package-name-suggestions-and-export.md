# Agent Note: Upload before naming and export person packages

Status: implemented
Scope: backend/migrations, backend/ocr_app/person_packages.py, backend/ocr_app/task_store.py, backend/ocr_app/routes.py, backend/ocr_app/exporting.py, frontend/src/components/UploadPanel.vue, frontend/src/components/PersonNameEditor.vue, frontend/src/components/BatchBoard.vue, frontend/src/components/ExportControls.vue, frontend/src/api.ts, frontend/src/business.ts, frontend/src/monitor.ts, frontend/src/review.ts, frontend/tests, tests, openapi.yaml, SPEC.md, FRONTEND_FIELDS.md, RUNTIME.md, IMPLEMENTATION_PLAN.md, README.md, ARCHITECTURE.md, frontend/public/help/index.html
Last-verified: 2026-10-13

## Problem

The user selects upload first, suggest the person's name after recognition, and points out the missing person-package Excel experience. Previously mixed uploads required person_name; encrypted name presence also distinguished packages from ordinary batches and enabled append/pairing. Removing only the input would silently remove package behavior. The existing exporter already accepted a whole batch or selected tasks and grouped saved fields by material type, but lacked a person-package overview. The user chooses overview plus detail (A).

## Decision

Represent package intent independently of the confirmed person name using an additive batch flag. Backfill existing explicitly named packages only; leave ordinary and historical unassigned batches unchanged. Mixed file_types creation means a person package even with no person_name; existing named and legacy single-type contracts remain compatible. A pending-name package can append materials, display identity-card presence and retain owner/admin isolation. Initially display 人员材料包·姓名待确认. Do not introduce a person registry or merge same-name packages.

Derive editable name suggestions from the latest saved structured recognition/correction fields, without any extra OCR/model request. Prefer identity-card front and named personal documents; retain distinct alternatives and their material/file sources. Do not infer the employee from a household householder/member, business legal representative, generic text or an unnamed ID back. Name agreement is not identity proof. Multiple names receive an explicit ambiguity warning; material without a usable name remains unverified. Never silently select a winner when evidence disagrees.

Provide manual name confirmation/correction with the package revision and a fresh transactional authorization/ownership check. Store only the confirmed name encrypted; later recognition or supplementation must not overwrite it. Suggestions recompute after saved field corrections. Naming does not modify task results, account ownership, original files or expiry. A stale concurrent rename/append receives409. This iteration does not automatically move another person's materials or claim a complete cross-document identity check.

The user selects export choice A: one Excel workbook with a 人员材料总览 sheet listing the confirmed name or 姓名待确认, selected material types/count, candidate names with file sources and source files; retain all selected latest saved document values in the existing type-specific detail sheets. Medical output remains the supplied eighteen-column ledger. No collapsing multiple certificates/cards into one arbitrary value. Whole-package and selected-file modes remain, with selection scoped to exactly the chosen files and names never sourced from unselected recognition results. Ordinary type-batch exports stay unchanged. Package downloads use 人员材料包 plus Shanghai time, avoiding person-name characters in filenames.

Choice B, one wide person row integrating all document fields, is rejected in favor of A because repeated documents and conflicting values have no agreed collapsing rule.

Preserve the existing required-saved-values-only export gate: no new confidence, optional-field, pairing or name-confirmation block. Show uncertain attribution explicitly if exported before confirmation. Preserve full internal values, string identifiers, formula safety, overflow failures, snapshot/version checks, selection atomicity and export audit. Continue the existing medical and orange nonmedical header formatting, frozen headers, filters and wrapped text. Package downloads use 人员材料包_YYYYMMDD_HHMMSS.xlsx in Shanghai time; ordinary filenames stay unchanged.

## Decision audit

The [process/package repairs](../../implemented/bug-fix/2026-10-13-region-ocr-and-package-repairs.md) capture the package revision when name editing begins. Reactive metadata refresh does not rebase an old draft;409 retains it and requests cancel/reopen with current information.

The [pre-push isolation repairs](../bug-fix/2026-10-12-prepush-isolation-and-migration.md) prevent delayed overlapping pagination from reversing reconciled name/pairing/package metadata and ensure accepted page changes wake pending task reconciliation. This extends the same generation/reference fences.

The [single-submit workflow](2026-10-12-person-package-single-submit.md) and [person package storage](2026-10-12-person-material-packages.md) partially overlap. This decision replaces their upfront mandatory name and immutable-name interaction; atomic upload, explicit package boundaries, ownership, versioned append, encrypted metadata and individual expiry remain. [Business workbook layout](2026-10-09-business-xlsx-layout.md) and [medical ledger](2026-10-09-medical-ledger-template.md) remain active for detail sheets. [Required-values-only export](../simplification/2026-10-08-required-fields-only-export.md), optional ID back and account isolation remain active. No implemented note is wholly absorbed or archived.

## Alternatives considered

- Extract a name with CPU OCR before submission: gives an immediate label, but adds another parsing source and still requires handling disagreement. Reuse the final structured recognition results and saved corrections.
- Automatically bind the majority/first recognized name: minimizes clicks, but one erroneous result or multiple people in a package creates false attribution. Offer suggestions and require an explicit human confirmation to persist a label.
- Remove the name input without distinguishing package intent: smallest UI change, but null names currently mean ordinary batches, breaking append and pairing. Add an explicit package flag with compatible backfill.
- Require name confirmation as a new export gate: makes downloads easier to label, but conflicts with the user's explicit required-fields-only rule. Mark pending attribution and preserve the gate unless separately changed by the user.
- Replace all type-specific worksheets with one wide integrated row: convenient for joining data, but can discard repeated/conflicting documents. The user selects overview plus detail.

## Verification

Eight isolated tests cover pending packages, saved-name sources/conflicts, encrypted confirmation and CAS, invalid/revoked/foreign/viewer access, selected-only overview, repeated documents, literal formula-like values, unchanged medical18 columns, migration/backfill/restart and concurrent name winners. Full backend655 and frontend125 pass alongside the separately authorized single-session change. Real-HTTP browser validation covers name-free upload, source/conflict display, editable confirmation, supplementation preserving the label and actual workbook download/reopen, without production mutations or vision calls. Artifact Tool imports/renders the overview read-only for visual inspection; existing detail formatting stays unchanged.

Independent frontend review reproduces two real refresh gaps: older-page packages only reread tasks, leaving revisions/pairing/suggestions stale, and recognition finishing between list and task reads can leave the final empty suggestions cached. Monitor now reads the existing single-Batch endpoint after older-page task reads or changed task identities/status/revisions, with generation and Batch-reference guards. Advancing metadata retains one reconciliation pass; failures retain pending work. Two regression tests cover the reproductions, and existing out-of-order/account-switch tests remain active. Evidence remains under output/person-package-names-20261012-v1/ and output/person-ui-release-review-20261012-v1/.

Independent follow-up verifies125 frontend tests, both corrected reproductions and three additional probes for Batch500 retry, a stale Batch response after newer pagination metadata, and session clear during a metadata read. Evidence: output/person-ui-release-review-20261012-v2/. Final owned real-HTTP browser8-group acceptance passes with zero page errors/model calls/production changes at output/person-package-names-20261012-v1/browser-164334/summary.json. The backend/export reviewer additionally checks true concurrent confirm/append, cross-package selected exports and0006-to0008 combined migration,42 isolated checks total, without finding a blocking defect.

Local activation succeeds after an idle check and SQLite/encrypted-file backup. Schema0007 and0008 are active; original business/account rows and all2509 pre-existing encrypted/key files retain their hashes, preserving255 tasks and2 accounts. GLM and Paddle are both ready in dual_resident mode with an empty queue. Served frontend assets match the build byte-for-byte; anonymous batch, append, classify and person-confirmation requests return401. Evidence: output/person-package-names-20261012-v1/activation.json. Session deduplication and one real post-restart login are intentional transitions covered by the [single-session decision](2026-10-12-thirty-day-single-session.md). This is local Windows activation, not Mac or online HTTPS qualification.

## Consequences

The [complete personnel table](2026-10-12-person-package-full-field-table.md) partially replaces this note's six-column overview layout after the user requests every selected business field in the first worksheet. Naming, explicit package intent, selected snapshots, duplicate detail rows, eligibility and medical template decisions remain active. The first sheet is now 人员信息总表 with full type-prefixed fields and numbered repeated-document groups.

This introduces additive schema0007 with is_person_package and a user-visible workbook format. Name suggestions are derived convenience data, not authenticity or reliable person matching. All name conflicts can remain unresolved; no automatic person merging, document relocation, medical employment decision, model fine-tuning or real-sample accuracy claim is included. PATCH /batches/{batch_id}/person accepts person_name and expected_revision, increments the shared package revision and stores only the confirmed label encrypted. Suggestions include explicit bank holder names at lowest priority, exclude generic/legal/household names, and carry task_id, doc_type and file_name sources. The user approved this scope and Excel A before implementation.

## Export metadata refinement

The [source filename removal](../../implemented/simplification/2026-10-15-export-without-source-filenames.md) partially supersedes the source filename columns and filename-bearing candidate descriptions in exported workbooks. Full business values, repeated-document groups, application source evidence, naming, snapshot gates and the medical template remain active.
