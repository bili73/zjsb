# Agent Note: Report measured document work instead of fixed stage percentages

Status: implemented
Scope: backend/ocr_app/pipeline.py, backend/ocr_app/task_store.py, backend/ocr_app/api.py, tests/test_document_pipeline.py, tests/test_task_store.py, tests/test_document_contract.py, tests/test_business_api.py, tests/test_runtime_api.py, openapi.yaml, FRONTEND_FIELDS.md, SPEC.md, RUNTIME.md
Last-verified: 2026-10-10

## Problem

The user reports implausible recognition progress. The pipeline emits5/10/20/70/90 by stage; every page repeats OCR20 then EXTRACTING70, so a multi-page file goes backwards. Result publication sets100 even for failure or cancellation. An autoregressive model has no known expected output length, so elapsed time or a token ceiling cannot establish total task completion. The user approves a backend-only correction and assigns frontend changes to another agent.

## Decision

The pipeline publishes preparation checkpoints and one completed physical OCR-region checkpoint after retries, preserving the current worker callback signature, polling, run/revision fences and180-second deadline. It stays in OCR across pages, enters EXTRACTING once for actual field mapping, then VALIDATING for final result assembly. Reusing cached text completes the destination region once; attempts, native text blocks and successful semantic recognition are not interchangeable units.

Task.progress_detail contains stage, prepared_pages, total_pages, processed_regions, recognized_regions, incomplete_regions and total_regions. Counts derive from the current encrypted pages and upload page count, without a database migration. A private per-page preparation marker establishes that every source page finished region planning before total_regions becomes known. Partial/legacy plans return null totals rather than inventing a denominator; public projections remove the private marker. A processed region has final recognized/incomplete status after its retry policy ends, or retained incomplete work when execution stops. Processed does not mean correct or fully covered. API/application source is1.20.0 and SPEC isv1.26; public paths remain/api/v1.

The integer progress field remains for compatibility and is deprecated for UI task estimation. Its active values derive only from completed OCR-region units with a known plan (0 until known, capped99 before final publication). Successful machine publication sets100; failed/cancelled publication retains its previous measured value. No percentage estimates preparation, model-token generation, field mapping, remaining duration or human review. This backend change modifies no frontend source, dependency, asset, process lifecycle or production batch.

The later [detail loading and write-cost repair](2026-10-19-prioritized-detail-loading.md) skips a progress UPDATE only when stage, bounded percentage and full page snapshot equal the stored state, after run/cancel/stop guards. Changed page contents persist even with equal percentage. This does not redefine progress as a heartbeat or weaken durable actual checkpoints.

## Decision audit

The [durable task decision](../../implemented/feature/2026-09-30-durable-document-tasks.md) partially overlaps in progress publication, cancellation and old-run protection; those guards remain. The [bounded medical recognition decision](../../implemented/bug-fix/2026-10-08-bounded-medical-recognition.md) still owns retries, cache keys and deadlines; only the inter-page progress trigger in its revision-cache test changes. The [runtime lifecycle](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) already avoids invented startup percentages and retains model lifecycle ownership. [Independent model queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) remain unchanged. The [frontend decision](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) owns display and polling, which another agent will integrate. The Mac/auth proposals and rejected localization/medical-threshold decisions do not own progress semantics. Nothing is wholly absorbed or archived.

## Alternatives considered

- Replace the visual component: Element Plus already provides indeterminate progress and custom text with no new dependency. It cannot make fixed backend percentages truthful, and frontend implementation belongs to another agent.
- Estimate progress by time or tokens: produces continuous motion with little code, but inference length, fallback and model waiting have no reliable denominator. It repeats the user's complaint.
- Add streamed token events or a new persisted progress table: exposes finer live activity, but needs a new transport/storage lifecycle without measuring expected completion. Current region checkpoints and polling satisfy this scope.
- Infer the total from the currently saved pages alone: avoids a marker, but a cancelled/failed preparation pass can leave only part of the region plan. A private completion marker and the validated source page count prevent that ambiguity.

## Testing

- Multi-page stages never alternate EXTRACTING/OCR, and the compatibility percentage never falls within a run.
- Completed physical regions increment once after all needed attempts, including cache reuse and incomplete final outcomes; native text does not inflate OCR counts.
- Queue/preparation and partial/legacy page plans expose unknown totals honestly; pure-text PDFs perform no model call.
- Failure/cancellation never manufacture100; reruns reset the plan and stale/cancelled progress cannot publish.
- API/schema and integration documentation describe exactly the returned counts. Focused backend regressions pass without frontend changes or production sample/model calls.

The original37-test pipeline baseline passes. The [red pipeline](../../../../output/progress-pipeline-red.txt) and [red store](../../../../output/progress-store-red.txt) retain the reproduced failures. The [focused103-test run](../../../../output/progress-backend-focused-v2.txt) and [full549-test backend run](../../../../output/progress-backend-full-v1.txt) pass. A real worker/pipeline/encrypted-store/TestClient test polls during fake model retries: processed counts stay0/0/0/1 across four calls, then become2 at NEED_REVIEW; task, batch-task and paginated-task reads agree. The new progress DTO is validated against OpenAPI, with malformed count/stage/ETA rejection. Broader initial Task-schema validation surfaced the pre-existing error=null versus non-null Error schema mismatch; progress validation and existing envelope assertions do not claim full Task-schema conformance. Earlier failed integration output remains preserved.

The independently implemented [frontend progress/retention display](../feature/2026-10-10-progress-detail-and-retention-display.md) consumes this contract. Frontend files and UI verification are owned by the other agent. No actual recognition model, production input, frontend build or production service restart is part of this backend verification.

## Consequences

The subsequent [phase-aware frontend](2026-10-10-phase-aware-progress-display.md) consumes these counters with known-OCR-only measured bars, truthful active phase labels and retained stopped counts. The user later authorizes this agent to complete frontend integration; initial backend-only qualification above remains historical evidence.

Region units differ in duration. A unit ratio is not a remaining-time estimate. More region checkpoints add encrypted SQLite writes; no transaction spans inference. Legacy tasks lack preparation proof and retain unknown OCR totals. Frontend integration and service activation are separate from the qualified backend source; running1.19.0 requires a coordinated restart to expose the1.20.0 contract. No accuracy or throughput measurement is claimed.
