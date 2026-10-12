# Agent Note: Restore evidence-bound field mapping and separate medical conclusions

Status: implemented
Scope: backend/ocr_app/documents.py, backend/ocr_app/extraction.py, backend/ocr_app/task_store.py, tests, scripts, SPEC.md, openapi.yaml, IMPLEMENTATION_PLAN.md, RUNTIME.md
Last-verified: 2026-09-30

## Problem

New confirmed cases are implemented in [native medical continuation](2026-10-09-native-medical-table-continuation.md) and [diploma school/date mapping](2026-10-09-diploma-school-and-date-mapping.md). They extend same-page recovery and school ranking, and replace the deliberate interval-end abstention with the user's confirmed enrollment/graduation convention. Source evidence and independent-list-count contracts remain.

The user asks to fix text-to-field mapping using the existing samples and to use medical report conclusions/counts when checking abnormal findings. Several independent losses are verified in the pre-fix pipeline rather than inferred from low OCR scores:

- The three PDF blood pages have native text and valid item/result labels. Default line-based table detection finds only two one-row header boxes, not the 24 unruled data rows. The extractor only consumes HTML tables, so all 72 frozen blood results are missing.
- The four/six/four conclusion bullets on PDF page 4 use a known private-use decorative glyph. The reliability heuristic rejects those short blocks; the current native evidence therefore loses the list, although explanation sections on later pages survive.
- The report anatomy graphic is on pages 7/7/6, not always page 6. The page-4 overall conclusions have four/six/four top-level findings without a count declaration. The user's exact title, “您共有 X项异常需进一步检查并治疗：”, identifies a separate follow-up list on pages 9/9/8 with explicit counts six/six/two. The first investigation did not distinguish these titles and concluded too early that no declaration existed. Overall findings, follow-up lists and laboratory abnormalities have different counting units.
- Certificate rules require label delimiters and narrow narrative forms. Confirmed failures include unlabelled narrative names, cross-line award/major statements, missing school-label aliases, certificate numbers swallowing trailing dates, and per-block narrative short-circuiting that suppresses later conflicting candidates.
- Medical result parsing does not recognize explicit LaTeX arrow tokens. A first-repeat audit of matched-v3 separates six formatting-equivalent arrows from one real numeric-content change. Default-profile decoded-v2 has seven numeric-content changes; the whole corpus has six. The strict original scores and encrypted outputs remain unchanged.

The [investigation report](../../../../output/field-mapping-investigation-20260930/REPORT.md) separates baseline failures, offline recovery experiments, formatting diagnostics and the scope of this implemented repair.

## Decision

The implementation restores native medical structure and repairs the confirmed certificate mapping defects under the user's approved scope. Both deployed recognition models, the production default, serial GPU ownership, confidence semantics and review/export boundaries remain intact. No third semantic model, training, medical grading or automatic truth repair is introduced.

### Native medical tables and conclusions

The successful line-based table path remains first. When real item/result header geometry exists but the body is absent, recovery uses a clipped mixed line/text strategy with observed column boundaries and text rows. It validates explicit sequence rows; neither expected values, fixed page numbers nor a fixed 24-row template participates. Original cell text and row/cell location are retained; ambiguous columns produce limitations. An entire page is never treated as an arbitrary table, and anatomy/summary prose does not become laboratory items.

The read-only exploratory clipped mixed strategy recovers all 72 reference values, but without row validation it also maps three non-laboratory rows per page. Requiring the report's actual sequence rows eliminates these extras in the three samples. A direct word-bbox approach misses one reference result per page because characters cross inferred column boundaries; it is not adopted merely because it is shorter.

Recognize the verified decorative conclusion bullet for reliability scoring without accepting arbitrary private-use text or replacement characters. Preserve the original string. Extract conclusion lists by section title, explicit list markers and source ordering, with bounded section ends and conservative continuation handling. Narrative advice, definitions, history, normal-result phrases and body-map labels are not newly inferred abnormalities.

The independent medical `report_summary` contains `scope`, `declared_count`, `findings` with stable per-run IDs and source evidence, `count_check`, and `sources`. The parser prefers the user's exact title with scope `follow_up_required`; it falls back to overall conclusions without a declaration, or unidentified without a reliable list. A declared count exists only when explicitly stated; it is never filled with observed list length. With no statement or insufficient same-list coverage, the check is unverified. It compares only within that title's list, never with another chapter's conclusions or laboratory `stats.abnormal`. Native row geometry, unique headers and complete consecutive numbering prove only local list coverage. Adjacent continuation tables must repeat its structure and continue numbering. Matching cannot establish full-report completeness or bypass review. Incomplete medical statistics remain null.

### Medical format and abnormal markers

Normalize only supported explicit display encodings for parsing, including LaTeX up/down arrows; retain `result_raw` and evidence unchanged. Never change digits, decimal positions, result units or reference numbers to match a reference. Distinguish raw-string scoring from documented format-equivalence diagnostics.

Recognize explicit report abnormal markers with bounded token rules, and distinguish negative phrases from a positive substring. An unqualified positive finding remains POSITIVE/unknown, as the existing contract requires. A report marker that conflicts with its mapped numeric reference produces a review issue instead of silently choosing a normal result. Do not introduce general clinical interpretation or the user's later grading workbook.

### Certificate mapping

Repair only confirmed label/narrative boundaries: collect all supported candidates across blocks, keep distinct values as conflicts, bound numbers and enum values, support cross-line statements and explicit date roles, and prevent major text from absorbing school or following study clauses. Dates with no determinable role stay unassigned. Source-backed values remain distinguishable from missing/ambiguous ones. The fixed four-image replay measures mapping changes, not new OCR accuracy or population generalization.

### Files and interfaces

- `documents.py`: a small native-table recovery helper and narrowly scoped reliability handling; existing `decode_pages` entry point and original evidence remain compatible.
- `extraction.py`: header/candidate normalization, the existing `extract_medical_items(evidence)` and `extract_fields(evidence, doc_type)` interfaces, plus `extract_report_summary(evidence)`; original values and unsupported layouts remain available for review.
- `task_store.py`: ensure project filters do not alter report conclusions; apply the existing result access/masking path to new content without claiming unrestricted natural-language anonymization. No new plaintext diagnostics.
- `SPEC.md`/`openapi.yaml`: additive report summary semantics and source granularity, keeping report findings separate from MedicalStats.
- `frontend/src/business.ts` and `ResultView.vue`: validate and display the independent summary, observed list length and explicitly unknown declaration; retain existing read-only review status. A full image-preview or review-edit feature remains a separate phase.
- `tests` and offline replay scripts: synthetic regression cases plus existing encrypted native/OCR samples; new CSVs store only IDs, field keys, outcomes and CPU extraction timings. Old scores and reference files are not overwritten.

## Decision audit

The [durable-task decision](../../implemented/feature/2026-09-30-durable-document-tasks.md) owns current processing, result and review boundaries and partially overlaps. The [OTSL decoder](../../implemented/bug-fix/2026-09-30-paddle-otsl-table-decoding.md) retains table-format ownership; this decision addresses missing native table bodies, field mapping and conclusions rather than reversing that adapter. The [whole-folder diagnostic](../../implemented/testing/2026-09-30-whole-medical-corpus.md) owns the frozen metrics; this work creates a new replay and never rewrites its baseline. The [dual diagnostic](../../implemented/testing/2026-09-30-dual-certificate-extraction.md) retains prompt/fusion and reference semantics; improved rules do not adopt automatic fusion. The [Paddle qualification](../../implemented/architecture/2026-09-30-paddle-vl-16-upgrade.md) receives a factual correction distinguishing numeric and format errors, while its default-retention decision remains unchanged. Existing notes partially overlap; none is completely superseded or archived.

## Alternatives considered

- Sending OCR text to a new semantic LLM can handle varied wording. It adds another deployment and cannot repair a native table body that was dropped upstream; restore structure and test the deployed recognizers' existing output first.
- A hospital/page-specific template gives excellent performance quickly. It silently binds to one layout and page count; use observed headers, sequence markers and section titles, with the current hospital as a regression sample rather than a hardcoded router.
- Full-page text-based table detection is supported and recovers the values. It also includes metadata and prose; recovery is restricted to verified table boundaries and row structure.
- Counting all report conclusions as laboratory abnormalities is easy to display. Findings may group several tests and include imaging or examination observations; keep a separate summary and count check.
- Using sample references to correct bad digits gives attractive scores. It contaminates inference and can invent medical values; only explicit formatting is normalized, and true digit errors remain visible.
- Broadening text reliability for every private-use glyph retains more text. It may admit unreadable custom-font encodings; support only the observed decorative marker in its list position and retain conservative rejection otherwise.

## Testing

- Synthetic tests reproduce header-only native tables, decorative-bullet loss, cross-line certificate fields and suppressed conflicting candidates before their fixes.
- The three native blood pages recover the 72 frozen reference results with no extra metadata rows; original sources and reference hashes remain unchanged. Inapplicable/ambiguous layouts remain reviewable rather than silently filled.
- The exact follow-up title yields six/six/two declared and observed findings with row sources and match; removing that title only in a separate diagnostic yields four/six/four overall findings with null declaration and unverified check. Page numbers and expected counts are verification only, never parsing conditions.
- Unknown count, missing/duplicate/contradictory declarations, list continuation and mismatched count have distinct synthetic outcomes; count consistency cannot publish a completed report.
- Explicit LaTeX arrow parsing does not modify numeric content; contradictory marker/range and negative phrases are covered by regression tests. The separate source-preserving investigation distinguishes strict raw, explicit-format and numeric differences without changing old scores.
- Certificate replay reports each field's before/after correct, missing and wrong values, along with conflict handling. No claimed percentage is based only on selected successful cases.
- New summary content stays encrypted at rest, is not added to diagnostics, and filters do not change it. Backend regressions, API/schema checks, frontend validation/display tests and DDE verification pass.

All 199 backend CPU tests and 24 frontend tests pass. OpenAPI TaskResult, ReportSummary and ReportFinding validation includes a mixed OCR-title/table pipeline; Vue rendering and TypeScript/production build checks pass. TaskStore filters preserve the independent encrypted summary, and synthetic tests cover ambiguous headers, opposite markers, unit letters, count declarations, contents pages and native continuation boundaries.

The [final replay report](../../../../output/field-mapping-replay-20260930-v1/REPORT.md) records 72/72 native blood reference results, no missing/wrong/ambiguous/extra rows, 72 valid row sources, and separate follow-up counts 6/6/2 with 14 valid row sources. Three PDFs take 3096.304 ms for native decoding/rendering and 213.976 ms for full-report mapping, measured once without OCR. Original source, encrypted snapshots and frozen reference hashes are unchanged.

Four-image certificate repeat1 replay preserves 39 present, 4 absent and 6 uncertain fields per model: GLM 11→37 correct, old Paddle 11→38, new Paddle 10→33. Missing/wrong counts are 1/1, 1/0 and 4/2 respectively; known-absent false fills are zero. Strict rejection of an uncertain number tail loses one apparent fill compared with the intermediate replay. Conflicts remain missing in present-field scoring. All old published scores reproduce; unchanged certificate-function hashes tie the replay to delivered code. CPU timings are stored separately from model inference measurements.

## Consequences

Native structure is recovered without extra model calls, and source-bound mapping exposes conflicting candidates instead of filling them silently. The cost is additional geometry and field-boundary logic with conservative abstention, including a lower apparent fill rate when unsupported identifier tails occur. New hospital/certificate layouts or annotated misses require a fresh regression and a review of these boundaries before adding aliases or choosing a semantic model.

Current visual references are provisional and the small hospital cohort overlaps older experiments. Geometry can become ambiguous for rotated, wrapped, missing-header or visually unusual documents. Decorative glyph repair must not make arbitrary private-use text reliable. Conclusion counts describe list structure, not clinical severity or a guaranteed full medical inventory. Rule improvements can expose previously hidden conflicts and decrease apparent fill rates. No clinical grading, calibrated confidence, complete review editor, export implementation, 16 GB hardware qualification or production-model switch is included.

## Related verification

The [certificate photo preparation](../feature/2026-10-12-certificate-image-upright.md) adds optional CPU orientation/deskew only for diploma/degree raster uploads, with the same corrected pixels used for preview and OCR. PDF/native medical evidence and these conflict/date-role contracts remain intact.

The [degree school/award repair](2026-10-12-degree-school-and-award-mapping.md) reuses certificate date/signature handling for observed degree mapping misses while retaining these source/conflict contracts and separate date roles.

The [adjacent document field repair](2026-10-12-adjacent-document-field-boundaries.md) prevents compact gender labels from becoming part of certificate holder names. It preserves the original source and existing date-role/conflict rules.

The [isolated current-pipeline acceptance](../testing/2026-10-08-current-pipeline-acceptance.md) verifies the repaired real API path with the same frozen references and a separate encrypted store. It retains the v1 historical medical timeout and distinguishes single-resident loading from inference; it does not replace these historical measurements or qualify production hardware.

The former frontend portion is retired by the [frontend retirement](../../implemented/simplification/2026-10-08-retire-temporary-frontend.md); current Scope covers surviving code. Old UI checks describe historical acceptance.

The [HR field profile](../../implemented/feature/2026-10-08-hr-document-field-profile.md) extends the existing evidence/column rules with titled personal tables, supplementary report grades and unique diagnosis/result association; it retains independent summary counts and unresolved candidates.
