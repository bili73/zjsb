# Agent Note: Reuse the Mac bank-name spelling rule on Windows

Status: implemented
Scope: backend/ocr_app/bank_photocopy.py, tests/test_bank_photocopy.py, FRONTEND_FIELDS.md, SPEC.md, RUNTIME.md
Last-verified: 2026-10-19

## Problem

The existing bank identity comparison treats 國/国 and 銀/银 as equivalent, but displays the first observed spelling. The user requests the Mac implementation and explicitly limits the change to bank names. origin/codex/mac-docker-deploy at c4d5a44 includes the portable fix from d33b012bc8dfd82b02522c05023ff1057e4c0ad5. That commit also contains Mac batch/readiness/deployment changes outside this request.

## Decision

The later user-requested [non-name bank conversion](../feature/2026-10-19-bank-non-name-simplification.md) partially supersedes the conversion scope and no-dependency choice below. It owns the broader bank/branch conversion; this note retains the selective Mac backport provenance, original verification and unchanged source/manual/history boundaries. The two-character-only and untouched-new-branch statements describe that earlier limited implementation.

The existing two-character bank mapping is the new automatically extracted bank_name value, independent of evidence order, in both BANK_CARD and BANK_CARD_COPY. Only this extraction behavior and its regressions are reused, adapted to the newly separate copy profile and four required defaults already in Windows. Actual different-bank conflicts and all sources remain. This is not a general Traditional-to-Simplified converter and adds no dependency or model.

Original OCR, source.raw_text, full text, PAN, holder_name, branch_name and all other document types remain unchanged. Historical recognized results and saved manual bank names remain byte-preserved; no read-time projection or migration normalizes them. New recognition or an explicit rerun uses the rule. Review/edit/export continue to honor saved values.

## Related-note audit

The [photocopy decision](../../implemented/feature/2026-10-14-bank-photocopy-handwriting.md) and [scan correction](../../implemented/bug-fix/2026-10-14-bank-scan-source-mapping.md) partly overlap: replace first-observed bank-name spelling only; preserve their raw evidence, source association and no-number-repair contracts. [Separate bank entries](../../implemented/feature/2026-10-19-bank-photocopy-entry.md) retains independent required profiles and unchanged historical types. [Portable backport policy](../../implemented/process/2026-10-16-portable-deployment-fixes-to-main.md) supports selective changes without importing Mac process/network configuration. Scope/topic searches find no existing Windows spelling owner or competing proposed/rejected normalization rule; nothing is wholly superseded or archived.

## Alternatives considered

- Keep the first observed spelling: closest to original rendering, but makes equivalent bank identities depend on source order. Preserve spelling in evidence instead.
- General Chinese conversion: covers names, branches and other documents, but the user explicitly chooses only the existing Mac bank-name scope. Do not install OpenCC or silently extend the mapping.
- Merge/cherry-pick all of d33b012: retains the upstream change together, but brings unrelated Mac batch and private-readiness wiring and can overwrite the new copy profile. Adapt only the bank hunk and tests.
- Normalize saved responses or Excel only: immediately makes old results look uniform, but changes manual values/history and leaves extraction conflicts order-dependent. Normalize only new extracted bank candidates.

## Verification

The red regression reproduces four failures before the change. All111 focused bank/copy/BIN/dispute/required/review/schema tests pass afterward. Both types produce 中国银行 from 中國銀行 regardless of order and preserve source.raw_text and generic.full_text; different banks retain conflicting candidates. Holder/branch names and PAN stay exact. Manual traditional bank names and historical recognized values remain traditional through projection/export. Default requirements remain one/four, with settings preserved. Logs are preserved in [Windows verification](../../../../output/bank-script-spelling-20261019-v1/REPORT.md). No model inference, fresh accuracy benchmark or Mac service operation is performed by these tests.

The idle Windows backend is backed up and restarted at19:07 to activate the rule; frontend assets are unchanged. The [activation record](../../../../output/windows-preview-restart-20261019-190739-50b453/verified.json) verifies15 unchanged tables,399 tasks,4 users,1 existing session,4109 referenced blob metadata entries,2 key hashes and18 HTTP static hashes; public health isok. No login or historical rerun is performed; protected model readiness is not queried. Mac online remains untouched.

## Consequences

Only 國 and 銀 are covered, matching the Mac rule exactly; this does not promise full Chinese conversion. A visible bank-name change is intentional for new results; it must not be described as OCR accuracy improvement or applied to frozen historical results. Existing Windows uncommitted work and running tasks must be preserved.
