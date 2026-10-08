# Agent Note: Simplify diploma output and extract evidence-bound medical personal information, grades and diagnoses

Status: proposed
Scope: backend/ocr_app/extraction.py, backend/ocr_app/documents.py, backend/ocr_app/task_store.py, tests, scripts, SPEC.md, openapi.yaml, RUNTIME.md
Last-verified: 2026-10-08

## Problem

The user wants diploma principal/study_mode removed, personal information from the table below 一、个人信息, and abnormal indicators with detection result and abnormal diagnosis. The three real PDFs place the table on page4 but page3 also mentions the title in a contents list. Current generic label parsing misses native table values, lacks marital_status/phone/work_unit, and conflicts on repeated exam dates. Medical rows discard grade columns and diagnoses live in a separate conclusion table.

## Proposal

DIPLOMA returns11 structured fields instead of13, retaining six required keys and removing only principal/study_mode. DEGREE_CERT keeps study_mode. Deprecated diploma labels remain parsing boundaries so neighboring school, major and certificate values do not absorb them. Apply the same public projection to encrypted historical results without rewriting original evidence, histories or frozen benchmark denominators.

Medical personal name/gender/age/exam_date/marital_status/phone/work_unit come preferentially from the actual labelled table associated with the section title, not a fixed page or a contents-line match. Conflicting candidates remain reviewable; absent or ambiguous fields are never guessed. Existing metadata extraction remains source-bound outside this personal subsection.

Medical result items add nullable risk_grade and diagnosis, with explicit source links for separately derived diagnosis. A nonempty grade other than A or / adds confirmed report_grade abnormal evidence; A or / does not clear arrow/reference/explicit-diagnosis abnormal facts. Real samples contain four slash-grade arrow anomalies and four slash-grade conclusion diagnoses. Missing grades are not treated as normal. Diagnostic list findings retain their grade and diagnosis; detection results attach only where a report item association is unique and supported, otherwise remain missing with review issues. Report-level list counts remain separate from laboratory item counts.

Update SPEC/OpenAPI alongside extraction and public result behavior, retaining masking, unknown confidence, NEED_REVIEW and null full-coverage statistics. Use CPU synthetic regressions and reliable native-PDF evidence replay in fresh outputs; no additional model, medical grading policy or historical measurement rewrite.

## Decision audit

The evidence-bound mapping, durable task and diagnostics decisions partially overlap and remain in force. The temporary frontend is retired in a separate decision. No runtime concurrency or Mac proposal is changed; nothing is fully superseded by this field profile.

## Alternatives considered

- Merely hide fields in frontend: this avoids backend changes, but the user confirms this round includes backend and all clients must see the same diploma contract.
- Remove deprecated labels from parsing entirely: this is smallest but verified synthetic texts then lose certificate number, major and school fields. Keep boundary recognition without exposing these values.
- Read personal data only from PDF page4: it is correct for today's samples but wrong after insertions or alternate templates; locate the titled section and verified table.
- Use grade as exclusive normal/abnormal classifier: this matches a simple switch but discards observed slash-grade arrows and explicit abnormal diagnoses. Use grade as an additional sufficient signal.
- Link diagnoses to any similar result name: it produces more filled fields but can misattribute a grouped finding. Require unambiguous observed correspondence and preserve unresolved findings for human review.

## Acceptance criteria

- New and historical diploma public output omit exactly the two keys; degree study_mode and neighboring parsed values remain intact.
- Synthetic moved-page/contents/native-table/conflict cases verify personal information provenance; current native PDF replay identifies the actual tables without exposing private text.
- Recognized non-A/non-slash grades become abnormal, slash/A preserve existing anomaly facts, and absent/uncertain grade/result/diagnosis remains reviewable.
- API schema agrees with fields, grade basis and separate diagnosis source; relevant CPU tests and DDE checks pass.

## Risks

Template title and columns may vary, so unsupported layouts abstain. Grade spelling is report evidence, not calibrated clinical severity. The diagnosis list has no result column and some findings cover multiple detail items; unknown associations must remain visibly incomplete. Original evidence can still contain retired diploma labels even though structured output does not.
