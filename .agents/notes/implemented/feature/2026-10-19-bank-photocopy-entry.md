# Agent Note: Separate bank photocopy requirements from ordinary card photos

Status: implemented
Scope: backend/ocr_app, frontend/src, frontend/tests, frontend/public/help, tests, scripts/probe_bank_photocopy.py, scripts/qualify_bank_copy_entry.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, ARCHITECTURE.md, RUNTIME.md
Last-verified: 2026-10-19

## Problem

The user wants different required fields for a bank photocopy with handwritten account details and a single card photo. Both previously used BANK_CARD, and required-field settings are keyed by doc_type. Making holder_name/bank_name/branch_name mandatory for photocopies under that shared type would also affect ordinary cards. A card may identify its issuing bank but typically cannot supply an account holder or opening branch.

## Decision

Two workbench entries have separate business types: BANK_CARD for ordinary cards, BANK_CARD_COPY for photocopies and handwritten supplemental sheets. Required-field settings remain independent. Defaults are card_number only for BANK_CARD and holder_name/card_number/bank_name/branch_name for BANK_CARD_COPY. Existing administrator overrides remain authoritative and are never reset by adding the new profile.

Keep the current complete bank field schema and saved values compatible. Ordinary-card presentation emphasizes card number and observed/derived bank metadata; unused optional holder/branch fields need no filling, and existing nonempty manually entered values must remain accessible and exportable. Photocopy presentation emphasizes the four account-detail fields. Do not remove historical fields to make the ordinary-card form look simpler.

Both types share the installed models, bank-family recognition/region planning, automatic orientation, candidate/source handling, local PAN/BIN checks, crop recovery, temporary region OCR and existing task budgets/queue limits. Branch names come from actual source text or manual entry, never a guessed BIN location. Printed/handwritten PAN conflicts retain both candidates. The business doc_type stays distinct throughout upload, results, review, exports and audits; algorithm reuse must not overwrite it with BANK_CARD or bypass the new required profile.

Historical BANK_CARD tasks, including earlier photocopies, retain their type, source, values, runs, revisions and confirmation fingerprints. No automatic content-based migration, result recomputation or required-policy reset occurs. The pre-implementation read-only check confirms revision1 has no BANK_CARD or BANK_CARD_COPY override; no policy write occurs. New uploads use the selected entry and its profile. Personnel packages offer both types; classification suggestions remain editable. Explicit photocopy headers or branch information support a copy suggestion; bank-only content without subtype evidence requires selection from the two candidates. A unique filename hint may suggest the type with a filename-only warning. Classification never changes a submitted task's type.

Exports use the appropriate type/profile and keep both bank kinds available in the personnel summary. The workbench retains its12-visible-card limit and account/default layouts; the directory has14 material types and excess entries remain in storage. Frontend/server saved-layout bounds accept14 keys, including unchanged13-key arrays, without rewriting old layouts or exposing all14 cards at once. Upload formats remain the single-image JPG/PNG/HEIC contract for both bank types; PDF support remains outside this change. SPEC advances to v1.34 and app/API/frontend to1.28.0 without a database migration or release tag.

## Implementation boundaries

`BANK_CARD_TYPES` in doc_profiles.py controls the shared bank algorithms. The copy profile duplicates metadata only; no second recognition implementation or new model is introduced. Intermediate extraction retains doc_type before refreshing BIN-dependent fields. The catalogue automatically places both types in the certificate lane. Review/public projection/export use the selected profile and preserve manual candidates and values. Frontend crop recovery submits the original business type; candidate/source controls, region overlays, number warnings, personnel suggestions and grouped Excel support both types.

The existing probe accepts --doc-type for future isolated serial qualification. qualify_bank_copy_entry.py replays historical encrypted predictions only after exact source/input-hash matching, and writes separate encrypted outputs. No production database, account, model service or Mac resource is used by qualification.

## Related-note audit

The subsequent [non-name bank conversion](2026-10-19-bank-non-name-simplification.md) applies equally to both entries' new recognition candidates while preserving the separate requirements, personal names, source evidence, historical types and human corrections defined here.

The [bank photocopy decision](2026-10-14-bank-photocopy-handwriting.md) previously favored a unified entry to reduce manual classification and duplicated workflows. This changes only that entry/profile tradeoff; its region planning, handwriting, provenance, conflicts and failure evidence remain active. [Configurable required fields](2026-10-10-configurable-required-fields.md) remains authoritative per business type. [Account-owned layouts](2026-10-14-account-workbench-layout.md) and [interview entry and shared upright](2026-10-14-interview-registration-and-shared-upright.md) retain account isolation and the twelve-visible-entry policy; this extends the stored-key bound explicitly. These decisions partially overlap and remain active; no entire note is superseded or archived. Searches find no competing proposed/rejected bank-entry split.

## Alternatives considered

- Two frontend cards with the same BANK_CARD request: smallest visible change and reuses all APIs, but both still share required-field settings, task identity and export grouping, so it does not solve the requirement.
- One card plus a stored ordinary/photocopy subtype: keeps a small workbench and can be selected in the upload form, but requires a new subtype dimension in task wire/storage contracts, settings keys, result identity and export policy. The project already keys these features by doc_type; a distinct business type fits the existing design with less new state.
- Infer requiredness from recognized name/branch fields or paper layout: minimizes user choices, but missing handwriting could misclassify a photocopy as an ordinary card and let required information escape the export gate. Classification may suggest, never decide the business requirement from missing results.
- Duplicate the entire bank pipeline: isolates future tuning, but repeats orientation, model scheduling, candidate checks and review fixes; share the existing bank family while separating business profiles.
- Reclassify all old BANK_CARD results: makes history immediately uniform, but available OCR cannot reliably distinguish every old photocopy and changing doc_type invalidates existing confirmation fingerprints. Keep historical types and manual results intact.

## Consequences

An ordinary card with a saved valid PAN can satisfy its required fields without holder/branch; a new photocopy missing any configured required account detail is flagged and cannot export. Each type's required-setting change does not affect the other. Source conflicts and existing explicit-dispute gates remain. Both types retain model routing, upright/crop/region source behavior and single/mixed/personnel exports. Existing results and confirmation IDs are unchanged, unknown classification stays editable, and saved13-key layouts remain accepted with at most12 visible cards. The extra visible business choice prevents a shared required policy from requiring information a bare card cannot supply.

Some photocopies do not state an opening branch. Missing information needs source verification/manual supplementation rather than fabrication. New required fields do not improve handwriting accuracy. Historical photocopies remain under BANK_CARD intentionally and are not retroactively subject to the new copy defaults. Account layouts can leave the new entry in storage until the user adds it.

## Verification

- Windows tests exercise independent defaults/admin policy, PDF rejection, source candidates and saved conflict resolution, old stored-row byte equality, old nonempty manual values and nonempty confirmation fingerprints, GLM lane/region/orientation sharing, and mixed/personnel XLSX export after manual completion.
- The first full backend run executes1003 tests: one obsolete13-type count assertion fails, seven environment-dependent tests skip, and all other tests pass. That assertion is updated to14; a64-test profile/copy/scheduler/contract rerun passes, including the additional lane regression. Frontend277 tests, typecheck and isolated Vite build pass. Failure logs are retained in the [validation record](../../../../output/bank-copy-entry-validation-20261019-v1/REPORT.md).
- The isolated [actual-component browser fixture](../../../../output/bank-copy-browser-20261019-qGuDTp/report.json) verifies storage access/max12 cards, immediate PDF rejection, BANK_CARD_COPY upload, four required controls, candidate/source actions, saving and ordinary-card one-required presentation. It makes no business requests. Earlier fixture selector failures are preserved separately.
- [Ten-sample frozen replay](../../../../output/bank-copy-entry-replay-20261019-v1/REPORT.md) matches original image hashes and all OCR input hashes; all10 field maps stay identical. Three ordinary cards remain unblocked; among seven copy cases, missing name, missing branch and unresolved PAN conflict each block one. The other four having values does not prove those values correct. No new model call, accuracy or speed claim is made.
- Initial qualification uses the staged build and isolated tests only. At the user's subsequent restart request, the idle Windows service is backed up and activated with1.28.0; the [activation record](../../../../output/windows-preview-restart-20261019-185323-57ca28/verified.json) verifies15 unchanged tables,393 tasks,4 users,1 session,4090 referenced blob metadata entries,2 key hashes and16 HTTP static hashes. Public health isok; protected model readiness is not queried because no login/session is replaced. No new recognition benchmark occurs. Historical source/key/data files and Mac online services remain untouched.
