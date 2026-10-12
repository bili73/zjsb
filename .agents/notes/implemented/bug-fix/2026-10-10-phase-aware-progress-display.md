# Agent Note: Show measured work only in the phase it describes

Status: implemented
Scope: frontend/src/business.ts, frontend/src/presentation.ts, frontend/src/components/BatchBoard.vue, frontend/tests/business.test.ts, frontend/tests/presentation.test.ts, frontend/tests/monitor.test.ts, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-10

## Problem

The user asks this agent to take over frontend integration of the approved backend progress contract. Another agent has already integrated region counts and a retention label. Its progress bar still displays region percentages during preparation, extraction and validation, and uses a fixed40-width indeterminate bar when counts are unknown. Terminal rows hide retained counts. The parser accepts incomplete detail objects and contradictory counts, allowing missing values to become invented zeroes.

## Decision

Element Plus and the existing polling remain. A measured bar appears only during OCR with a known positive region total, accompanied by literal processed/total counts. Queue has no activity spinner; other active phases use the existing Loading icon and explicit stage text, not a fixed-width percentage bar. Preparation displays saved/source page counts. Extraction/validation remain visibly active even after all OCR regions finish. Stopped states retain measured counts and incomplete warnings without a success bar; NEED_REVIEW explicitly distinguishes machine completion from human review.

One pure presentation function in presentation.ts makes stage/count decisions testable and replaces the scattered component functions. The optional outer progress_detail remains backward compatible, while a present DTO must contain its required fields, valid matching stage and consistent nonnegative counts; no default-zero or clamping repairs malformed responses. Unknown totals stay null, including legacy actual_source_page_count=null. Existing unrelated UI changes, including retention, are preserved. Qualification uses unit/monitor tests, typecheck/build and an isolated browser fixture without model or production task writes. Local activation only proceeds after idle-state verification and backup; a busy production service is not interrupted.

## Decision audit

This partially refines the [other agent's display decision](../../implemented/feature/2026-10-10-progress-detail-and-retention-display.md): actual counters and retention stay, while percentage display becomes OCR-phase-only and DTO validation matches the implemented [backend contract](../../implemented/bug-fix/2026-10-10-measured-task-progress.md). The [frontend rebuild](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) still owns components and serialized polling. Nothing is wholly replaced or archived; proposed auth and rejected localization/medical-threshold notes are unrelated.

## Alternatives considered

- Keep region percentages in every active phase: preserves continuous numeric feedback and requires less UI code, but100% OCR can look like a completed task while field mapping is running.
- Use a fixed-width indeterminate ElProgress: already integrated and clearly animates; its percentage-shaped track and accessible numeric value still imply a number with no denominator. A spinner and stage text express waiting directly.
- Accept partial count DTOs and default missing values to zero: tolerates experimental servers, but contradicts the now implemented required schema and can display false work counts. Missing outer DTO gets stage-only fallback; malformed present DTO fails the existing parse guard.

## Testing

- Queue, preparation, unknown OCR, known OCR, mapping, validation and all stopped states present correct activity/counts with no time-based increments or legacy percentage fallback.
- Incomplete count is visible; OCR work100% never makes mapping/validation/review look complete.
- Same-run/same-revision polling updates counts, and rerun clears previous progress.
- Frontend tests, typecheck/build, browser qualification and DDE verification pass. Original inputs, accounts, prior verification outputs and unrelated UI features are preserved.

The inherited frontend baseline has94 passing tests. The [parser reproduction](../../../../output/progress-phase-parser-red.txt) records legacy null-page metadata rejection. [All99 frontend tests](../../../../output/progress-phase-frontend-tests-v1.txt) and [typecheck/build](../../../../output/progress-phase-build-v1.txt) pass. New tests cover all phases, unknown/zero totals, stopped incomplete work, no premature rounded100%, same-run/same-revision updates and rerun clearing.

The [thirteen-case real HTTP/browser run](../../../../output/progress-phase/browser-1b0f67d740f849849c5a0a1378726d75/report.json) verifies DOM/ARIA, incomplete warning, no time-based advancement, legacy DTO absence, live OCR-to-mapping-to-failure and real authenticated rerun. The fixture uses twelve synthetic tasks, controlled work counts, its own account/encrypted store and no model; screenshot inspection confirms readable rows. Browser/server resources close and production writes/model calls are zero. The preceding failed fixture output remains preserved: its synthetic control route followed the static mount; only fixture routing order changed.

## Consequences

The [local activation](../../../../output/progress-phase/activation.json) serves the qualified entry/assets on application1.20.0 with both models ready. Two idle checks precede an integrity-checked backup and replacement of the verified owned launcher tree. All151 tasks, one account, every database table, encrypted artifact and secret fingerprint match before/after. Old frontend assets and entry/help backups remain. Original samples are untouched; loading models for activation does not add an accuracy/speed benchmark.

Counts move only at backend checkpoints. A known regional ratio does not estimate duration or accuracy; the UI explicitly labels work units. Strict DTO validation treats malformed servers as a visible read failure, while older servers omitting the DTO remain supported. Model reload during an idle local release is startup work, not an inference-speed benchmark.
