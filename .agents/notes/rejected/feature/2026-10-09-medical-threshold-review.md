# Agent Note: Compare source-backed medical values and retain human employment decisions

Status: rejected — the user assigns this judgment to humans; keep a manual Excel opinion column and no automated grading or hiring decision
Scope: backend/ocr_app, frontend/src, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

The user asks to compare medical reports with the workbook at F:\dingding\体检异常分级管理工具包（结合先行入职体检参考标准）.xlsx and add an employment-related field to Excel. Read-only inspection finds 32 rule rows (5–36) on 三级指标阈值总表 and a separate informed-declaration checklist. These are company-authored threshold/prose rules, not a complete executable medical or employment standard.

Some ranges are incomplete or ambiguous: ALT uses second-tier 50–150, first-tier >500 and third-tier <50, leaving >150 through 500 undefined; WBC leaves >9.5 through <12 undefined and has shared endpoints. Urine glucose needs blood glucose; urine occult blood needs repeat testing and clinical exclusion; other rows require symptoms, disease evidence or professional imaging interpretation. Several rules depend on role, while the current report carries no applied-job field. The company's tier and the report's A/E3 grade are independent classifications.

HBsAg and age-linked automatic non-hiring prose must not become a programmatic employment gate. The [official 2010 notification](https://www.mohrss.gov.cn/xxgk2020/fdzdgknr/zcfg/gfxwj/jy/201407/t20140717_136568.html) restricts general employment hepatitis-B testing and rejection; [Employment Promotion Law article 30](https://www.mohrss.gov.cn/xxgk2020/fdzdgknr/zcfg/fl/202011/t20201102_394626.html?xxgkhide=1) protects pathogen carriers subject to professionally established statutory occupational exceptions. Company text cannot establish such an exception. This note proposes a review aid, not automated hiring based on health or age.

## Proposal

Keep the current business Excel layout until the business team supplies its template, but add reference-threshold review and a separately saved human hiring-opinion field after the user approves this narrowed contract. Automated output is limited to observed measurements, objective threshold comparison, evidence/cell reference, matching completeness and what remains unresolved. The program does not produce hire/reject/restricted-hire decisions or use flagged health/age prose to exclude applicants.

Extract a versioned local rule catalogue from the source with its SHA256, worksheet/cell coordinates, units, strict/inclusive endpoints and original text. Business/medical/legal owners need to resolve gaps and job/legal applicability before affected rules are enabled. Ship approved data with the application rather than depend on a Windows F: path at runtime. Keep report grade separate from reference rule metadata.

Allow a reviewer to record relevant job category and confirm measurement aliases/units/context. Use all saved verified measurements, not only the abnormal display filter; missing measurements or incomplete coverage cannot imply normality. Match ALT/AST/etc. by explicit labels and verified aliases; do not confuse platelet distribution width with PLT. Normalize safe compatible units and urine signs (+3 versus +++) without losing raw text. Unsupported units, multiple candidates, ambiguous range endpoints, cofactor/symptom requirements and unmatched rules yield an explicit unresolved/needs-professional-review result, not a guessed tier or employment outcome.

For Excel add 参考阈值核对, 需补资料／复查 and 人工录取意见 to the medical summary, with per-abnormal detail references as appropriate. Hiring opinion defaults to 待人工决定, is manually supplied by an authorized human and keeps actor/version history. Keep the existing required-value-only export gate; the new review fields do not silently create a new blocking requirement. Human findings, source values, hospital grades and clinical diagnoses are never replaced by company-tier guesses. Final business-template rearrangement remains a separate future change.

## Decision audit

[Business Excel](../../implemented/feature/2026-10-09-business-xlsx-layout.md) provides the present layout and saved-snapshot contract; this proposal adds review columns without replacing it. [HR fields](../../implemented/feature/2026-10-08-hr-document-field-profile.md) retain literal hospital grades and diagnoses. [Required-value export](../../implemented/simplification/2026-10-08-required-fields-only-export.md) retains its gate. [Native continuation](../../implemented/bug-fix/2026-10-09-native-medical-table-continuation.md) retains incomplete-coverage conservatism. These decisions partially overlap and remain active; none is wholly superseded or archived. No existing grading owner is found by topic search.

## Alternatives considered

The later approved [medical ledger template](../../implemented/feature/2026-10-09-medical-ledger-template.md) removes the temporary opinion placeholder because it is absent from the supplied eighteen-column layout. This does not reopen automated threshold grading or employment decisions; the user explicitly keeps judgment with humans and treats the Word workflow only as reference.

- Apply the table's strongest tier as automatic hire/reject output: easy to automate and resembles the workbook labels; it makes a consequential employment decision from sensitive health/age, includes unverified job/legal restrictions and hides gaps. Do not implement this.
- Ask a language model to interpret every rule and infer missing conditions: handles prose variation, but cannot establish medical facts, legal exceptions or missing ranges. Use source-backed deterministic comparisons plus explicit unresolved states.
- Evaluate only already displayed abnormalities: cheap and readable, but companion normal findings and missing coverage affect applicability. Use the full saved evidence, never treat missing as normal.
- Build all 32 rows as active rules immediately: broad coverage, but ambiguous endpoints and unresolved professional/job restrictions would become undocumented assumptions. Catalogue them first and enable only confirmed objective rules.

## Acceptance criteria

Boundary, gap, alias, urine-sign and unit fixtures compare only unambiguous source-backed facts. Job unknown, missing cofactors, uncertain interpretation and incomplete report coverage are explicit. Excluded health/age employment logic remains disabled, no automatic hiring outcome is generated. Human opinion is versioned and exports exactly as saved. Every comparison includes its source and rule version; workbook original and historical OCR outputs remain untouched. Template layout change and Mac throughput are not claimed by this feature.

## Risks

The source contains gaps, mixed medical/employment wording and rules needing clinical judgment. A developer must not fill those gaps with personal medical guesses or interpret an HR confirmation as establishing medical/legal applicability. This proposal awaits approval of the human-review output and review by the responsible business/medical/legal owners; no grading code or export field is implemented by writing this note.
