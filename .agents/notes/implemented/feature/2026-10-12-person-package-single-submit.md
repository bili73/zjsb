# Agent Note: Upload one person's mixed materials in one submission

Status: implemented
Scope: frontend/src/components/UploadPanel.vue, frontend/src/components/BatchBoard.vue, frontend/src/components/DiagnosticsPanel.vue, frontend/src/App.vue, frontend/src/api.ts, frontend/src/business.ts, frontend/src/monitor.ts, frontend/src/packageUpload.ts, frontend/src/diagnostics.ts, frontend/tests, backend/ocr_app/routes.py, backend/ocr_app/business.py, backend/ocr_app/task_store.py, backend/ocr_app/document_classification.py, requirements-app.lock.txt, tests, openapi.yaml, SPEC.md, FRONTEND_FIELDS.md, RUNTIME.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, README.md, frontend/public/help/index.html
Last-verified: 2026-10-12

## Problem

The user finds person packages inconvenient and selects one person per package, choosing all material types together and submitting once. The current screen requires a type first, clears selected files on a type switch, confirms attribution per request and returns to the general batch list after submission. Additional types require reopening a package and repeating the type/upload/confirmation sequence. The current backend accepts only one doc_type_hint per multipart request, so a frontend button alone cannot make mixed submission atomic.

## Decision

Offer explicit 按人员整理 and 按类型批量 modes; the chosen primary workflow is the person mode, while preserving existing type-batch uploads. A person enters the name once, chooses mixed files together, reviews a list containing thumbnail/file name and an editable document type, then clicks 整包提交. Each file represents one material type, including multi-page PDFs of that type. A PDF containing several different document families is not automatically split in this iteration.

The user approved the workflow and requested automatic classification. An authenticated memory-only classification endpoint examines the first two PDF pages (native text first) or a bounded image with bundled RapidOCR 3.10.0 ONNX assets on CPU, two threads and one classification in flight. No GLM/Paddle requests, production tasks, extracted text response or plaintext temporary files are added. Strong content headers take precedence over filename hints; conflicting types and unsupported Xuexin report kinds remain 待选择. A filename fallback is explicitly labeled and all suggestions stay editable. Classification failure permits manual selection. 身份证 alone does not establish the side, and 学信网 alone does not establish the supported report kind. The browser classifies files serially, cancels removed/unmounted work and never overwrites a manual choice with a late response. The operator confirms the selected person once for the whole submission. Never infer the person or merge same-name packages from OCR or filenames. Existing named packages use the same mixed-file editor for supplementation. Successful creation opens that package, and supplementation keeps it visible rather than forcing the user back through the batch list.

Extend the existing create/append multipart requests with a bounded ordered file_types JSON array, one supported type per files entry. Keep legacy single-type doc_type_hint requests compatible; reject ambiguous requests containing both contracts, length mismatch, duplicate fields or unknown types. Mixed creation requires an explicit person name; append inherits the existing package. File order, not filename, binds each type to its bytes, so repeated filenames cannot overwrite metadata. The same file/aggregate/count limits apply before per-type decoding. A shared abnormal-only option applies only to medical tasks.

Prevalidate every file before writing any batch, task or blob. Persist all accepted types in one store transaction; one invalid file rejects the submission, and storage/authorization failures roll back only newly created artifacts. Preserve the live authorization/ownership recheck, expected package revision, duplicate-file/type-conflict handling, existing results/expiry and independent per-model queues. Do not implement sequential create-then-append requests hidden behind one button: that leaves a partly committed package if a later request fails. A lost response retains the existing explicit unknown-outcome/refresh behavior; do not automatically replay creation.

## Decision audit

The [pre-push isolation repairs](../bug-fix/2026-10-12-prepush-isolation-and-migration.md) fence the whole attribution-confirmation lifetime, lock reentry and reject stale account/selection/package continuations before submitting bytes. Atomic upload and manual attribution remain active.

The later [upload-before-naming and export decision](2026-10-12-person-package-name-suggestions-and-export.md) partially replaces upfront name entry: package intent is independent, names are suggested from saved results and confirmed/corrected after upload. This note retains atomic mixed submission, CPU classification, editable type suggestions and evidence boundaries; the original mandatory-name interaction below is historical.

The [person package decision](../../implemented/feature/2026-10-12-person-material-packages.md) remains implemented. This approved implementation replaces only its one-type-per-request upload interaction; encrypted attribution, immutable ownership, versioned append, duplicate handling and expiry remain. The [optional ID back decision](../../implemented/feature/2026-10-12-optional-id-card-back.md) remains active: a front-only package is valid and no back is required. The original package and optional-back notes are partially overlapping and remain active. CPU image orientation and local dual-model lifecycle constraints remain compatible. No prior note is fully absorbed or archived.

## Alternatives considered

- Put a single submit button over successive existing upload/append calls: minimizes backend work and preserves current contracts, but can commit only part of a package, repeats attribution/version handling and complicates recovery. Use one atomic mixed submission.
- Classify every input with a vision model before submission: handles opaque filenames and complex layouts, but adds model queue work and long routing latency. Use bounded CPU OCR and editable suggestions; the two vision models remain responsible for recognition after submission.
- Use filename hints only: has no extra dependencies and responds immediately, but cannot classify camera-generated filenames. The user's additional automatic-classification requirement warrants a small CPU-only OCR dependency with models bundled in the pinned wheel.
- Infer person membership from OCR names: saves typing, but fails on homonyms, missing names and the unnamed ID back. Retain explicit manual attribution.
- Require a separate drop zone/upload for every document type: avoids file-type hints, but repeats file picking and does not satisfy the user's all-materials-at-once preference. Use one combined file list.

## Behavior and invariants

A name plus mixed ID front, bank, diploma and medical files creates one named package with independent task types in one submission. Type-unknown rows cannot submit; hints are always editable. Mixed supplementation retains old results and expiry. Invalid last file/storage failure/revoked authorization creates no partial tasks or blobs; concurrent stale append fails explicitly. Owner/admin/viewer isolation and front-only export behavior remain intact. Legacy type-batch upload and mixed export remain compatible. A partial/lost response retains the explicit unknown-outcome warning and refresh-before-retry guidance. The API, field guide and web manual describe the final contract. Backend/frontend/notes checks precede activation.

## Consequences

Classification is a convenience suggestion, not recognition accuracy or identity verification. Wrong suggested/manual type or person assignment remains possible and must be visible before submit. Only the first two PDF pages are inspected; mixed-document PDFs must be separated manually. This is a workflow change involving frontend and upload/store contracts; no person registry, old-batch migration, clinical decision, GLM/Paddle model change or automatic multi-person grouping is included. The workflow and automatic-classification addition are explicitly authorized by the user.

## Verification

Twelve isolated backend tests cover content headers, filename/content disagreement, mixed/unsupported PDF pages, unknown/busy/failed classification, per-file type binding with repeated names, medical-only options, atomic invalid-last-file and storage failure, duplicate type conflicts, stale mixed append, unchanged old tasks, bank PDF rejection and authenticated memory-only classification independent of runtime availability. Frontend119 tests pass, including classification response guards, ordered mixed multipart, sequential classification, manual/removal/unmount response fencing and existing account-switch fencing; typecheck/build pass. All642 backend tests pass; DDE tree/format/archive verification and index checks pass. Final logs are in output/person-package-classification-20261012-v2/.

An isolated synthetic real browser verifies automatic content suggestions, unknown/manual choice, submission blocking, one mixed create, opening its package, one mixed append, retaining original rows, optional ID back, both-present update and legacy type mode. No production mutations or vision-model calls occur. Evidence: output/person-package-classification-20261012-v1/browser-152822/summary.json.

The read-only CPU probe uses15 distinct originals from five directory groups and opaque filenames. Initial14 matched and one medical image remained unknown; after adding its visible 本次体检项目意义 heading,15/15 match their directory labels, range0.010–1.579seconds, mean0.641seconds. This is development-set classification tuning, not independent field accuracy or identity verification. Identity-card/passport/household/business real-sample validation remains incomplete. Originals and initial failed/unknown measurements remain intact. Final source hashes are captured before and verified after the final v4 execution. Final report: output/person-package-classification-20261012-v4/REPORT.md.

## Local activation

Idle activation preserves all250 tasks,2 accounts and2,442 encrypted/key files after a verified SQLite backup. Schema0006 and application1.22.0 remain unchanged; GLM/Paddle are dual_resident/ready, queue empty, built frontend assets match served bytes, and anonymous batch/append/classification requests receive401. No original preview reads or business changes occur during this activation. Evidence: output/person-package-activation-20261012-v1/activation.json.

The final timing probe uses perf_counter/QueryPerformanceCounter (100ns reported clock resolution). Earlier v1-v3 monotonic/GetTickCount64 timings have15.625ms granularity and remain preserved; use v4 JSON/CSV for plots, not zero-rounded native-PDF timings.

The [field-region OCR](2026-10-13-field-region-ocr.md) reuses the pinned CPU asset loader in a bounded helper; upload classification behavior remains unchanged.
