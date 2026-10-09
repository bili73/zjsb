# Agent Note: Summarize measured medical groups without requiring a conclusion

Status: implemented
Scope: backend/ocr_app/api.py, backend/ocr_app/medical_ledger.py, backend/ocr_app/extraction.py, backend/ocr_app/exporting.py, frontend/src/business.ts, frontend/src/components/ResultView.vue, tests/test_medical_ledger.py, frontend/tests/business.test.ts, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user clarifies that blood routine, urine routine and liver laboratory tables do not print a 小结. The current liver abnormal-only exception suppresses seven recognized normal liver rows in the Kong PDF. Some qualitative rows carry report grade A without an arrow or comparable numeric range and are excluded from normal summaries. The user requests normal recognized tests to display 未见异常 and explicitly chooses 报告未载明 for genuinely unlisted tests. The original Kong PDF lists nine projects, without urine routine or abdominal ultrasound; HCG urine testing is a different project. Its five abnormal blood rows must remain visible.

## Decision

Summarize all six groups from measured rows, independently of a printed conclusion. Keep confirmed abnormal results and conflicts ahead of normal fallback. Allow a source-backed, nonempty A-grade UNKNOWN row as report-level normal evidence, but never override HIGH/LOW/ABNORMAL/POSITIVE, conflicting evidence or missing results. Existing measured item classifications, review issues, confidence and statistics remain unchanged. Normalize exact printed normal conclusions to 未见异常; preserve detailed conclusions.

Infer NOT_ON_DOCUMENT only from a source-backed native-PDF project catalogue with contiguous numbered rows beginning at one, a recognized subsequent section ending the catalogue, and unchanged recognized catalogue names. A listed test without results, a matching actual test heading, an incomplete catalogue, ambiguous names or OCR-only catalogue must abstain. HCG alone does not imply urine routine. Keep value null and contributing catalogue sources, with derived origin; UI and medical Excel show 报告未载明. Manual values and explicit absence always win. Read/export projections use retained evidence and do not rewrite saved ciphertext.

## Decision audit

- [Liver abnormal-only](../../implemented/bug-fix/2026-10-09-liver-abnormal-only.md) partially overlaps: the latest explicit normal-summary request replaces its normal-liver suppression. Source binding, abnormal detail and manual/history protections remain useful; preserve and reciprocally link the old decision.
- [Normal fallback](../../implemented/bug-fix/2026-10-09-medical-normal-summary-fallback.md) partially overlaps: extend its five groups to liver and source-backed A-grade evidence. Unknown and conflicting data still abstain. No note is wholly superseded.
- [Ledger template](../../implemented/feature/2026-10-09-medical-ledger-template.md) and [native continuation](../../implemented/bug-fix/2026-10-09-native-medical-table-continuation.md) retain attribution, independent counts, required export gates and measured evidence. Partially overlap and link the new summary policy.
- Rejected automatic clinical grading and certificate localization stay rejected. Mac and hosted-auth proposals are unrelated.

## Alternatives considered

- Require a printed conclusion: gives direct quoted wording, but these laboratory sections deliberately have none and already provide measured evidence.
- Fill all empty fields as normal: simplest and visually complete, but hides genuine extraction failures and absent tests.
- Infer absence from any missing catalogue name: would cover OCR reports too, but a truncated catalogue or unrecognized synonym could falsely declare absence. Require closed numbered native evidence and abstain on ambiguous matches.
- Migrate old encrypted results: makes stored values match current policy, but needlessly risks history and manual values. Refresh read/export projections instead.

## Consequences

All six source-backed groups can summarize normal measured evidence without a printed conclusion. Unknown rows, conflicting evidence, incomplete catalogues and early unclassified history continue to abstain. Derived normal text describes report evidence, not full recognition coverage or clinical fitness. A grades do not calibrate confidence, rewrite measured classifications or clear review. Absence inference intentionally covers only closed numbered native catalogues. Manual values/absence win and historical ciphertext remains immutable. The shared frontend renderer displays existing certificate absence as 未载明/不适用 and medical absence as 报告未载明/不适用.

## Verification

Two reproducing tests fail before the fix. Final related backend suite passes116 tests in2.802s; frontend passes73 plus typecheck and candidate build. Three serial native-PDF replays retain project counts9/10/11 and confirmed abnormalities7/6/2, with0 model calls and154 pending image regions. This is mapping verification, not model accuracy. All24 saved medical results have idempotent read-only projections and matching Excel cells. Latest Kong liver is normal from7 measured rows; its5 blood abnormalities remain; urine routine and abdominal ultrasound are absent from its9-project catalogue. An initial audit assertion incorrectly covered same-person early unclassified versions; it is narrowed to the explicit latest task, without changing runtime abstention on older data.

CUA passes5 synthetic display assertions with0 browser errors. The actual downloaded18-column Excel retains normal/absent/missing/abnormal distinctions. Default-size screenshots preserve evidence; no layout redesign occurs. The isolated server stops with0 model requests or production writes. Browser and command automatic-review deadlines each time out once, then succeed on their allowed single retry; no unsafe-action rejection or bypass occurs.

After3 idle checks and an integrity-checked SQLite backup, all12 identity-verified old owned processes exit. Application1.17.3 reports both models ready and DB/worker/storage healthy. All68 task ciphertexts, one account and keys retain signatures. HTTP build files equal the qualified candidate; prior assets/build remain backed up. Evidence is in output/normal-group-fix-20261009-v1/REPORT.md. No model accuracy benchmark, sample rewrite, clinical grading, migration, Mac qualification, commit or push occurs.
