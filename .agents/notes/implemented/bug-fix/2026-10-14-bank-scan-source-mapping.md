# Agent Note: Correct bank scan region selection and field semantics

Status: implemented
Scope: backend/ocr_app/bank_photocopy.py, tests/test_bank_photocopy.py, scripts/probe_bank_photocopy.py
Last-verified: 2026-10-14

## Problem

Six additional photos expose a back mistaken for a front through the phrase 网上银行, a hotline promoted to PAN, ID/social-security numbers mixed with PAN, unreadable quick-OCR lines omitted before visual recognition, and bank/branch/name values lost after recognition. The frozen baseline has 7/21 provisionally correct fields and 3/6 correct final PANs.

## Decision

Use positive issuer/card evidence and negative back-service evidence together. Keep nearby detected text pixels for visual recognition even when quick OCR cannot read the text. Recognize aligned side supplements when source cues connect them to a single card; retain ambiguity for multiple fronts and keep neighboring forms outside the association. Preserve the existing whole-image fallback when outlines cannot be established, with local supplementary recognition where observed labels/phone context justify it.

Extract PANs by line context, excluding labelled non-card numbers and independently valid dated Chinese ID numbers when they are not explicitly labelled bank PANs. Never repair digits, choose by Luhn, or discard genuine conflicting PANs. Separate bank institution from branch, join observed multiline branch text, reject signature boilerplate as names, and retain source evidence. No new model, public fields, required-field policy or account/export changes.

## Related-note audit

[Stable bank-name spelling](2026-10-19-stable-bank-script-spelling.md) records the limited Mac backport; the later [non-name bank conversion](../feature/2026-10-19-bank-non-name-simplification.md) expands new bank/branch text to offline t2s conversion. Source evidence, genuine conflicts, PAN and personal names remain under this correction; stored/manual results are not converted.

This is a correction to [photocopy support](../../implemented/feature/2026-10-14-bank-photocopy-handwriting.md), partially replacing its positive-text-only supplement gate and same-column restriction. Its source/conflict/privacy/model-budget decisions remain. [Automatic admission](../../implemented/feature/2026-10-09-bank-auto-recognition.md) and [orientation](../../implemented/bug-fix/2026-10-12-bank-card-roi-orientation.md) remain in force. Proposed Mac/auth work and rejected generic certificate localization are unrelated; nothing is archived.

## Alternatives considered

- Whole-page OCR retains all pixels with minimal planning, but the retained baseline demonstrates back boilerplate contamination and tiny handwriting. Keep it as a fallback, not the sole path.
- Recognizing only semantically valid quick-OCR lines minimizes calls, but excludes precisely the handwriting that needs the visual model. Use geometric context without trusting quick text as the final value.
- PAN checksum or BIN selection can resolve some candidate conflicts cheaply, but cannot establish the intended account. Exclude explicit non-PAN evidence and keep true conflicts instead.

## Verification

Twenty focused tests cover wrong-back selection, hotline/ID contamination, side and unreadable handwriting, multiline branches, signature names, bank script equivalence and preserved genuine conflicts. The complete backend suite passes754 tests in260.290s. Prior failed regressions are retained; compatibility checks exposed raw Unicode source normalization and discarded unknown labelled issuer conflicts, both repaired without changing the assertions.

All six scans and four original bank samples are remeasured serially with one model resident, unchanged original hashes and frozen code hashes. The [comparison](../../../../output/bank-scans-comparison-20261014-v3/REPORT.md) uses the same21 provisional references for the new scans:7/21 becomes20/21; PAN3/6 becomes6/6, bank2/6 becomes6/6, branch1/5 becomes5/5, name1/4 becomes3/4. Mean document latency4.779s becomes4.685s; startup8.516s is separate. Original samples are9/10 source-present fields, with three ordinary cards unchanged and the original faint photocopy PAN still conflicting. All16 GLM calls reach EOS; Paddle is not called and is not a comparison arm. Historical outputs and intermediate runs remain intact.

The idle production service is backed up and restored dual-resident. Both models warm successfully. All11 business tables,272 tasks,2 accounts,2825 existing material/key files and13 static files match the pre-test snapshot; anonymous business routes remain401. Evidence is linked from the comparison report. No historical task or manual correction is recomputed.

## Consequences

Geometric crops can contain unrelated text or cut handwriting; association remains reviewable and never proves ownership. The six new scans are tuning data, and one photographs previously tested material. Provisional visual labels and regression improvements are not independent production accuracy or Mac performance.

New sample05 still produces an incomplete name after local recognition. New sample01 has an uncertain handwritten reference excluded from the accuracy denominator, and the original faint photocopy still requires a human PAN choice. A reference merely present among candidates does not count as a correct final field. Absent name/branch values are not invented. No new model, API schema, frontend behavior or export policy is introduced by this correction.
