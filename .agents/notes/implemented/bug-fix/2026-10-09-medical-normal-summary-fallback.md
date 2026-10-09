# Agent Note: Summarize source-backed normal groups without a printed conclusion

Status: implemented
Scope: backend/ocr_app/medical_ledger.py, tests/test_medical_ledger.py, backend/ocr_app/api.py, tests/test_runtime_api.py, tests/test_document_contract.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user sees a blank blood-routine summary even though its measured rows are recognized and normal. Requiring a printed 小结 unnecessarily leaves that ledger cell empty. The user now explicitly requests 未见异常 when there is neither an abnormality nor a printed conclusion. The immediately preceding liver abnormal-only requirement still applies.

## Decision

For blood_routine, urine_routine, ecg, dr_imaging and abdominal_ultrasound, derive 未见异常 when the observed group contains at least one eligible measured row, every group row has a real source and nonempty result, every row is NORMAL with a recognized abnormality basis, and no row has an unresolved conflict. Do not infer normal from an absent group, a catalogue entry, UNKNOWN/POSITIVE-only rows or unresolved evidence. Existing printed conclusions, confirmed abnormal summaries and conflict handling retain priority. Liver_function keeps its abnormal-only rule. Preserve manual values and explicit absence.

Keep derived origin, unavailable confidence, review obligations and contributing measured sources; the generated text is an application summary, not a quotation from a nonexistent 小结. Refresh caller-owned historical read/export projections without rewriting saved ciphertext. Unrelated partial pages do not invalidate a source-backed group, but this value never claims whole-report completeness. No grouping, counts, required export gates, model prompts or clinical/hiring rules change.

## Decision audit

- The [ledger template](../../implemented/feature/2026-10-09-medical-ledger-template.md) partially overlaps: replace only its refusal to derive a normal group without a printed conclusion. Group attribution, optional fields, measured evidence, manual priority and counts remain active. Preserve the original rationale and add reciprocal links.
- The [liver abnormal-only correction](../../implemented/bug-fix/2026-10-09-liver-abnormal-only.md) remains active unchanged; this rule explicitly excludes liver_function.
- The [biochemistry refinement](../../implemented/bug-fix/2026-10-09-biochemistry-ledger-export.md) retains newline/export styling and the later liver correction; its older normal-liver fallback is not revived.
- [Rejected automatic threshold review](../../rejected/feature/2026-10-09-medical-threshold-review.md) remains rejected. Mac/runtime proposals are unrelated. No note is wholly superseded or archived.

## Alternatives considered

- Keep blank cells and add a special UI badge: makes absence explicit and avoids derived normal text, but does not meet the user's newly requested ledger value or Excel behavior.
- Fill every empty group with 未见异常: maximizes completion and is simplest, but falsely treats absent, unrecognized and conflicting groups as normal.
- Continue requiring a literal 小结: gives exact source wording, but hides normal measured evidence in reports that do not print group conclusions.

## Consequences

Recognized normal rows no longer leave the five non-liver ledger cells unnecessarily empty. Unknown/missing groups still abstain. NORMAL summarizes the extracted evidence and is not a clinical diagnosis or a completeness guarantee. Unknown rows are never filtered out before deciding that a group is normal. Confidence stays unavailable; existing measured-item review requirements remain. The liver-only and human-priority exceptions preserve the preceding explicit user choices.

## Verification

Two reproducing tests fail before the change. The first ledger run reveals an incorrect test assumption about newly requiring review on optional summary fields; the corrected assertion verifies that existing measured-item reviews are preserved, without changing that established behavior. All failed logs remain. The relevant backend suite passes105 tests in24.346s; the final ledger suite passes19 tests. Saved results are decrypted/projected read-only with0 recognition calls and0 production task writes. 赵紫妍's blood summary becomes 未见异常 from24 normal measured rows; four workbook round-trips match projected group cells. Missing/unclassified groups and all normal liver summaries remain blank. Counts, sources, manual values/absence and raw results remain preserved.

After three idle checks and a consistent backup, all12 identity-verified old owned processes exit. Replacement Windows service1.17.2 reports GLM/Paddle ready and healthy DB/worker/storage. All64 task ciphertexts, one account, key files and existing frontend build hashes are preserved. Evidence lives in output/normal-summary-20261009-v1/. Certificate localization is separately diagnosed there as page-sized input-region sources plus same-page frontend scroll behavior; it is not changed by this implementation. No sample rewrite, model recognition benchmark, Mac qualification, commit or push occurs.

## Later measured-group summary policy

The [measured-group summary correction](../../implemented/bug-fix/2026-10-09-medical-measured-group-summaries.md) partially supersedes normal-summary eligibility: liver and source-backed A-grade measured rows can produce 未见异常 without a printed 小结. Closed numbered native catalogues distinguish report absence from missing recognition. Abnormal details, attribution, counts, manual priority, source binding, unavailable confidence, review and immutable history remain active. The older decision and measurements above retain their original rationale; no note is archived.
