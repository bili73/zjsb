# Agent Note: Simplify diploma output and extract evidence-bound medical personal information, grades and diagnoses

Status: implemented
Scope: backend/ocr_app/extraction.py, backend/ocr_app/documents.py, backend/ocr_app/task_store.py, tests, scripts, SPEC.md, openapi.yaml, backend/ocr_app/api.py, RUNTIME.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, FRONTEND_FIELDS.md
Last-verified: 2026-10-08

## Problem

The user wants diploma principal/study_mode removed, personal information from the table below 一、个人信息, and abnormal indicators with detection result and abnormal diagnosis. The three real PDFs place the table on page4 but page3 also mentions the title in a contents list. The previous generic label parsing missed native table values, lacks marital_status/phone/work_unit, and conflicts on repeated exam dates. Medical rows previously discarded grade columns while diagnoses live in a separate conclusion table.

## Decision

DIPLOMA returns11 structured fields instead of13, retaining six required keys and removing only principal/study_mode. DEGREE_CERT keeps study_mode. Deprecated diploma labels remain parsing boundaries so neighboring school, major and certificate values do not absorb them. The same public projection applies to encrypted historical results without rewriting original evidence, histories or frozen benchmark denominators.

Medical personal name/gender/age/exam_date/marital_status/phone/work_unit come preferentially from the actual labelled table associated with the section title, not a fixed page or a contents-line match. Conflicting candidates remain reviewable; absent or ambiguous fields are never guessed. Existing metadata extraction remains source-bound outside this personal subsection. Observed personal-section or contents mentions without a reliable matching table block fallback for personal keys; a report without any such title retains the existing plain-label fallback. Section boundaries include observed numbered heading syntax, and unsupported layouts abstain.

Medical result items add nullable risk_grade and diagnosis, with explicit source links for separately derived diagnosis. A nonempty grade other than A or / adds confirmed report_grade abnormal evidence; A or / does not clear arrow/reference/explicit-diagnosis abnormal facts. A uniquely associated summary grade is independently sufficient even if a diagnosis conflicts; preserve detail and summary grade values/source scopes, and do not use a diagnosis conflict to erase that grade evidence. Real samples contain four slash-grade arrow anomalies and four slash-grade conclusion diagnoses. Missing grades are not treated as normal. Diagnostic list findings retain their grade and diagnosis; detection results attach only where a report item association is unique and supported, otherwise remain missing with review issues. Report-level list counts remain separate from laboratory item counts. Following the user correction on 2026-10-08, exact 小结 section rows (ignoring whitespace and a trailing colon) are excluded from newly extracted medical items before abnormal classification and result association; the source evidence and independent conclusion list remain intact. Substring matches are not used. Historical encrypted runs remain immutable and require rerun to obtain the changed mapping.

Recognized mainland ASCII medical mobile values/candidates (including observed separators/country prefix) are masked to the last four digits consistently across the public response, including source/generic copies; encrypted originals remain untouched. Do not classify every unrelated11-digit laboratory value as a phone.

SPEC is v1.14 and API/app version is1.12.0 alongside extraction and public result behavior, retaining masking, unknown confidence, NEED_REVIEW and null full-coverage statistics. FRONTEND_FIELDS.md describes only the implemented payload and routes. It binds local preview through raw-file SHA256 and Task.content_hash because upload deduplication invalidates raw submission indexes; it does not promise masking of unqualified fixed/international/fullwidth phone formats. It distinguishes unique result association from diagnosis conflicts, including optional compatibility for historical medical responses and unavailable review/preview/export operations. CPU synthetic regressions and reliable native-PDF evidence replay use fresh outputs; no additional model, medical grading policy or historical measurement rewrite.

## Decision audit

The implemented [medical continuation](../bug-fix/2026-10-09-native-medical-table-continuation.md) and [diploma mapping](../bug-fix/2026-10-09-diploma-school-and-date-mapping.md) repairs extend source handling while preserving this profile's fields and removed signatory/medical fields. The user confirms interval start/end as enrollment/graduation on 2026-10-09, with footer issuance kept separate.

The [evidence-bound mapping](../bug-fix/2026-09-30-evidence-bound-field-mapping.md), [durable task](2026-09-30-durable-document-tasks.md) and [diagnostics](2026-09-30-local-diagnostics.md) decisions partially overlap and remain in force; links in those notes point back to this extension. The [temporary frontend is retired](../simplification/2026-10-08-retire-temporary-frontend.md) in a separate decision. No runtime concurrency or Mac proposal is changed; nothing is fully superseded by this field profile.

## Alternatives considered

The approved [medical ledger template](../../implemented/feature/2026-10-09-medical-ledger-template.md) replaces only the medical primary-field layout: retire marital_status/phone/work_unit from current structured fields while preserving raw/historical evidence, restore institution/report_date and add measurements/group summaries. Personal-section priority, literal report grades/diagnoses, diploma mapping and confidence boundaries remain active.

- Merely hide fields in frontend: this avoids backend changes, but the user confirms this round includes backend and all clients must see the same diploma contract.
- Remove deprecated labels from parsing entirely: this is smallest but verified synthetic texts then lose certificate number, major and school fields. Keep boundary recognition without exposing these values.
- Read personal data only from PDF page4: it is correct for today's samples but wrong after insertions or alternate templates; locate the titled section and verified table.
- Use grade as exclusive normal/abnormal classifier: this matches a simple switch but discards observed slash-grade arrows and explicit abnormal diagnoses. Use grade as an additional sufficient signal.
- Hide 小结 only in the UI: it avoids parser changes but leaves backend abnormal classification, linking and export with the spurious rows. Exclude the exact section label at extraction while retaining evidence.
- Remove all names containing 小结: it catches more spellings but can discard legitimate longer project names without evidence. Restrict normalization to whitespace and trailing colon.
- Link diagnoses to any similar result name: it produces more filled fields but can misattribute a grouped finding. Require unambiguous observed correspondence and preserve unresolved findings for human review.
- Mask every11-digit number: this can catch unrecognized phones, but can also hide unrelated laboratory/identifier values. Only recognized mainland mobile values/candidates authorize equivalent-format masking across that response.
- Bind previews by original submission index: this is simple, but verified batch deduplication makes [A,A,B] return only two tasks. Match raw-file SHA256 to public Task.content_hash before associating originals.

## Testing

- New and historical HTTP diploma output omit exactly the two keys; degree study_mode and neighboring parsed values remain intact. Repeated reads preserve encrypted blobs, database history, run/revision, original evidence and source identities.
- Synthetic moved-page/contents/native-table/conflict cases verify personal information provenance; current native PDF replay identifies the actual tables without exposing private text.
- Recognized non-A/non-slash grades become abnormal, slash/A preserve existing anomaly facts, and absent/uncertain grade/result/diagnosis remains reviewable.
- Complete generated → encrypted publish → authenticated HTTP responses validate against the current TaskResult schema. Tests cover legacy optional fields, all result projections, phone candidates/equivalent observed formats, source identity, unrelated11-digit numbers and health/schema version agreement.
- All309 backend CPU tests pass with0 failures/errors/skips;25 are new HR regressions. The first full-suite attempt retains a failed stale1.10.0 health assertion in [verification v1](../../../../output/hr-profile-verification-20261008-v1/summary.json); the synchronized1.12.0 test and exact source hashes pass in [verification v2](../../../../output/hr-profile-verification-20261008-v2/summary.json). DDE verify and index --check are delivery gates.
- Final [native replay v2](../../../../output/hr-medical-native-replay-20261008-v2/summary.json) keeps source/code/frozen-reference hashes unchanged during the run. Three PDFs supply21/21 nonempty personal fields with valid page4 cell sources; these are filling/source observations, not independently labelled personal accuracy. The frozen blood subset remains72/72. Native detection rows total212; independent summary lists remain6/6/2 with count match.11/14 findings uniquely link results,3 retain null+MISSING; diagnosis/result sources each11/11 are valid. Non-A/non-slash detail grades4/5/2 all retain abnormal status.
- Replay performs0 model calls and leaves154 image regions pending. All full-coverage stats remainnull. It does not qualify whole-report OCR, a new hospital template, clinical judgment, GPU timing, Mac or16GB deployment. Earlier v1 replay and all previous measurements remain intact.

## Consequences

Personal fields and separate report grades/diagnoses are available to the new frontend; exact ambiguous associations remain visible instead of being guessed. Recognized phone copies are masked with source geometry retained. The [frontend handoff](../../../../FRONTEND_FIELDS.md) distinguishes live routes from planned review/preview/export operations and uses content hashes for original-file mapping after upload deduplication.

Template title and columns may vary, so unsupported layouts abstain. Grade spelling is report evidence, not calibrated clinical severity. The diagnosis list has no result column and some findings cover multiple detail items; unknown associations must remain visibly incomplete. Original evidence can still contain retired diploma labels even though structured output does not.


## Current contract extension

The later user-authorized [internal full-value policy](2026-10-08-internal-unmasking-and-review-friction.md) replaces this note's phone/number masking boundary only; historical encrypted evidence and measured field results remain unchanged. [Review and export](2026-10-08-human-review-and-xlsx-export.md) extend its read-only delivery.


## Subsection-label verification

User-requested exact 小结 exclusion passes2 focused tests (including whitespace/colon, genuine longer names, abnormal preservation, source immutability and independent list counts). The CPU suite at this mapping checkpoint passes387 tests in11.804s; later card and batch changes have a separate final delivery gate. A new native-only replay in output/medical-subsection-label-replay-20261008-v1 removes4/5/5 summary rows:66→62,72→67,74→69 projects. Ordinary items and abnormalities, generic/page evidence and independent conclusion lists compare equal; declared/observed lists remain6/6,6/6,2/2 with match and the frozen blood subset72/72. Source hashes remain unchanged and model calls are0;154 pending graphical regions remain unrecognized, so this is mapping regression rather than whole-report accuracy. Frozen v1 uses an LF-normalized extraction hash; an independent source-equivalence artifact proves equality to the final CRLF file bytes with identical AST. No original result is rewritten.

## Medical catalogue and anomaly scope

The implemented [examination-project catalogue](2026-10-08-medical-project-catalogue.md) retires report_no/report_date/package_name/institution and adds the separate optional exam_projects field; medical required keys are now name/gender/exam_date. It also excludes exact height/weight measurements from operational anomaly filtering/statistics while preserving raw values, grade/diagnosis facts, BMI and independent report-summary counts. Personal-section extraction, findings, 小结 exclusion and frozen measurements here remain active; this is partial extension rather than archival. Authenticated historical projections and save/reload/XLSX use the current profile without rewriting original encrypted runs.

The [review-scope fix](../bug-fix/2026-10-08-medical-review-scope.md) also excludes height/weight and old exact 小结 item records from human-review blockers, without rewriting their recognition evidence or the frozen replay above. New extracted 小结 rows are still suppressed by this note's extraction guard.

The [cover-institution refinement](../bug-fix/2026-10-09-medical-cover-institution.md) preserves personal-section priority and limits the restored optional institution fallback to complete source-backed branches in the observed cover row.
