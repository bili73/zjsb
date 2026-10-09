# Agent Note: Read the known medical institution from its cover information row

Status: implemented
Scope: backend/ocr_app/medical_ledger.py, tests/test_medical_cover_institution.py, SPEC.md, openapi.yaml, backend/ocr_app/api.py, RUNTIME.md, FRONTEND_FIELDS.md, ARCHITECTURE.md, tests/test_document_contract.py, tests/test_runtime_api.py
Last-verified: 2026-10-09

## Problem

The user locates institution on PDF page one, in the final personal-information row to the right of the portrait. The three source covers print 普潓年华健康体检中心, a parenthesized branch and a separate numeric branch code. Current fallback accepts any standalone hospital-like line anywhere on page one and retains the trailing code. The user needs the printed full branch name and accepts manual entry for other institutions or unreadable evidence.

## Decision

When no explicit institution value or conflict already exists, accept the complete observed 普潓/普惠年华健康体检中心 branch line only on page one and within the observed lower-right personal-information band (normalized x-start at least .35, y-start .50 to .75, with a nonempty bounded rectangle). Preserve the actually read prefix and branch, without replacing 惠/潓 or inventing a branch. Remove only a separate trailing parenthesized numeric code from the value; keep the entire source text and geometry. A broad whole-page OCR box does not prove this location and abstains. Different eligible branches conflict. Do not infer from logos, filenames, employer, later pages or mere brand occurrence.

Explicitly labelled institution fields and saved manual values retain their existing semantics. Unknown standalone hospital lines no longer supply this convenience fallback. No additional model, page crop, public field or required gate is introduced. API/application patch version identifies the delivered mapper.

## Decision audit

- [Medical ledger](../../implemented/feature/2026-10-09-medical-ledger-template.md): partial overlap; narrow its generic cover fallback, retain optional fields, evidence preservation, human judgment and eighteen-column output. Neither note is absorbed or archived.
- [Medical personal fields](../../implemented/feature/2026-10-08-hr-document-field-profile.md): retain personal-table priority and original-grade semantics.
- [Accuracy refresh](../../implemented/testing/2026-10-09-diploma-accuracy-refresh.md): owns the separate serial fresh certificate experiment, not these extraction semantics.

## Alternatives considered

- Keep generic page-one hospital matching: can handle more hospitals with little code, but ignores the user's precise source location and can consume unrelated institution text.
- Fill a fixed company name plus a guessed branch: needs no recognition and looks complete, but fabricates the branch and cannot establish original source.
- Add an OCR crop/model request for every cover: can help scanned reports, but these sources already have reliable positioned text. Preserve existing OCR routing and abstain where location is unavailable.

## Verified invariants

Known cover branches preserve their printed names without the numeric code; wrong page/position, incomplete name, broad OCR, unknown standalone hospitals and contradictory branches abstain or conflict. Raw source text and original samples are unchanged. Real three-PDF native extraction and relevant/full backend regressions qualify the rule. The normal user service is restored after the independently authorized serial benchmark.

## Consequences

The relative band is supported by three covers from the same hospital family, not a universal detector. Graphic-only or changed-layout covers may require manual entry. Native mapping correctness is separate from full-report OCR accuracy.

The bounded fallback avoids a new model call and preserves a usable full branch name. It deliberately loses generic standalone-hospital coverage; revisit only when additional hospital/layout evidence is supplied, rather than widening the band by guesswork.

## Verification

Six new cover tests first reproduced the old wrong-position/trailing-code behavior, then passed with the narrow source rule. They cover literal prefix, wrong page/position, full-page OCR, incomplete/unknown names, branch conflicts and retained explicit labels. Three source covers were rendered and visually inspected; all three native PDF values match the complete printed branch with page-one sources, while their trailing numeric code remains in raw evidence. The CPU replay performs zero model calls or production writes; project counts 9/10/11 and abnormal counts 7/6/2 remain unchanged. Its 154 image boxes are unrun, so this is not whole-report accuracy.

All 469 backend tests pass in 111.809 seconds. SPEC v1.19 and API/application 1.16.1 identify the delivered mapping. After the separate serial benchmark, both production models are ready and original 52 task ciphertexts, one account and key hashes match the pre-pause snapshot. [Measured evidence](../../../../output/accuracy-20261009-v1/REPORT.md), [native replay](../../../../output/accuracy-20261009-v1/medical-native/summary.json) and [restore check](../../../../output/accuracy-20261009-v1/service/after.json) retain scope and source hashes.
