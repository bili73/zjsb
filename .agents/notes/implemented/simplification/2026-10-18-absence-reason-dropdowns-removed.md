# Agent Note: Absence-reason dropdowns removed from the review editor

Status: implemented
Scope: frontend/src/components/ReviewEditor.vue, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-18

## Problem

Every editable row in ReviewEditor carried a second 缺省原因 select offering 原件未记载/不适用：optional basic fields (缺省原因（可选）), per-item 报告等级/异常诊断, per-finding 报告等级/异常诊断/检测结果原文, and optional household-member fields. The user asked for all of them to be removed — operators did not use them and the extra dropdown doubled each row's visual density, continuing the detail-page decluttering line (2026-10-16-detail-page-declutter).

## Decision

- All four absence selects deleted from the template. The now-unreachable frontend plumbing went with them: the `absence` reactive, the `absenceObject` helper, absence slots on items/findings/members drafts, the `absence` entry in the deep dirty watch, absence_reasons assembly in the three save() bodies, and the CONFLICTING_ABSENCE member guard.
- review.ts is untouched: `AbsenceReason` and the optional `absence_reasons` fields in ReviewBody / buildReview stay because that is the backend contract layer (review.test.ts still covers it) and backend review.py still accepts absence_reasons. Only the UI producer is gone, so a saved review simply stops sending the key (it was optional).
- Display paths unchanged: business.ts fieldValueText still renders 未载明/报告未载明/不适用 for historical or backend-derived markings (medical_ledger.py auto-marks 检查清单缺失 as NOT_ON_DOCUMENT), so existing and system-derived data keeps rendering exactly as before.
- Copy synced: help section 5's 报告未载明 row no longer instructs marking 缺省原因 (now: 选填项留空即可；系统判定或此前保存的标记仍会显示); FRONTEND_FIELDS.md 新材料字段 and 医疗items review paragraphs now say 留空即可 and note the API still accepts absence_reasons.

## Alternatives considered

- Keep the optional-field dropdown and drop only the item/finding/member ones: rejected — the user asked for all of them, and the field-level one had the weakest justification (export never requires absence reasons: 选填空值无需缺省理由).
- Keep the reactive plumbing behind a disabled flag for easy restore: rejected as dead code; since the backend contract stays optional, restoring the feature is a template-only change plus passing absence_reasons through the existing buildReview call.

## Verification

Frontend typecheck and node tests pass (246 tests, including the untouched `absence and explicit acceptance are distinct and version bound` contract test); production build passes; `npm run verify` passes with this note.

## Consequences

Operators can no longer acknowledge "genuinely not on document" for item/finding-level 报告等级/异常诊断/检测结果原文: where review.py previously dropped the corresponding MISSING advisory when absence_reasons was marked, that advisory now stays listed (drawer NEED_REVIEW notice) unless the value is filled in. Those advisories do not block export (export checks required values, number validation and explicit conflicts), so this trades advisory silence for a calmer editor, not a gate change. Basic optional fields lose nothing: leaving them empty was already export-equivalent. Restoring the capability is frontend-only per the Alternatives section.
