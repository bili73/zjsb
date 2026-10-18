# Agent Note: Verify account rotation through the restarted Windows service

Status: implemented
Scope: backend/ocr_app/task_store.py, backend/ocr_app/task_scheduler.py, backend/migrations, RUNTIME.md
Last-verified: 2026-10-16

## Problem

Isolated fairness tests do not establish that the current Windows service has activated the migration or that three real account sessions receive fair document turns with a real model. The user authorizes restart and a test using the three existing accounts, and clarifies these are test accounts rather than online production accounts.

## Decision

Activate the current main worktree with dual residency on the existing local port. Confirm no queued/active/expired material, preserve a consistent SQLite backup plus all material/key hashes and copied files, stop only the verified launcher tree, restart hidden and check migration, authorization and static hashes. Compare original columns and content before adding test batches. Source changes from previous authorized turns remain in the worktree; this is not a Git publication or a Mac deployment.

Use normal HTTP login with user-provided credentials, each held only in memory. Existing sessions may be replaced under the established single-session rule; do not alter passwords, insert sessions, change roles, or manufacture task ownership. Submit three distinct synthetic diploma PNGs per account through upload APIs, placing the first account's batch before the other two while its first document is active. Preserve real OCR attempts, task lifecycle, failures and measured timestamps. Test records are explicitly named and retained for the user. Check the owner ring at each observed claim using the actual persisted enqueue sequence, and verify operator cross-account reads remain denied and admin reads permitted.

The unequal4/3/2 extension uses the same accounts and live service with its own output, database baseline and unique synthetic images, preserving the first run. No restart, cursor reset, account alteration or application change is needed. Checks cover skipping an exhausted account, continuing the remaining owners in FIFO order, per-sample real inference and no unrelated task interference.

## Related decisions

[Account-fair document queues](../../implemented/architecture/2026-10-16-account-fair-document-queue.md) defines the tested behavior. [Independent model queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) remains one request per model; this is a live fairness probe, not a serial accuracy benchmark or true same-model concurrency test.

## Alternatives considered

- A cloned database and synthetic worker preserve the live service completely, but repeat existing unit evidence without proving activation and real inference through three sessions.
- Writing tasks as another account or inserting session rows avoids needing passwords, but bypasses the exact HTTP authorization and upload path under test. Use normal login with the provided test credentials.
- Reuse real employee documents for more realistic extraction, but recognition accuracy is not the target and identifying data is unnecessary. Distinct synthetic images exercise model requests and avoid per-batch deduplication.

## Testing

The Windows worktree is activated at main HEAD 2a358cd839f3492fa80c15bef807496cb182ba4d plus authorized uncommitted changes. Migration reaches0012. Normal authenticated health confirms dual_resident and both models ready before and after the probe. Three uploads under the existing HRSSC,29684,29685 identities produce nine distinct synthetic diplomas. Actual claims are A1 B1 C1 A2 B2 C2 A3 B3 C3, matching the persisted owner ring and within-account FIFO at every claim. Both later accounts receive their first turn before A2. Each sample has exactly one real, uncached GLM attempt ending with eos; all nine reach NEED_REVIEW with no failure or timeout. Same-lane processing intervals do not overlap. Per-task active processing is4.334–6.122 seconds; queue time is0.035–38.035 seconds. These are application lifecycle timings, not pure inference or accuracy measurements.

Operators can read their own test tasks but get404 for the other accounts' tested tasks/batch lists; the administrator reads all nine. All three probe sessions are logged out after observation. Restart and final post-test checks preserve the original62 batches,275 tasks,297 runs,3022 artifacts,2094 attempts,3023 audit rows,3 account records and settings. All3024 original material/key files and16 served static files retain their hashes. Source hashes match the activated worktree. Only the expected3 batches/9 tasks/9 runs/18 artifacts/9 attempts/9 audit rows are added; no unrelated task activity affects the rotation. Report passed is set only after these final per-sample and preservation checks.

Local evidence is retained in output/account-fairness-live-20261016-165043: REPORT.md, report.json, tasks.csv, restart-verified.json and final-verified.json. Restricted private/snapshot contains the consistent database/files backup. Probe code and verification helpers remain in ignored tmp; credentials enter only through stdin and are absent from scripts, reports and saved identities. An independent read-only review confirms the live result and identifies aggregate-attempt/no-interference/report-finalization weaknesses in the temporary probe; the separate final verifier closes all three checks against this run without repeating inference. The service remains running; no Git publication or Mac activation occurs.

The4/3/2 follow-up passes with actual order A1 B1 C1 A2 B2 C2 A3 B3 A4; eligible account counts are1,3,3,3,3,3,2,2,1. Exhausted owners are skipped without stalling or breaking within-account FIFO. All nine samples have one real uncached GLM attempt ending with eos and reach NEED_REVIEW; active processing takes4.377–5.750 seconds. First waits are0.040/4.749/9.331 seconds; full batch completion from enqueue is43.340/37.108/27.744 seconds for A/B/C. Both models remain ready and the final queue is empty. Independent read-only review confirms the observed exhaustion transitions. Final checks preserve all284 existing tasks,65 batches,3 account records/settings and3042 original material/key files, with only the expected3 batches/9 tasks and corresponding attempts/artifacts/audit added. No unrelated tasks interfere, all probe sessions are logged out,16 static files and source hashes match, and final verification marks the report passed. Evidence is in output/account-fairness-432-20261016-170647. Two preparation failures (missing timezone data, absent stdin) occurred before any login/upload and were fixed without replaying model tasks; filenames use explicitUTC+8.

## Consequences

The nine samples do not qualify general extraction accuracy, 50 simultaneous model requests, or Mac performance. Single-device login intentionally replaces previous sessions of these test accounts. Recognition may fail; failures remain evidence rather than being silently retried or marked as successful. Historical queued_at is unknown and does not become a fabricated measurement. Backups contain encrypted business material and protected key files and stay in ignored local output with restricted access.
