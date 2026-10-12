# Agent Note: Configure business-required fields by document type

Status: implemented
Scope: backend/ocr_app/doc_profiles.py, backend/ocr_app/required_fields.py, backend/ocr_app/task_store.py, backend/ocr_app/review.py, backend/ocr_app/exporting.py, backend/ocr_app/routes.py, backend/migrations/versions/0004_required_fields.py, frontend/src, frontend/tests, tests, ARCHITECTURE.md, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-10

## Problem

Required fields are fixed in document profiles. The user wants to set them in the frontend and explicitly selects one shared setting per document type, applied to current and historical tasks without OCR reruns. A UI-only override would disagree with server export checks and optional-absence review validation.

## Decision

An administrator-only settings tab provides authenticated GET/PUT endpoints under /admin/required-fields. The application persists document-type overrides and one monotonic revision in a small SQLite settings table; default absence preserves existing conditional profiles. Saving a type selects its exact editable required field set, including optional household member fields and generic body text. Derived read-only fields cannot become required. Restore defaults removes that type's override, including restoring its conditional rules. An empty custom set permits optional empty business fields while still requiring a saved supported result.

Current server settings govern task export flags, full result metadata, review field validation and atomic whole-selection export. Read one settings snapshot for each read/export/review operation; changes never rewrite historical ciphertext, OCR outputs, manual fields, task status or result revision. Expose a separate optional required_fields_revision on batch/task/result DTOs. Terminal batch rows refresh when it changes; result cache identities invalidate while dirty drafts retain their existing stale-version protection. The generic body and each existing household member use the same selected requirements.

Settings saves use expected_revision under BEGIN IMMEDIATE, validate field keys/types and preserve other types. Stale administrators receive 409 without a lost update. Existing administrator/CSRF/origin checks protect writes. A mandatory authorization callback revalidates the live administrator session inside the write transaction, including no-op saves, as qualified by the [cross-session review repairs](../bug-fix/2026-10-12-review-repairs.md). Audit settings changes using field keys and revisions only. Existing defaults, task version guards, presence-only export and all-or-nothing selection remain.

## Decision audit

The [presence-only export gate](../../implemented/simplification/2026-10-08-required-fields-only-export.md) and [document profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) partly overlap: defaults stay, but current required sets become administrator configurable. The [frontend workbench](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md), [review contract](../../implemented/feature/2026-10-08-human-review-and-xlsx-export.md) and [administrator accounts](../../implemented/feature/2026-10-09-admin-account-creation.md) retain monitoring, draft and permission contracts. Proposed Mac/auth work and rejected clinical grading/localization are unrelated. No implemented decision is wholly superseded or archived.

## Alternatives considered

- Store checkboxes only in browser storage: smallest frontend change, but cannot enforce shared settings or agree with backend export. Persist on the server and project the same policy everywhere.
- Store requirements per batch or account: supports differing workflows, but the user explicitly selects shared document-type settings that affect existing tasks. Avoid extra policy layers.
- Rewrite saved recognition results after each settings change: makes stored metadata immediately reflect policy, but risks overwriting manual work and changing historical revisions. Project current requirements at read/review/export boundaries.
- Reject custom empty required sets: prevents nearly blank exports, but creates a hidden fixed requirement despite explicit configuration. Show the consequence clearly while retaining saved-result/type validity.

## Verification

All 519 backend tests and 85 frontend tests pass, with typecheck and production build. Eight dedicated settings tests cover administrator/CSRF/origin authorization, invalid/derived keys, persisted defaults and per-type reset, immutable historical ciphertext/revisions, current review requirements, atomic selection export, household/generic requirements, concurrent saves and one policy snapshot across a concurrently changed batch list. Upgrade from migration0001 to0004 preserves task ciphertext and input bytes and creates an empty settings table; absence keeps defaults.

Five real-HTTP browser checks on isolated synthetic data pass with zero model calls and zero production writes. They cover the old missing-school task, saving requirements and downloading Excel without changing task values/revisions/status, current required labels, dirty-draft protection when another session changes policy, stale-save409 with selected choices retained, resetting defaults, derived-field disabling and refresh. Earlier hidden-input selectors and a premature assertion failed in the acceptance harness; all attempts and artifacts remain separate under output/required-fields-20261010-v1. No production setting is chosen on behalf of the administrator.

The production database has an online pre-migration backup at output/required-fields-20261010-v1/pre-migration.sqlite3. The additive table is present and empty, preserving default policy revision0; activation occurs only with zero active/queued tasks. The activated production service reports both models ready; all115 task ciphertexts/statuses/revisions, the single account and default policy remain unchanged. The protected new route returns401 without login and served static bytes match the accepted build. Deployment health and ciphertext comparison are recorded in output/required-fields-20261010-v1/activation.json.

## Consequences

Administrators can permit incomplete business data by marking fields optional. Presence completeness remains independent of OCR accuracy, confidence or human review. An empty custom set permits saved results with blank business fields. The server enforces the latest policy snapshot on every review/export even if another open browser has stale metadata. Local saves refresh loaded rows; other sessions obtain settings on their next read, visibility refresh or reload. Dirty drafts remain protected rather than silently replaced. Startup migration is required before using the settings routes; there is no destructive downgrade.
