# Agent Note: Export saved results once required values are present

Status: implemented
Scope: backend/ocr_app/exporting.py, backend/ocr_app/task_store.py, frontend, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, ARCHITECTURE.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-08

## Problem

The implemented [business Excel layout](../feature/2026-10-09-business-xlsx-layout.md) changes exported content and presentation while preserving this decision's required-saved-value-only gate and whole-selection blocking behavior.

The earlier [human review and XLSX decision](../../implemented/feature/2026-10-08-human-review-and-xlsx-export.md) requires all selected tasks to reach COMPLETED and clear review issues before export. The user explicitly changes the export condition to all required fields having values. This should not relabel uncertain or incomplete recognition as reviewed.

## Decision

Export current saved, unfiltered results when their business-required values are present. Resolve conditional top-level requirements through doc_profiles.profile(doc_type,current_values), include basic_info-compatible values, each household member's MEMBER_PROFILE required fields and at least one household member, and require nonempty generic full_text. Use a saved reviewed_generic when it exists; otherwise use recognized generic. None, empty text and whitespace-only text are missing; scalar0/False are present. Missing optional values do not require absence reasons for export. Filled values with format/checksum failures, candidate/coverage issues or unavailable/low confidence do not create extra export blockers. NEED_REVIEW or FAILED results can export if required values are present. No saved result remains missing.

Keep the recognition/review state unchanged and include its actual metadata in XLSX. Export does not call apply_review or silently accept any issue. Operator/admin permissions, current-version checks, safe audit, encrypted access history and formula-safe text serialization remain. Export still succeeds for the complete selection or returns409 with safe missing-field keys/codes for every blocked selected task; do not export a partial subset.

Task and TaskResult expose optional export_ready and export_blockers using the same server presence check before any medical result filter. The frontend uses the saved-version flag rather than status; legacy responses without a flag defer eligibility to the server. Unsaved drawer edits must be saved before export. Do not add another upload/deployment/model workflow.

## Decision audit

[Human review/export](../../implemented/feature/2026-10-08-human-review-and-xlsx-export.md), [document profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md), [frontend rebuilding](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) and [full internal values](../../implemented/feature/2026-10-08-internal-unmasking-and-review-friction.md) remain partially active. Only their export eligibility statements are superseded; review completion, source preservation, permissions, type rules and historical benchmarks still apply. None is fully superseded or archived.

## Alternatives considered

The approved [medical ledger template](../../implemented/feature/2026-10-09-medical-ledger-template.md) keeps the medical required set name/gender/exam_date. Newly added measurements, report metadata and group summaries remain optional; the catalogue count is derived rather than a new required gate. This presence-only policy is unchanged.

- Requiring COMPLETED and every review issue resolved gives the strongest assurance of verified exports, but adds the precise friction the user explicitly removes. Preserve warnings/state while allowing presence-complete results.
- Letting the UI alone decide is smaller and avoids an API addition, but it cannot access every result from a batch list and can be bypassed. Use one small server helper and expose its summary.
- Treating checksum-valid as part of filled limits invalid identifiers, but changes the user's presence-only condition and rejects supported historical/unknown formats. Keep validation visible as review information, not an export gate.
- Exporting just ready tasks yields immediate partial data, but contradicts the approved all-or-nothing selection semantics and can hide missing records. Continue to block the entire selected export on missing required values.

## Verified behavior

Required None/empty/whitespace or a missing field blocks export even if the task says COMPLETED;0/False do not count as missing. Filled required values permit export with optional blanks, unresolved review issues, FAILED/incomplete recognition and format warnings. Household member requirements and generic recognized/reviewed text are respected. No export changes stored states, revisions, original result blobs or confidence. Batch/selection is atomic; viewer403 and stale-version409 remain. Frontend enablement and real HTTP browser downloads follow the same flags. Preserve the old402-test checkpoint and failed browser fixtures as historical evidence; validate this changed policy separately with CPU tests/FakeRuntime and no real-model calls.

## Consequences

A downloadable workbook may contain unreviewed, invalid or partial recognition values; actual status and recognition metadata remain explicit. Presence completeness is not authenticity, confidence or full-page coverage. Old measurement timings remain frozen, and changing the export gate adds no new OCR accuracy claims.

## Verification

The final complete backend suite passes409 tests in12.531s, including7 new presence-only tests. They cover conditional profiles, each household member, explicit null/whitespace versus0/False, basic_info compatibility, original generic text with formula-safe long-text chunks, human-text precedence, failed/unreviewed exports, completed-but-missing rejection, unchanged encrypted result/state/revision, no call to apply_review, and identical eligibility across medical filters. The existing bank HTTP regression now verifies that a filled invalid PAN exports while its non-acceptable FORMAT review issue and NEED_REVIEW status remain.

The current frontend passes55 tests, type checking and build. An isolated frozen-static headless browser uses synthetic materials and real loopback HTTP to verify required-missing whole-batch409, unreviewed single/selected downloads, saved supplementation with incomplete-output issues still present, whole-batch download, unsaved-edit gating, and401/403/stale409. Four XLSX files parse successfully; export never changes result/state/revision/issues. This export probe uses0 real/Fake model requests. The same build separately passes UTC+8/type-title/descending-order, drawer split and pixel-rotation smoke; only that rotation probe uses1 Fake admission request,0 real model calls. Failed selectors/fixtures remain preserved rather than counted as success.

The actual local service was updated only after confirming0 active/queued tasks. Both resident models report ready; authenticated metadata on41 existing tasks carries consistent presence flags, and the served index SHA256 a0ce9dda4ef6b18b46810537bf972a451dad43dcf21c19e360b38aad89ac8bd0 matches the qualified frozen build. Detailed artifacts: output/required-fields-export-20261008-v1, output/required-fields-export-browser-20261008-v1 and output/current-frontend-smoke-20261008-v1/attempt-004. Previous402-test and OCR/BIN measurements remain frozen and do not qualify this new export policy.
