# Agent Note: Fill the liver ledger field only from confirmed abnormal measurements

Status: implemented
Scope: backend/ocr_app/medical_ledger.py, tests/test_medical_ledger.py, backend/ocr_app/api.py, tests/test_runtime_api.py, tests/test_document_contract.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user clarifies that 肝功五项 is an abnormality field: normal liver measurements must not populate it. The earlier measured-result fallback deliberately fills seven normal A-grade measurements in the native samples, which conflicts with this newly explicit business rule. Printed normal conclusions currently also populate the field.

## Decision

Automatically populate liver_function only with confirmed abnormal source-backed measurements attributed to the liver group. Keep actual abnormal names, results, units and diagnoses; ignore normal/unknown measurements and normal or unclassified standalone conclusions for automatic field values. Retain the established biochemical-heading whitelist and conflict detection: contradictory evidence remains empty and reviewable rather than guessed. Preserve conclusions as evidence metadata. Do not automatically overwrite manual values or explicit absence. Existing derived historical values are refreshed on the caller-owned read/export projection without rewriting saved ciphertext. Other group summaries, complete item evidence, anomaly counts, eighteen-column layout and required-field export gates remain unchanged.

## Decision audit

This partially supersedes the [biochemistry refinement](../../implemented/bug-fix/2026-10-09-biochemistry-ledger-export.md) for liver measured-result fallback, and the [ledger template](../../implemented/feature/2026-10-09-medical-ledger-template.md) for liver normal-conclusion filling only. Newline anomalies, EF760E headers, other group conclusions, human overrides, source binding and historical verification remain active; no note is archived. Calendar scope and download names are independent active frontend requests. The rejected automatic clinical/eligibility grading remains rejected.

## Alternatives considered

- Keep all measured liver values: preserves maximum visible detail, but the user now explicitly wants this column to contain abnormalities only. Complete measurements remain in items/source evidence.
- Fill 正常 or 未见异常 when a conclusion says so: directly reflects source text, but still fills the column without an abnormal indicator, contrary to the request.
- Erase old saved fields in a database migration: makes storage match the new presentation, but risks destroying manual values and history. Recompute derived read/export projections instead.

## Consequences

Normal measurements and printed normal conclusions leave the automatic liver field empty. Complete measured items and conclusion evidence remain available. A standalone abnormal conclusion without a confirmed source-backed measurement is not automatically summarized; humans may enter a verified value. Empty does not mean clinically normal or fully recognized. Manual values and explicit absence remain unchanged, including old manually supplied normal text. Historical derived values refresh only on caller-owned read/export projections.

## Verification

The relevant backend suite passes101 tests in23.430s; the frontend passes71 tests and typecheck/build. The final synchronized OpenAPI documentation passes10 contract tests. CUA verifies default today, October8 selection, explicit all dates, Monday week and month boundaries, and a new synthetic upload returning from October8 to today's day range. Batch, selected and single downloads produce actual 银行卡_20261009_HHmmss.xlsx files; all three reopen with unchanged saved card fields. Mixed-type and Shanghai-midnight names are covered by unit tests.

Three serial native-PDF replays retain7 liver measurements per report but leave the liver ledger cell empty, with project counts9/10/11 and abnormal counts7/6/2 unchanged. They make0 model calls and leave154 image regions pending; this is mapping verification, not complete OCR accuracy. Initial browser automation/download timeout and the unavailable-engine fixture are preserved; the ready-engine fixture completes, stops cleanly and makes0 real model calls or production task writes.

After three idle checks and a consistent SQLite backup, all12 identity-verified old owned processes exit. Windows loopback1.17.1 serves all4 qualified frontend files with matching HTTP hashes; both models are ready. The61 original tasks encrypted fields, one account and key files retain their signatures. The actual production page shows only October9's6 batches by default and only October8's14 after selection. Evidence is in output/calendar-period-20261009-v1/. No migration, original sample rewrite, Mac qualification, commit or push occurs.

## Related normal-summary rule

The [normal-summary fallback](../../implemented/bug-fix/2026-10-09-medical-normal-summary-fallback.md) explicitly excludes liver_function. Its five other groups can summarize fully normal recognized rows without a printed conclusion; the abnormal-only liver decision and measurements above remain active.

## Later measured-group summary policy

The [measured-group summary correction](../../implemented/bug-fix/2026-10-09-medical-measured-group-summaries.md) partially supersedes normal-summary eligibility: liver and source-backed A-grade measured rows can produce 未见异常 without a printed 小结. Closed numbered native catalogues distinguish report absence from missing recognition. Abnormal details, attribution, counts, manual priority, source binding, unavailable confidence, review and immutable history remain active. The older decision and measurements above retain their original rationale; no note is archived.
