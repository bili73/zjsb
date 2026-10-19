# Agent Note: Keep preview file I/O outside the writer lock and reuse unchanged diagnostic scans

Status: implemented
Scope: backend/ocr_app/preview.py, backend/ocr_app/diagnostic_service.py, tests, ARCHITECTURE.md, RUNTIME.md
Last-verified: 2026-10-19

## Problem

Authenticated Windows measurements reproduce diagnostic queries taking3.4–3.8s and preview responses taking0.13–1.12s. Preview access-history fsync holds the SQLite writer lock, taking up to1s in a request and serializing concurrent page loads. E: is a SATA mechanical disk; a separate12-write8KiB probe has44.596ms median versus1.433ms on the C: NVMe SSD. This measures storage latency, not all OCR slowdown. Diagnostic profiling traverses2238 source/archive files and validates119221 records, including intentional inter-file yielding; default queries repeat this work.

Latest medical runs complete without a task timeout but contain per-region time_limit results. One identical22-page input has the same52 geometry/input-hash attempts on October16 and19; model generation grows from62.889s to119.406s and queue time grows only5.297s. This rules out extra attempts as the sole explanation and leaves current GPU execution speed to be remeasured. Do not increase task budgets or claim the disk explains model generation time.

## Decision

Read the preview's version-bound artifact reference through an ordinary connection, then decrypt, encode and durably stage its encrypted access history outside the SQLite writer lock. Recheck account, owner, run and result revision immediately before atomically attaching the history. Remove staged history on rejection/rollback, preserve final response authorization and retain existing fsync and pixel output.

Reuse a single bounded in-memory collection of allowlisted ERROR/CRITICAL records for an unchanged file-signature set and coarse UTC day window. Check the actual retained raw/archive file set and signatures on every request. Changed/new/deleted files invalidate it. Cache only complete scans within8MiB, retain pagination/filtering and exact requested dates, and never use the cache to authorize archive deletion. Every HTTP response retains its administrator/session recheck.

## Related decisions

[Bounded writes](../../implemented/bug-fix/2026-10-16-bounded-http-writes.md) explicitly leaves preview history I/O as a follow-up; this applies its staging boundary to previews. [Diagnostic recovery](../../implemented/bug-fix/2026-10-15-queued-retention-and-diagnostic-recovery.md) retains corruption reporting and content validation for deletion; its matching-window repeated-parse policy is partially replaced by bounded signature-checked reuse here. [Read amplification](../../implemented/bug-fix/2026-10-19-batch-read-amplification.md) repairs batch polling independently. [API authorization](../../implemented/bug-fix/2026-10-13-api-authorization-boundaries.md) retains revocation/version fences. No active decision is completely superseded.

## Alternatives considered

- Moving runtime storage to the SSD would substantially reduce durable I/O, but changes deployment/data paths and requires a separate reviewed migration. Keep files and keys in place in this repair.
- Removing fsync or preview access records is fast but changes durability and access evidence. Preserve them and shorten only their lock scope.
- A time-based response cache is simpler but may show deleted/replaced logs. Revalidate file identity, size and timestamps on every reuse and disable caching for partial/oversized scans.

## Testing

The new preview contention and staging-conflict tests reproduce500/503 on the old implementation. New diagnostic regressions expose repeated scanning. After the change57 contention/authorization/diagnostic tests pass, followed by7 scan-cache and pure batch-stop tests including an additional exact-window case. Existing pixel-encode revocation checks still return no pixels, and stale staging leaves no orphan. The tests use synthetic isolated storage, not the real samples.

Only the idle Windows launcher is restarted. All15 table contents and3623 existing material/key hashes match immediately after restoration (output/windows-slow-path-restart-20261019-100722/recovery-check.json). Authenticated health confirms both models ready. Same-route local measurements are retained in output/windows-request-profile-20261019-095850 and output/windows-request-profile-20261019-100822: the diagnostic cold query remains3.342s, then unchanged queries take45.103/44.309ms versus repeated3.408/3.429/3.794s before. Five concurrent preview requests have maximum measured writer wait563→203ms. Disk latency varies between observations; these are not an isolated causal estimate of total UI speed. Mac remains unchanged.

Three new diagnostic tasks replay the same original21/22-page PDFs without rerunning or modifying old results. Stored process elapsed times change144.625→80.938s,159.390→119.922s and175.546→133.594s; HTTP upload-to-polled-terminal times are separately83.812/122.234/136.359s. All50/53/51 regions finish, none incomplete/pending; the last input previously has2 incomplete regions. Actual uploads take211.8–229.66ms, previews during OCR251.526–278.896ms and batch reads8.4–42.231ms. Original340 task rows/72 batches/367 runs and all3608 original material/key hashes remain unchanged; only new diagnostic tasks and expected auth/access/audit/cursor activity are added. The output/windows-slowdown-20261019-095850 report and CSV retain per-route/phase data without private values.

## Consequences

Cold/changed diagnostic scans still read the underlying history. Storage staging still costs I/O but no longer reserves the writer during file work. Metadata signatures use the same trust boundary as the existing archive index. These repairs do not certify medical completeness or CUDA batching correctness.

The model generation time itself recovers after restarting the local service, with unchanged checkpoint/input hashes and no physical-call increase for the two22-page reports. Historical GPU state was not captured and there is no controlled ablation of restart versus host load. Keep the recovery observation separate from the confirmed I/O/read fixes; a persistent GPU slowdown root cause and long-run stability remain unproven.
