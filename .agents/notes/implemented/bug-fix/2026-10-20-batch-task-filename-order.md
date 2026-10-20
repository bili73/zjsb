# Agent Note: Display batch tasks in stable natural filename order

Status: implemented
Scope: frontend/src/presentation.ts, frontend/src/components/BatchBoard.vue, frontend/tests/presentation.test.ts, frontend/tests/batch-board-visuals.test.ts, FRONTEND_FIELDS.md, SPEC.md, CHANGELOG.md, frontend/public/help/index.html
Last-verified: 2026-10-20

## Problem

The task endpoint orders by creation time and UUID. All tasks in one upload share a creation timestamp, so their visible order is effectively UUID order. The board only filters the returned array. Operators cannot find files in the expected numeric filename order.

## Decision

Sort a copied task array for display using a zh-CN numeric filename comparator. Nonempty names precede missing/blank names. Collation ties use the exact trimmed name and then immutable task ID for deterministic ordering independent of response order, status, run and result revision. Keep original task references and the monitor's arrays unchanged.

Show a one-based sequence column derived from the complete sorted batch, then apply existing missing/disputed filters. Hidden rows leave gaps rather than renumbering visible tasks. Added/deleted files rebuild the sequence; the number is a display position, not a durable task identifier or queue rank. Recognition completion, review saves and reruns retain positions. Existing selection uses task_id, and full-batch export retains its current scope and ordering.

## Related-note audit

The [batch visuals](../../implemented/bug-fix/2026-10-20-batch-board-visuals.md) cover batch naming/calendar presentation, not task sorting; keep them intact. [Numbered pagination](../../implemented/feature/2026-10-16-numbered-list-pagination.md) covers pages of batches, audit and accounts, not numbering tasks inside a batch. [Fair document queues](../../implemented/architecture/2026-10-16-account-fair-document-queue.md) remain execution rules; this presentation order must not affect dispatch or reset its sequence. Scope/topic searches in proposed, implemented and rejected find no existing natural-filename task-order decision. No note is superseded or archived.

## Alternatives considered

- Preserve upload order: closely matches file selection, but existing rows cannot reliably recover same-timestamp original selection order and current enqueue_seq changes on rerun. The user approves filename ordering instead.
- Change the shared task endpoint order: gives every consumer the same order, but would also change export and package consumers beyond the requested board fix; encrypted filenames need application sorting anyway. Keep this change in the presentation layer.
- Sort unresolved or active tasks first: highlights work to do, but rows move as recognition or review changes. Keep existing explicit filters and stable filename positions.

## Verification

Three presentation regressions cover numeric filename ordering, deterministic ties and missing names, unchanged input/reference identity and ordering after refreshed statuses/runs/revisions. The mounted board regression checks actual setup wiring, full-batch numbers surviving filters, independent batches and sequences after append/delete. All289 frontend tests pass; typecheck and the isolated production build pass. Build output retains the existing large-chunk warning.

Three isolated real-Edge checks render the actual Vue board and Element Plus table, verify the sequence cells and natural order, preserve a hidden selected task through both filters, then replace statuses/run IDs/revisions without moving rows. The probe records zero browser errors and zero business API requests. Screenshot/report evidence remains under output/batch-task-order-20261020/attempt-pfjI8j; suite and build logs are under tmp/batch-task-order-*-20261020.log. These are synthetic UI checks, not recognition accuracy or GPU experiments. Concurrent upload-test edits remain untouched.

Read-only HTTP verification finds all16 current Windows static files byte-identical to the tested isolated build, including the new board and manual. Evidence is output/batch-task-order-20261020/http-static-verification.json. This task's verification does not publish files, restart services, replace login sessions or call any business API. Refreshing the existing Windows page loads the verified assets; Mac online stays untouched.

## Consequences

Chinese names use the browser's zh-CN collation. File insertion/deletion can change existing sequence numbers. The board order and exported workbook order remain separate; no API, schema, authorization, inference, historical result or Mac online mutation is included.
