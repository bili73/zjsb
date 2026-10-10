# Agent Note: Durable local document tasks with bounded processing

Status: implemented
Scope: backend, tests, scripts/probe_business.py, scripts/probe_browser.cjs, access-key.cmd, requirements-app.lock.txt, SPEC.md, openapi.yaml, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, RUNTIME.md
Last-verified: 2026-10-10

## Problem

The first runtime slice loads models but cannot persist or process business tasks. The user approves the next stage: upload, durable processing, result queries and actionable errors, with review editing and business export deferred.

## Decision

Local SQLite uses synchronous SQLAlchemy and versioned Alembic migrations. Short transactions atomically claim tasks and protect run/revision publication, cancellation and reruns. The runtime worker remains the sole model coordinator. All pages and attempts share the Task's180-second active deadline. Restart never silently resumes tokens. Independent watchdog uses first-observed-run monotonic time plus181 seconds with0.5-second sampling. The [independent queues decision](../../implemented/architecture/2026-10-08-independent-model-queues.md) replaces whole-runtime timeout and long shutdown writer locks: a short transaction fences exact run/start identity, targeted termination confirms outside SQLite, and another short transaction recovers that run. Failed exit confirmation does not authorize recovery. The [temporary workbench](../../archived/feature/2026-10-08-temporary-recognition-workbench.md) adds local supplied-file comparison without backend reveal or review/export.

Sensitive source files, corrected pages, results and attempt bodies use AES-GCM under a key protected by current-user Windows DPAPI, separate from business tables. This is field/artifact encryption, not whole-SQLite encryption. Only authenticated API calls access business data; default responses mask sensitive numbers including raw text, without altering structural UUIDs or diagnostic IDs. Retention is seven days and only touches owned business artifacts; historical experiments remain untouched. Admission requires MEDICAL_REPORT, DIPLOMA or DEGREE_CERT; unsupported declared types and explicit card/security-code PDF text are rejected before storage. Image mislabeling is not a reliable security-code classifier: bank-card admission/redaction remains unimplemented, and this slice is not approved as full bank-card processing.

Reliable PDF text keeps its positions and bypasses OCR. The first pass persists corrected pages and collects all native text/table evidence; the second pass handles image/unreliable regions. Only page metadata and pending boxes are retained between passes, not a full-document image cache. This costs extra rendering but preserves later-page native evidence when an earlier OCR region times out. Small images are not blindly discarded as decoration. Certificates retain whole pages; long medical regions use conservative horizontal white-band cuts, not the experimental PP layout model. Source coverage remains unverified, confidence stays null, and successful extraction enters NEED_REVIEW. Read-only results include available partial results after FAILED; full review/export endpoints remain unavailable.

[Bounded medical recognition](../bug-fix/2026-10-08-bounded-medical-recognition.md) now limits medical generation to a soft 20 seconds and at most two original-image attempts, while certificates retain their three-attempt repair policy. Exact error-free EOS reuse stays inside one Task and binds current sources; neither cancellation/rerun nor a new Task inherits the cache. The shared deadline, hard supervision and conservative review state remain unchanged.

## Upload admission limits

The user approves up to100 files per upload,50 MiB per nonempty file and500 MiB of file payload per upload. The UI labels these binary limits as MB, consistently with the existing byte calculation. Shared backend constants bind streamed multipart admission and decoder validation; frontend constants bind the picker, messages and validation. Multipart framing receives separate bounded headroom scaled for100 filenames, while the aggregate file payload still cannot exceed500 MiB. Exactly-at-limit uploads are valid; excess count or size returns FILE_TOO_LARGE/413 before persistent task creation. Existing malformed-form400, format/page/pixel validation, authentication and task queues remain active.

Files remain in memory until decoding and encrypted persistence complete. Larger accepted uploads can increase peak memory and admission time; these limits do not qualify100-file OCR throughput, simultaneous500 MiB clients or Mac deployment. The existing upload client timeout and one-request batch transaction remain unchanged. No append/replace endpoint is introduced. The [frontend workbench](2026-10-08-frontend-rebuild-element-plus.md) uses the same limits without increasing per-model concurrency.

Only raising the browser limit gives immediate selection relief but leaves server rejection intact; update both sides and their API contract. Removing total-size limits accepts arbitrary scans but leaves unbounded memory use under the current in-memory parser; keep the approved500 MiB ceiling. Disk spooling would reduce request memory but introduces plaintext temporary files and lifecycle work outside this parameter change; retain memory-only admission and revisit it if deployment measurements require it.

The upload regression passes74 targeted backend tests and73 frontend tests, including a real500 MiB streamed multipart payload with100 long filenames, a50 MiB decoded/encrypted source,100 distinct queued tasks, byte/count excess413, invalid-last-file rejection and mid-write rollback. Typecheck and the production frontend build pass. Fixtures use isolated stores and no recognition model; this is admission qualification, not OCR throughput or a concurrent-client memory benchmark.

## Decision audit

The implemented [password sessions](2026-10-09-web-password-sessions.md) replace the browser key gate with named Cookie principals after local account provisioning; task persistence, versions and actor audit remain. The [hosted web-session proposal](../../proposed/architecture/2026-10-09-hosted-web-session-auth.md) still requires Mac container/native-inference, secret migration and proxy qualification; it does not replace DPAPI storage or Windows supervision yet.

The [runtime decision](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) partially overlaps in process ownership and is retained. The [layout experiment](../../implemented/testing/2026-09-29-automatic-layout-evaluation.md) supplies failure evidence, not a production coverage guarantee. [Local diagnostics](2026-09-30-local-diagnostics.md) owns error logging and shares task/run identifiers. The DDE tooling note is unrelated.

The [schema extraction diagnostic](../testing/2026-09-30-schema-extraction-benchmark.md) tests a separate candidate route without changing production extraction. Its improved recall and higher false-value rate do not supersede this task workflow.

## Alternatives considered

- In-memory background work is smaller but loses queued work and cannot protect restart/revision behavior.
- PostgreSQL and an external queue provide multi-host capability that this local low-volume application does not need.
- OCR every PDF region avoids text quality classification but wastes processing and discards reliable source text geometry.

## Testing

- Durable upload only returns 202 after file publication and task commit; failures leave no accessible partial task.
- Cancel/complete and old-run conflicts are tested, as are interrupted-run recovery and retention.
- Real PDF text and image inputs produce source-linked results; reliable text regions have no OCR calls.
- Model calls, repair and fallback share the Task deadline; independent queues serialize each model while permitting qualified cross-model overlap.
- Authenticated business routes, encrypted storage, masking and visible unsupported inputs are verified.
- Baseline runtime, CPU/browser checks and DDE gates are verified independently from serial actual-document outcomes; document failures remain visible in the acceptance records.

Regression checks include numeric UUID/error-ID masking, stale warnings on rerun, explicit abnormal versus unknown filtering, failed transactions, concurrent claims/cancel/publication, stale watchdog runs, failed process cleanup, DPAPI key continuity, schema compatibility, parser stdout isolation and multi-page native-first processing. Browser acceptance caught and corrected the native fetch receiver binding bug. The first full-report probe timed out after six pages; the two-pass regression proves later native evidence survives an early OCR timeout. Integration records keep failed attempts and unlabelled accuracy as null; field population is not accuracy.

The [acceptance report](../../../../output/phase2-acceptance-20260930/REPORT.md) records 115 backend CPU tests, 21 frontend tests and separate browser/model evidence. The final real report probe retains all 21 pages and 38 native-table items but still times out; its overall document status is partial, not passed. Native source region IDs also resolve to registered page regions, including timeout results. Shutdown timeout cleanup does not wait recursively on its own confirmation event.

## Consequences

The [OTSL adapter](../bug-fix/2026-09-30-paddle-otsl-table-decoding.md) adds the missing Paddle table-format conversion before medical column mapping. Native PDF table recovery and evidence coverage remain separate; supported format decoding does not imply complete clinical fields.

Native decoders, table geometry and medical layouts can fail. Repeated logos/signatures consume OCR budget; the 21-page actual report does not yet have complete automatic recognition acceptance. Medical stats remain null without complete coverage proof, even when individual source-backed rows are available. Hard worker termination retains encrypted page/attempt artifacts but cannot guarantee a structured partial result if publication never finishes. Low-volume transactions and a local encrypted store simplify deployment, but account migration/backup recovery and 50-file throughput are not qualified. Full review editing, business export, all document families, CPU-only inference and a 16 GB HR machine remain unverified or unimplemented.

## Related verification

The [isolated current-pipeline acceptance](../testing/2026-10-08-current-pipeline-acceptance.md) verifies the repaired real API path with frozen references and a separate encrypted store. Its v1 single-resident timeout remains historical evidence. The [bounded-recognition v2 run](../bug-fix/2026-10-08-bounded-medical-recognition.md) finishes all three PDFs without Task timeout on current Windows dual residency, with 72/72 blood results and 6/6/2 scoped findings. This processing completion does not prove whole-report semantics or qualify target production hardware; medical stats remain null.

The [HDR JPEG admission repair](../bug-fix/2026-10-08-hdr-jpeg-upload-admission.md) shares upload/worker image validation, preserves encrypted original bytes and replaces generic unsupported-image errors with actionable safe format rejection. Its actual-route browser acceptance supplements the earlier synthetic mock API checks; admission success is separate from OCR accuracy.

The former frontend portion is retired by the [frontend retirement](../../implemented/simplification/2026-10-08-retire-temporary-frontend.md); current Scope covers surviving code. Old UI checks describe historical acceptance.

The [HR field profile](2026-10-08-hr-document-field-profile.md) narrows only public diploma fields and masks recognized mobile copies without rewriting encrypted history, run/revision or audit records.


## Current contract extension

[Document profiles](2026-10-08-card-and-document-profiles.md) extend type admission; [human review/export](2026-10-08-human-review-and-xlsx-export.md) extend the read-only workflow; [internal full values](2026-10-08-internal-unmasking-and-review-friction.md) replace masked business outputs under exact user authorization. Persistence, encryption, versions and original run history remain active.


## Batch presentation extension

On2026-10-08 the user requests UTC+8 display, newest-created batch first and document-type batch names. Keep canonical UTC timestamps and persisted original history unchanged; the frontend explicitly formats aware timestamps in Asia/Shanghai across batch, engine and diagnostic displays. Sort known creation timestamps descending rather than reversing API order through repeated unshift; refresh, pagination and optimistic insertion must preserve that order. Invalid/missing times do not invent a time. New encrypted batch names use the canonical document label. Historical response names are derived from actual task document types without rewriting name_enc; mixed known types use a combined readable label, an empty/unknown batch stays explicitly unspecified. UI creation-time labels must not say updated time while showing created_at.

Overwriting every stored timestamp with local wall time seems direct, but can change ordering/audit semantics and creates migration work without improving display; use a fixed display timezone. Renaming only newly uploaded batches avoids touching old records, but leaves historical batches hard to find; project document-type names in responses too. This extends the [current frontend](2026-10-08-frontend-rebuild-element-plus.md) display contract while retaining batch IDs, task lifecycle, encryption and immutable run history.


## Batch presentation verification

Failure-first CPU tests reproduce the old stored upload label and reversed first list. New and historical type-name tests preserve encrypted name history and UTC timestamps; empty/mixed types are explicit.54 integrated frontend tests/typecheck/build and the52-batch targeted synthetic browser check pass. Single-task ordering, upload-ID order and worker claim FIFO are unchanged. This is UI/API presentation verification, not OCR or hardware timing.


## Current refinement

The [calendar browser](2026-10-09-batch-calendar-browser.md) adds read-only creation-day ranges before pagination without changing identities or UTC storage. The [bank input/recovery refinement](2026-10-09-bank-auto-recognition.md) queues full photos without synchronous OCR and creates a new task for a recovered single crop, retaining original tasks.
