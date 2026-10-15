# Agent Note: Extend source-preserving length hints to card and certificate numbers

Status: implemented
Scope: frontend/src, frontend/tests, scripts, FRONTEND_FIELDS.md
Last-verified: 2026-10-14

## Problem

The user requests the same visible length hint for bank cards and certificate numbers as for identity numbers. A single18-character rule would mislabel valid cards, older diplomas and prefixed degree certificates. Existing saved results must benefit without rerunning OCR or rewriting human corrections.

## Decision

Use one pure frontend hint function in the saved-result and live-review views. Counts ignore whitespace; bank counts also accept full-width digits and grouping hyphens for display only. Keep values, leading zeros, source text, backend validation status and presence-only export rules unchanged. Empty fields retain the missing-field UI; absence of a length hint never establishes authenticity or checksum validity.

Keep ID and unified-social-credit lengths at18. Xuexin online-code hints use the existing12/16 compatibility lengths. For bank cards, reuse the existing pinned offline BIN dataset: generate a small committed prefix/length reference so frontend builds remain standalone. Select the most specific prefix first, and abstain for unsupported prefix lengths, ambiguous products or absent records. A length mismatch is explicitly an offline-reference warning; unknown cards show their count and uncertainty, with only the existing10–19 application compatibility range as a broad bound. Do not guess16/19 for every bank or add an online lookup.

Diploma and Xuexin certificate numbers use17/18 as common reference lengths, with shorter historical/other-type values described as informational, not invalid. Degree numbers use16 as the ordinary reference and preserve historicalT/Z-prefixed17-character values; older/special values retain a clear exception notice. No date is inferred from a possibly wrong number to tighten the rule.

## Sources and related-note audit

- [CHSI help](https://www.chsi.com.cn/help/xlcx_lscx.jsp) explicitly allows17/18-digit education identifiers and shorter early certificates.
- [MOE2005 numbering notice](https://www.moe.gov.cn/s78/A22/s7065/201001/t20100129_33128.html) gives16-character degree numbering andT/Z variants; [MOE2015 management notice](https://www.moe.gov.cn/srcsite/A22/moe_817/flfggz_xx/201507/t20150713_193671.html) specifies16 digits for the later scheme. These are compatibility hints, not complete document validation.
- [Card/document profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) owns the unchanged BIN source, longest-prefix/abstention and validation rules. Its2020 community snapshot is not an authoritative or current card-product registry.
- [Interview length hints](../../implemented/feature/2026-10-14-interview-registration-and-shared-upright.md) retain their18-character behavior; this extends the shared presentation to other types.
- [Required-value export](../../implemented/simplification/2026-10-08-required-fields-only-export.md) remains unchanged. No decision is reversed or archived. Model/deployment and rejected localization proposals are unrelated.

## Alternatives considered

- Apply18 digits universally: simplest reusable rule, but rejects valid bank and academic numbering variants.
- Warn only outside10–19 digits for bank cards: matches existing compatibility admission, but misses an18-digit transcription for a reference product using19. Use prefix-specific advisory lengths where available.
- Add live backend requests on each keystroke: avoids a small derived reference file, but introduces latency and new runtime/API work for a display hint. Generate from the existing verified dataset and test it against that source.
- Enforce modern certificate lengths strictly or repair identifiers: reduces visible anomalies, but corrupts historical/original numbers and contradicts the user's manual-review requirement.

## Verification

The191 frontend tests and typecheck/build pass, covering fixed, multiple and historical lengths; prefix specificity/abstention; front-loaded zeros; full-width/grouped card input; and source preservation. The generated1697-prefix reference matches the1709-row pinned source and hash, also checked by the generator's --check mode. Ten isolated real-HTTP/Edge workflow groups pass, including bank, diploma, degree, Xuexin and licence saved/live hints, explicit manual corrections preserving source values, the original ID flow, Excel and account isolation. [Browser evidence](../../../../output/number-length-hints-20261014-v1/interview-browser-185234/browser.json) uses synthetic materials only. The first browser attempt is retained: its selector incorrectly used the catalogue's degree label instead of the saved field label; after correcting the test locator, the full workflow passes.

## Consequences

The community bank dataset is old and certificates have uncovered formats. Wording must remain advisory and unknown rules must abstain. Publishing new hints does not retrofit backend validation metadata or change a saved task's state.

The Windows static publication verifies13 files against their live HTTP responses, minimal health remainsok and the model processes are unchanged. [Publication evidence](../../../../output/number-length-hints-20261014-v1/publication/verified.json) retains the prior static files. No backend restart, production-data rewrite or Mac deployment occurs.

## Partial supersession: explicit export disputes (2026-10-14)

The approved [explicit-dispute gate](../../implemented/feature/2026-10-14-disputed-results-export-gate.md) supersedes the presence-only permission for concrete number-length warnings, format/checksum failures and conflicts. Ordinary save cannot waive these disputes; an explicit per-dispute original-document confirmation needs no reason. Informational uncertainty remains nonblocking; required-field profiles, original evidence, atomic selection, version/ownership checks and historical verification here remain applicable. This note is not fully superseded.
