# Agent Note: Explicit person material packages with versioned append

Status: implemented
Scope: backend/migrations, backend/ocr_app/task_store.py, backend/ocr_app/routes.py, frontend/src, frontend/tests, tests, SPEC.md, openapi.yaml, IMPLEMENTATION_PLAN.md, FRONTEND_FIELDS.md, RUNTIME.md, README.md, ARCHITECTURE.md, frontend/public/help/index.html
Last-verified: 2026-10-13

## Problem

The user approves implementing person packages, mixed-material append and identity-card front/back pairing in this iteration. Existing type batches can contain multiple people, so assigning a person from OCR or converting legacy batches would invent attribution.

## Decision

The later [administrator file retention decision](2026-10-15-admin-file-retention.md) replaces this note's fixed seven-day duration and client-side expiry fallback. Administrators select 7/15/30 days or never for existing and future files after a confirmation dialog; original upload clocks, ownership and history cleanup boundaries remain. Server nullable deadlines are authoritative. The seven-day descriptions below document the original default.

Reuse a batch as an explicitly named person package when its first upload supplies a manually entered person name. Store the person label encrypted and append revision as additive batch columns. Legacy batches remain unassigned and retain their tasks and ownership. The initial implementation specifies one supported material type per request; the later approved [single-submit workflow](2026-10-12-person-package-single-submit.md) replaces that interaction with editable content classification and atomic ordered mixed uploads. Version-checked uploads can add materials only to a named package. The UI confirms that selected files belong to that named person. Never merge by name or inferred OCR identity.

Append prevalidates all files, rechecks live authorization and ownership in a short transaction, and checks the expected package revision. Reuse an identical file already in the same package only for the same type; reject a conflicting type assignment. New tasks have independent runs and seven-day expiry; existing tasks/results/expiry remain unchanged. Batch.expires_at projects the earliest remaining task expiry; Task.expires_at exposes its own expiry. Failed transactions remove only their own newly stored artifacts. Concurrent stale appends return an explicit version conflict, never overwrite a package. Upload limits remain 100 files/50MB each/500MB per request.

Pairing describes material presence, not recognized identity equality or authenticity. A named package with only the back receives a missing-front warning immediately, including while tasks are queued or failed. The later approved [optional-back decision](2026-10-12-optional-id-card-back.md) retains the missing_back presence state but replaces the front-only warning with optional-material information; front recognition and export are independent. Both sides are marked present but still require original comparison. No sides means not supplied, never paired. Legacy batches do not receive person-pair claims. Warnings do not change required-field export eligibility. Existing batch ownership, owner attribution, deletion and expiry continue to apply.

## Decision audit

The [process/package repairs](../../implemented/bug-fix/2026-10-13-region-ocr-and-package-repairs.md) preserve the 100-file per-request upload limit while allowing deletion snapshots for packages whose cumulative task count exceeds100. Complete membership/version checks and atomic deletion remain required.

The [review repairs](../../implemented/bug-fix/2026-10-12-review-repairs.md) deliberately left append/pairing unimplemented; this later user approval implements that subset without altering history recovery or clinical decisions. [Batch ownership](../../implemented/feature/2026-10-10-account-owned-batches.md), [durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md), [deletion](../../implemented/feature/2026-10-10-delete-recognized-batches.md) and [card profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) partially overlap and retain their boundaries. Hosted/Mac plans are unrelated. Nothing is fully absorbed or archived.

## Alternatives considered

- Add a separate person registry and cross-batch association: supports wider dossier workflows, but adds global identity lifecycle and access semantics beyond this iteration. A batch already provides the needed ownership and export boundary.
- Match by recognized names: reduces operator input, but identical names, OCR errors and the unnamed identity-card back create unsafe associations.
- Allow mixed append into any legacy batch: convenient, but existing batches can contain multiple people and cannot support reliable missing-side claims.
- Automatically reclassify appended files: fewer clicks, but the current type-specific recognition contract is explicit. One type per append avoids silently routing another material incorrectly.

## Verification

All615 backend tests and115 frontend tests pass, including13 isolated package tests for additive0005-to0006 migration, encrypted attribution, owner/admin/viewer boundaries, revocation during admission, a real two-thread stale-version race, atomic bad-file/storage failure, duplicate reuse/type conflict, unchanged manual results/runs/expiry and expiry-driven pairing recomputation. Frontend multipart, session fencing and strict metadata decoding pass; typecheck/build pass.

An isolated real browser creates a synthetic named package, confirms attribution, shows the front-only presence state (the earlier warning is replaced by optional-back information in the follow-up decision), appends the back, retains both task rows and switches to both-present with manual-comparison guidance. Existing rerun confirmation and cancellation preserve the completed synthetic result. Screenshots and logs are retained in output/pm-remediation-20261012-v1/; this workflow uses no recognition model and does not mutate production data. The web manual, contracts and implementation descriptions agree with the implemented scope.

The source classification directory contains15 distinct files across five families: diploma3, degree2, Xuexin3, bank3, medical4. Read-only before/after hashes match. Inventory and unit checks are not accuracy measurements; dedicated identity-card, passport, household-register and business-license real-sample acceptance remains incomplete.

## Consequences

The [upload-before-naming decision](2026-10-12-person-package-name-suggestions-and-export.md) partially replaces mandatory upfront/immutable person labels with a separate package flag and encrypted, versioned human confirmation/correction. Pending packages support append and pairing. Ownership, independent expiry, no automatic merge and atomic revision rules remain active.

The user later selects and authorizes the implemented [single-submit person workflow](2026-10-12-person-package-single-submit.md). It replaces the earlier one-type-per-request recommendation with CPU content classification and atomic mixed creation/append; this ownership, encrypted attribution, revision and preservation design remains active. The historical alternative below explains why classification was initially deferred; the later note records the new requirement and bounded CPU tradeoff.

Manual attribution can still be incorrect; the UI requires original comparison. Legacy batches and same-name people remain independent. Retention is per material: append never extends original expiry, the batch displays its current earliest material expiry, and clearing an expired side recomputes pairing. Presence is deliberately distinct from recognized identity and export readiness. A lost upload response has an unknown outcome; refresh before retry rather than replay automatically. No global person registry, source-task relocation or automated authenticity decision is introduced.

## Local activation

The idle Windows service is updated to application1.22.0/schema0006. Verified SQLite backups precede each owned process-tree restart; the second activation includes the optional-back follow-up. All original columns/rows match before/after fingerprints, except the explicitly additive schema migration in the first activation. The246 existing tasks,2 accounts and2,411 original encrypted/key files remain unchanged. Both GLM and Paddle complete serial loading/warmup and report dual_resident/ready with an empty queue. Served frontend assets match the qualified build; anonymous batch/append requests return401. Evidence is retained in output/pm-packages-activation-20261012-v1/ and output/pm-packages-activation-20261012-v2/. No production recognition or account changes are performed for verification.
