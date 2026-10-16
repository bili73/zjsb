# Agent Note: Detail page decluttered (tags, confidence, helper small text removed)

Status: implemented
Scope: frontend/src/components, frontend/src/business.ts, frontend/src/workbench.ts, frontend/src/guide.ts, frontend/tests, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-16

## Problem

The result drawer carried dense always-on annotation: per-field 待核对 / 核对项 N tags with issue tooltips, a 置信度 …/未标定 span on every field, 置信度 and 核对 columns in the medical items table, a 仅看待核对 checkbox, several explanatory small texts (ResultView medical disclaimer alert, ReviewEditor intro alert + save-button note, TableReview title/header/save notes, GenericSources intro, SourcePreview usage paragraphs, RegionOcrDialog panel note). In production `confidence` is always null / `confidence_method=unavailable` (ARCHITECTURE.md), so every confidence render was the literal string 未标定 — pure noise. The user asked for the tags, the confidence display and the save-button note to be deleted, plus a sweep for remaining redundant small text.

## Decision

- ResultView: field-line 待核对/核对项 tags and 置信度 span removed; medical summary-note alert removed (the medical guide step carries the same completeness caveat verbatim); items-table 置信度 and 核对 columns removed; 仅看待核对 checkbox and its BMI small text removed; summary-meta counts line and `linkedFindings` removed. Kept: number-length-hint red lines, 判定 tag with basis tooltip, stat cards, radio filter, search.
- ReviewEditor: medical intro small text, the how-to alert, and the save-button note (后端决定是否完成复核…) removed; bank-candidate small text now renders only for CONFLICT fields (the non-conflict variant was filler).
- TableReview: title note and save note removed (dynamic alerts above and the disabled-state of 保存表格修正 carry the state); header-suggestion note trimmed to suggestion + reviewed-state sentence; kept 点击单元格选择位置 — it is the antecedent for the whole merge/insert workflow, not decoration.
- GenericSources intro trimmed to counts + 重复字段分别保留 (kept deliberately: duplicate keys are legal, dropping the phrase invited users to delete legitimate pairs) + 字段可在下方修改.
- SourcePreview: both usage paragraphs deleted; toolbar span shortened to page count + click affordance + red-box dismiss hint.
- RegionOcrDialog: panel note deleted; `.region-panel-foot` justify-content changed to flex-end so the copy button stays right-aligned (the removed span was what spread the row). The crop-OCR quality tag (置信度 X% · 较低) stays — it scores the fresh snippet read, not a business field. The date-suggestion note stays (functional guard against treating format conversion as verification).
- TaskResultDrawer: the NEED_REVIEW red notice now appends a bounded summary of issues that cannot be auto-accepted (`collectIssues` filtered by `!canAcceptIssue`; field-level MISSING excluded because the editor's red border + （必填） labels are their carrier — item- and finding-level MISSING have no other carrier and are listed): the first 2 entries as `label：message` (the 项目： prefix is stripped to avoid double colons, trailing 。 trimmed before joining with ；), then 其余 scope names capped at 4 with a count beyond, so every affected row stays locatable via the search box. This is the replacement outlet for the deleted tag tooltips: codes like VALIDATION_FAILED / CONFLICT / MULTI_CANDIDATES / LOW_CONFIDENCE are not auto-accepted at save and would otherwise have no visible carrier anywhere between the field and the generic export-blocked hover.
- business.ts `confidenceText` deleted; workbench.ts `searchMedicalItems` lost its `reviewOnly` parameter; guide.ts lost the 置信度 sentence and the read-only step now says 位数提示 instead of 核对提示.

## Alternatives considered

- Keep 核对项 tooltips and only drop 待核对: rejected — the user wants the tags gone and confidence is constant noise, but the tooltip content is operational, hence the notice summary instead of keeping the UI.
- Put the issue list into the export-blocked tooltip instead of the notice: the notice is always visible on NEED_REVIEW tasks and matches the user's preferred one-red-line pattern; the hover stays generic and shared with batch export.
- Keep 仅看待核对 as a functional filter: rejected — with the 核对 column gone a review-only table cannot show why items matched; need_review data, the radio filters and the notice summary still route attention.

## Verification

Frontend typecheck, node tests (219 pass, including the rewritten `medicalFlag formatting` and two-argument `searchMedicalItems` tests) and production build pass; `npm run verify` passes with this note. Guide anchor-existence test untouched and green (no data-guide element was removed).

## Consequences

Issue messages surface in one bounded place (drawer notice) instead of per-element tags: 2 detailed entries, then up to 4 affected scope names, then a count. The review_issues payload and backend gating are unchanged, so restoring richer per-field indicators is a frontend-only change. Known backend-side gap surfaced by review: the id-card checksum rule reuses its neutral PASS/FAIL copy 仅校验号码校验位。 as the failure message, which reads as a rule description rather than a failure once it is the only carrier — a backend copy fix, not a frontend one. FRONTEND_FIELDS.md now states the frontend does not render confidence and describes the findings table per-row instead of aggregate counts; the help page no longer tells users to look for 待核对/核对项 hints or the 未标定 display.
