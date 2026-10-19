# Agent Note: Recognize bank photocopies and handwritten supplements in BANK_CARD

Status: implemented
Scope: backend/ocr_app, tests, scripts, frontend/src, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-14

## Problem

The single-card orientation and whole-image OCR path can select the back of a photocopied card, omit handwriting, and mix unrelated neighboring forms. The requested output is name, card number, bank and opening branch in the existing entry.

## Decision

The profile reuses holder_name and bank_name with labels 姓名 and 开户行, adds optional branch_name, and puts these four business fields first. Existing required-field settings remain authoritative. The pipeline identifies front-card and supplemental regions without sample-specific coordinates; retain the ordinary-card path when no composite layout is established. GLM is primary and Paddle is the incomplete-output fallback. Both read the sample handwriting identically, while both misread the faint printed PAN, so automatically combining guesses is unjustified. Generation is bounded to 40 seconds and the task to 180 seconds. The pipeline preserves the 180-second task deadline, partial evidence, source coordinates, human corrections, offline BIN provenance and conflict review. Branch names come only from source text. Printed and handwritten numbers must not be reconciled by checksum guessing. Unknown multi-person/card associations require review.

## Related-note audit

- [Stable bank-name spelling](../bug-fix/2026-10-19-stable-bank-script-spelling.md) records the limited Mac spelling backport. The subsequent [non-name bank conversion](2026-10-19-bank-non-name-simplification.md) expands new bank/branch and other non-name text to offline t2s conversion. The original OCR and source.raw_text remain exact; personal names/PAN, history and manual values retain this note's preservation rules.

- [Separate photocopy entry](2026-10-19-bank-photocopy-entry.md) replaces only the unified business-type choice: BANK_CARD_COPY has four default required account fields, while BANK_CARD retains its existing defaults and historical records. The shared bank algorithms, provenance and historical results in this note remain active; this partial replacement does not archive the recognition decision.

- Partial overlap: [profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md), [bank orientation](../../implemented/bug-fix/2026-10-12-bank-card-roi-orientation.md), [automatic admission](../../implemented/feature/2026-10-09-bank-auto-recognition.md). Retain their ordinary-card and evidence rules; this adds photocopy regions and handwriting.
- Retained constraints: independent model queues, configurable required fields and required-only export; no architecture reversal.
- [Scan source-mapping correction](../bug-fix/2026-10-14-bank-scan-source-mapping.md) replaces the initial same-column/quick-text supplement gate with contextual side and adjacent-line coverage, and adds number semantics and issuer/branch corrections. The initial failed baseline below is retained as evidence; current results are recorded in that correction.
- Rejected certificate field localization remains rejected for other certificates; no general certificate localization revival.
- Generic forms/table notes and Mac proposals are independent; no note is fully superseded or archived.

## Alternatives considered

- Whole-page OCR is simplest and retains every handwritten line, but includes card-back details and adjacent unrelated forms and shrinks the important characters.
- A separate photocopy entry gives an explicit mode, but asks users to classify inputs and duplicates correction/export logic.
- A new handwriting model might improve difficult handwriting, but adds unmeasured operational cost; qualify the two installed models first.

## Verified scope

Serial isolated model measurements retain the unchanged source and every failed field outcome; one sample does not establish general accuracy. Regression covers ordinary cards, matching/conflicting PAN sources, phone separation, ambiguous associations, branch provenance, configurable requirements, correction and both export paths. Production accounts/tasks remain separate from the qualification output.

## Consequences

One photocopy cannot establish coverage of other handwriting/layouts. Card surfaces and handwriting may remain ambiguous and require human review. CPU region planning must not silently treat a back or neighboring form as a front. No source images, recognized personal data or keys enter Git.


## Verification evidence

The isolated manual-region qualification records four EOS calls and separate loading timings in [report](../../../../output/bank-photocopy-models-20261014-v1/REPORT.md). Automatic pipeline runs use all four unchanged originals: the photocopy takes5.453s across four regions; the three ordinary cards take5.063/1.719/3.703s and stay on the single-region path. All seven generations reach EOS. These are single-resident serial Windows timings, not production throughput, Mac results or held-out accuracy.

The first automatic run misses bank_name because the model emits traditional 銀行. Its failed field outcome remains preserved. The [frozen-output replay](../../../../output/bank-photocopy-field-replay-20261014-v2/summary.json) with the repaired suffix handles the bank source without new inference. Three core fields have values; PAN remains null with both printed and handwritten candidates. The visible source supports a provisional manual reading, not independent ground truth or account ownership validation.

[CPU rotation checks](../../../../output/bank-photocopy-upright-20261014-v2/results.json) cover16 inputs from4 originals. The photocopy's three synthetic right-angle turns are recovered and retain all four regions; baseline recovers one of those three. The twelve ordinary-card rotation decisions are unchanged from HEAD; existing abstentions are retained. This is layout/orientation evidence, not OCR accuracy on rotated inputs.

Fourteen focused tests cover phone separation, traditional bank print, matching/conflicting PANs, back/neighbor exclusion, multi-card abstention, manual corrections, historical projection and ordinary/person-package exports. Contract tests cover candidate sources; frontend parsing rejects invalid coordinates. The isolated browser confirms source overlay, draft-only candidate selection, save/reopen persistence and actual four-field XLSX download. Source and key data remain outside Git. First regression failures (English holder-name compatibility and the intentional legacy projection change) are retained with fixes and updated contract assertions. Final regression and safe local activation are recorded in RUNTIME.md.


Final code verification:748 backend tests pass in264.595s;173 frontend tests and typecheck/build pass. Local activation/data checks are recorded separately in RUNTIME.md.

The additional six-photo qualification exposes unresolved coverage failures; implementation status does not imply acceptance. The [frozen baseline](../../../../output/bank-scans-20261014-v1/REPORT.md) records eight GLM calls, all EOS, no Paddle fallback, and2.344–8.078s per document (mean4.779s; startup7.016s separate). Provisional assistant visual labels give7/21 correct final fields, including3/6 PANs; one uncertain reference and two absent fields are excluded, not counted as successes. Two correct PANs survive only as conflicting candidates. One back is selected as a front and its hotline numbers become a wrong PAN. Side handwriting exclusion, social-ID contamination, signature-label confusion, multiline branches and bank/branch mapping remain unresolved. Fourteen reference values appear in raw OCR but only seven reach correct final fields. These are six photographs, including a new photo of the prior material, not independent production accuracy. No rules are changed during this measurement. The service is restored with both models ready and272 tasks,2 accounts and existing data/static files verified unchanged; detailed restoration evidence is linked from the report.
