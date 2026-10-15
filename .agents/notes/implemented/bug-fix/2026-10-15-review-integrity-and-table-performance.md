# Agent Note: Preserve unresolved selections and applicant ownership during review

Status: implemented
Scope: backend/ocr_app/export_disputes.py, backend/ocr_app/review.py, backend/ocr_app/interview_form.py, backend/ocr_app/exporting.py, backend/ocr_app/task_store.py, frontend/src/table-review.ts, frontend/src/components/TableReview.vue, tests/test_export_disputes.py, tests/test_interview_form.py, tests/test_document_privacy.py, frontend/tests/table-review.test.ts, frontend/tests/table-review-component.test.ts, SPEC.md, FRONTEND_FIELDS.md, openapi.yaml
Last-verified: 2026-10-15

## Problem

Real isolated HTTP probes reproduce two data-integrity failures. A save acknowledges a medical finding whose result association is still unselected. An emergency-contact table preceded by an external heading supplies the applicant's missing mobile number. Both allow incorrect Excel exports. Separately, visible table cells repeatedly scan every merge; bank task summaries acquire fabricated empty fields, and result detail calculates export disputes twice.

## Decision

Keep ordinary save as the authorized acknowledgment interaction. Confirm only targets with a selected value: medical findings require a live result association and nonempty result, and medical items require a nonempty result with selected or explicitly absent diagnosis when diagnosis sources exist. Previously stored acknowledgments must not suppress now-unconfirmable disputes. Metadata and same-value patches preserve unresolved selection conflicts. Explicit corrections and optional absences keep their existing review path; missing required fields remain blocking.

Determine applicant table ownership from applicant labels and surrounding section boundaries, including headings outside tables. A generic mobile label alone does not identify an applicant table on a multi-table page. Preserve isolated incomplete basic regions, applicant evidence and whole-region OCR fallback. Excluded contact/family/work sections never supply applicant fields.

Build a component-local computed merge index and query it once per visible cell. Rebuild on merge changes, retain it during text edits, and preserve existing grid, pagination, keyboard and export contracts. Project bank profiles only for actual result shapes. Calculate blockers and disputes together per result detail request; retain the existing blockers-only wrapper for other callers. Do not cache results across requests.

## Related-note audit

- [Save-as-review](../../implemented/feature/2026-10-14-save-confirms-export-disputes.md) and [dispute gate](../../implemented/feature/2026-10-14-disputed-results-export-gate.md) retain their interaction, evidence, revision and ownership rules. This repairs their unselected-value invariant, including historical acknowledgments.
- [Interview extraction](../../implemented/feature/2026-10-14-interview-registration-and-shared-upright.md) retains its five-field profile and bounded model fallback; section ownership enforces its existing contact-exclusion rule.
- [Photo-table conversion](../../implemented/feature/2026-10-13-photo-table-to-excel-replan.md) retains its grid semantics and limits. [Bank profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) retain full legacy result projection; task summaries are not results.
- Scoped deployment/auth proposals and rejected model/localization choices do not govern this repair. No decision is wholly superseded or archived.

## Alternatives considered

- Acknowledge all non-scalar targets: simplest shared rule, but accepts associations with no selected value. Rejecting every medical conflict is conservative, but prevents legitimate source exceptions after a value is chosen.
- Match phone labels globally: maximizes recall with little code, but attributes another person's number to the applicant. Conservative section ownership may leave ambiguous fields missing for manual review.
- Keep merge scans: no derived index, but costs visible cells times total merges on every render. Full virtualization or a global cache adds unrelated lifecycle/invalidation complexity; a bounded local index suffices.
- Cache export analysis across requests: avoids more computation, but must track revisions, required-field policy and filtering. One analysis per detail request is sufficient and has no stale-cache risk.

## Consequences

Unselected medical conflicts remain blocking even with historical acknowledgments. Selected exceptions retain the one-save workflow. Conservative applicant ownership can leave uncertain phones missing for manual review; previously saved phone values are not inferred or rewritten. The merge index uses memory bounded by the existing 10000-cell grid limit and is invalidated by structural edits. Per-request export analysis avoids cache invalidation across result and policy revisions. No database migration or OCR accuracy benchmark is required; local activation preserves existing accounts and records as verified below.

## Testing

Both P1 regressions fail before repair; additional metadata/no-op edit regressions reproduce selection erasure. The 21 dispute and 13 interview tests pass, including real isolated HTTP save/export boundaries, legacy acknowledgments, explicit absence, selected medical results and manually corrected applicant phones. Original evidence remains unchanged. Bank task API responses are deterministic and field-free while existing legacy projection tests retain current result profiles. A spy verifies one dispute analysis per detail request.

The 197 frontend tests pass, including the actual TableReview component's index reuse, one lookup per visible cell, page-spanning merges, structural invalidation, saved draft contents and revision fences. Typecheck and isolated production build pass. The synthetic 1000-row, 10-column, 5000-merge fixture measures three calculation runs: median repeated-scan time1095.69ms, index construction plus queries6.77ms, cached queries0.08ms. This excludes browser DOM and OCR inference, and does not establish end-to-end latency. [Measurement](../../../../tmp/fixes-20261015/table-performance.json) preserves every run; full-suite logs and build artifacts remain in the same directory.

The full backend suite passes806 tests in275.679 seconds. The full frontend suite passes197 tests. DDE tree/link/metadata/archive verification passes; the derived index is regenerated and checked for consistency. Pre-repair failures and final suite logs remain under [verification evidence](../../../../tmp/fixes-20261015/backend-tests.log). Source publication includes the deployed application, tests and documentation, including the previously uncommitted interview and dispute-gate prerequisites. Local tool preferences, runtime data, model weights and build outputs remain outside this publication.

## Local activation

The Windows loopback service at127.0.0.1:8765 runs the verified repair code and all13 candidate static files. Before stopping the owned launcher tree, queued/active/expired task counts are zero and a consistent SQLite, encrypted material, key and static-resource snapshot is retained. The replacement launcher uses dual_resident; supervised GLM and Paddle loading and warmup both succeed. Public health is ok, and anonymous business/full-health requests return401.

All13 database tables match the pre-restart snapshot row for row, preserving291 tasks and2 accounts;2979 material/key file hashes match. Served static bytes and backend source hashes match the activation manifest. [Activation verification](../../../../output/review-repairs-20261015-activation/activation/verified.json) and the adjacent service-snapshot retain the evidence and rollback material. The service version remains1.26.0; no version bump or Mac deployment is requested.
