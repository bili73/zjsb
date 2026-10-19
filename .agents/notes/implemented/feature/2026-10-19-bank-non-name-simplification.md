# Agent Note: Simplify newly recognized bank text while preserving personal names

Status: implemented
Scope: backend/ocr_app, requirements-app.lock.txt, tests/test_bank_photocopy.py, tests/test_bank_simplification.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, CHANGELOG.md
Last-verified: 2026-10-19

## Problem

The user expands the preceding Mac-compatible two-character bank-name rule: both bank entries should simplify recognized Traditional Chinese text, except personal names. 國/銀 alone misses agricultural banks, branch names and labelled card metadata. A response/export-wide converter would also rewrite saved human choices, history and source evidence.

## Decision

The application environment uses pinned official OpenCC1.4.2 and its offline t2s dictionary. Only new BANK_CARD/BANK_CARD_COPY recognition candidates for bank_name, branch_name, card_scheme, card_type and valid_thru are simplified before deduplication/validation. Holder names, PAN/BIN digits and all other material types are excluded. Corresponding Traditional Chinese bank labels are recognized without changing their source text. Script-equivalent candidates merge; genuinely different banks/branches remain unresolved conflicts. Local normalized context copies support number/boilerplate boundaries; values and evidence for personal names and numbers never come from those copies.

Never normalize saved/public results, manual review input, source/raw text, generic full text or Excel at read time. Exports use saved field values. Historical runs and manual confirmations keep their values and fingerprints; only new recognition or an explicitly requested rerun uses this rule. No schema migration, new model, model-environment dependency or Mac operation is needed. The application lock pins the required converter; missing/broken installation is an installation error, not a silent partial-conversion fallback.

## Related-note audit

The [Mac spelling backport](../../implemented/bug-fix/2026-10-19-stable-bank-script-spelling.md) partly overlaps: its limited conversion scope is expanded by this new user instruction, while selective backport provenance and untouched original/manual/history boundaries remain useful. The [photocopy source correction](../../implemented/bug-fix/2026-10-14-bank-scan-source-mapping.md), [photocopy evidence contract](../../implemented/feature/2026-10-14-bank-photocopy-handwriting.md) and [separate bank entries](../../implemented/feature/2026-10-19-bank-photocopy-entry.md) remain active. Scope and topic searches find no competing proposed/rejected conversion owner. No note is wholly superseded or archived.

## Alternatives considered

- Extend the two-character table: zero new dependency and exact control, but cannot cover the requested bank/branch text reliably without maintaining a second conversion dictionary.
- Convert complete OCR text before parsing: simplest broad coverage, but destroys source spelling and can change personal names. Convert only field candidates and a local copy used to match bank context.
- Convert public responses or Excel: makes historical display uniform immediately, but rewrites human values/history without re-recognition and leaves candidate conflicts inconsistent. Keep saved values authoritative.
- Use a language model or regional vocabulary conversion: can rewrite difficult wording, but adds inference cost or changes phrasing beyond script conversion. Use official OpenCC t2s, not tw2sp.

## Verification

The first red run reproduces10 failing subcases across5 tests; an additional regression reproduces two failures for traditional explicit PAN labels resembling valid Chinese IDs. After conversion and context matching, all117 focused bank/copy/BIN/review/dispute/required-field/contract tests pass. Both types cover full bank/branch conversion, Traditional Chinese HTML labels, multiline branches, unchanged personal names/PAN/raw text, equivalent versus real conflicts, saved manual/history values through projection/save/Excel and unchanged ID-card values. Dependency installation is Windows app-only; pip check passes. Evidence is retained in [local verification](../../../../output/bank-non-name-simplification-20261019-v1/REPORT.md). No model inference or accuracy benchmark is performed.

Another114 shared field/profile/pipeline/privacy/certificate tests pass, for231 related regressions in total. The Windows idle backend is backed up and restarted at19:19; the [activation record](../../../../output/windows-preview-restart-20261019-191936-ae5340/verified.json) verifies15 unchanged tables,399 tasks,4 accounts,1 session,4109 referenced blob metadata entries,2 keys and18 HTTP static hashes. Public health and SQLite quick_check pass. No frontend publication, historical rerun, session replacement or protected model-readiness probe occurs. Mac online is untouched.

## Consequences

New automatic fields display consistent Simplified Chinese without adding a recognition model or per-document network call. Personal names remain source spelling and raw text can still contain Traditional Chinese. Dictionary conversion does not correct OCR substitutions or prove bank identity; genuine ambiguity remains reviewable. The added pinned binary dependency has app-Python3.12 WindowsAMD64, macOSARM64 and LinuxARM64 wheels in PyPI metadata, but only Windows installation is tested here. A later deployment must install the updated app lock; missing converter installation fails rather than silently claiming full conversion. Historical/manual fields are intentionally not batch-rewritten. This is not an OCR accuracy or Mac deployment qualification.
