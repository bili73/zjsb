# Agent Note: Group help TOC so chapters 1-10 run consecutively

Status: implemented
Scope: frontend/public/help/index.html, frontend/tests/help-toc.test.ts
Last-verified: 2026-10-20

Closes visual-review finding #17, unblocked after the backend committed help/index.html in 42376fc; landed in the same batch as the export-tip hover note ([export tip](../feature/2026-10-20-export-tip-hover.md)).

## Problem

- Unnumbered special topics (拍照表格 photo-table, 通用表单 generic-form, retention, 操作审计 audit) sat between numbered chapters in the manual TOC, interrupting the 1–10 reading flow; retention was only an h3 inside chapter 9 and had no TOC line of its own.
- Body sections sat in a different order from the nav, so a trailing nav link scrolled the reader backward through the page.

## Decision

- Nav gains four group headers: 快速上手, 基础流程（第 1–6 节）, 进阶说明（第 7–10 节）, 专题：特定场景与维护. Numbered chapters stay 1–10 with zero renumbering; the four special topics move into the trailing group.
- Body sections are reordered so nav order exactly mirrors body order (the TOC is a mirror of the page; clicks only scroll forward within a group).
- Retention is promoted from an h3 inside admin to its own `<section id="retention">` with an h2 of the same title; its body (ol.steps + closing p) is byte-identical to the old block modulo the h3→h2 tag swap, so the deep-link anchor id is unchanged and the IntersectionObserver TOC highlight (`main section[id]`) now covers it.
- Meta line updated to 适用版本 v1.28.0 / 更新日期 2026年10月20日 (matches package.json 1.28.0).

## Alternatives considered

- Full renumbering to 1–14: rejected — large diff, breaks the existing 「详见第10节」 cross-refs, and contradicts the earlier decision to keep numbering stable.
- The reviewer's exact 3-group split (quick-start / 1–7 / 8–10 + topics): rejected — separating chapters 7 and 10 from 8 and 9 into different groups re-breaks the number flow the finding complains about.
- Group the nav without reordering the body: rejected — keeps the backward-jump problem while pretending to fix the structure.

## Verification

New frontend/tests/help-toc.test.ts parses the static HTML: numbered chapters run 1–10 with no gap, the four topics sit after chapter 10, nav link order equals body section order (17 each), at least four nav-group headers. Style-only aspects of the groups are asserted by none of this and stay human-accepted.

Move integrity was machine-checked against HEAD rather than eyeballed: after line-ending normalization the 14 untouched sections are byte-identical; admin equals its old content minus exactly its trailing retention block; the new retention section equals the h2 title plus the old body verbatim; no duplicate ids; figure captions still ascend 1–7; the only cross-ref target (第10节) still exists. 281/281 frontend tests, vue-tsc + vite build clean, root npm run verify green with this note.

The pre-commit 3-dimension adversarial review ran as inline machine verification this session — the Workflow/Agent orchestration tools were not available (two ToolSearch rounds found neither; recorded in the handoff doc). The checks above are the correctness/contract/test-quality dimensions substituted deterministically where possible.

## Consequences

- Chapters 1–10 read consecutively; special topics are discoverable in a labelled trailing group instead of interrupting the main flow.
- Retention has its own TOC line, own anchor (id unchanged), and participates in the scroll-spy highlight.
- Backend-authored manual copy (including the bank photocopy text from f0804c0) is untouched: the reorder moved nodes without editing their bytes.
