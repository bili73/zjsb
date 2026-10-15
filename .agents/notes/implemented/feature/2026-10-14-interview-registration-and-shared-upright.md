# Agent Note: Add interview registration and complete entry-wide image orientation

Status: implemented
Scope: backend/ocr_app, frontend/src, tests, frontend/tests, scripts, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-15

## Problem

The user requests a 面试登记表 entry with required name, gender, age, ID number and mobile number, and automatic upright preparation in every recognition entry. Eight JPGs in the supplied sample directory have been visually inspected. They share an 应聘登记表 form, include a sideways photograph, handwritten names/numbers, checkbox gender, one digit per ID cell, nearby emergency-contact information and a number misplaced in the name cell with the name written just above it. Background show-through and a second form peeking below a page can contaminate extraction.

Current raster preparation covers certificate/card types and GENERIC; TABLE calls it through its own pipeline. MEDICAL_REPORT raster uploads bypass it. PDFs respect PDF rotation metadata but never use the pixel orientation helper. The catalogue has twelve types and personal/default layout writes cap arrays at twelve.

## Decision

Add INTERVIEW_FORM with exactly five initial fields: name (姓名), gender (性别), age (年龄), id_number (身份证号) and mobile_number (手机号). All are required by default and remain editable through the existing administrator required-field policy. Preserve full source text and original/corrected pages, without exporting unrelated application content as business fields.

Paddle table recognition is primary; GLM ordinary OCR makes at most one alternate attempt for missing, invalid or incomplete basic-information fields within the same task deadline. Both use a20-second generation soft budget. Qualification compares both models and modes serially on the same source-bound crops: Paddle table retains checkbox selection better; GLM ordinary OCR can recover out-of-cell handwriting. Truncated output remains evidence but does not populate final fields. No model or queue is added; interview tasks share the Paddle lane.

Locate the basic-information table with printed labels and observed table/text geometry. Include a margin for nearby handwritten corrections; do not use sample-specific pixel coordinates or assume the largest table is the right subject. Preserve a whole-region fallback when localization is uncertain. Recover adjacent ID digit cells only within the identified row; process selected gender options only within the gender cell. Mobile extraction uses the applicant's mobile label and region, excluding emergency contacts. A misplaced ID may be recovered as a candidate with source attribution, but must not become a name or be silently relocated on checksum evidence alone. Conflicts stay visible for human correction; unknown confidence remains null. Age is the age written on the form, not today's age inferred from ID. Missing gender/age is not filled from ID. Existing ID checks and a conservative mobile-format check provide review hints, never automatic character repair or official authentication.

Retain existing required-value-only export eligibility: saved required values must be present; validation issues do not silently introduce a new export gate. Export the five saved fields in that order, with identity/mobile values as text. Reuse the current orange header, white data fill and Microsoft YaHei 12-point fonts. Include the type in person-package classification, name suggestions and complete-field exports. Existing account authorization, task revisions, partial results and manual values remain in force. No business database migration is expected for adding this profile.

Enable the existing conservative EXIF/quarter-turn/small-angle preparation for all supported raster entry types, including medical and interview forms. Apply it to pure scanned PDF pages without usable native text, caching decisions by page across both decoding passes. Reliable native-text and mixed pages retain their existing extraction/coordinate path; respect PDF rotation metadata and do not rasterize away usable text. Corrected preview pixels, OCR inputs, region boxes and any field coordinates must agree. Blank/uncertain/missing-model cases preserve the unforced image and show the existing warning. No perspective or page-warp model is added. Region-OCR crops retain the operator-selected orientation and are not separately reinterpreted by this entry-level extension.

Expose the new entry and material labels, classification and review UI. Raise matching layout/API/schema limits from twelve to thirteen so a full catalogue can still be saved; existing personal and administrator layouts are not rewritten. In saved custom layouts the new type starts tucked under the existing policy and can be added explicitly. The new form's source links may locate identified regions; certificate localization remains unchanged.

## Related-note audit

- [Card/document profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) remains the typed field/validation authority; this extends its catalogue.
- [Adaptive forms](../../implemented/feature/2026-10-14-adaptive-generic-forms.md) supplies existing layout/OCR capabilities, but GENERIC keeps its dynamic result contract.
- [Photo-table conversion](../../implemented/feature/2026-10-13-photo-table-to-excel-replan.md) keeps its independent matrix/export workflow.
- [Upright preparation](../../implemented/feature/2026-10-12-certificate-image-upright.md) is partially extended beyond its original allowlist and PDF exclusions; thresholds, preserved originals and abstention remain.
- [Bank orientation](../../implemented/bug-fix/2026-10-12-bank-card-roi-orientation.md) retains its special card-view logic.
- [Account layouts](../../implemented/feature/2026-10-14-account-workbench-layout.md) and [administrator defaults](../../implemented/feature/2026-10-14-admin-workbench-default.md) retain isolation, explicit save and revisions; only catalogue capacity grows.
- [Required-only export](../../implemented/simplification/2026-10-08-required-fields-only-export.md) remains unchanged. No proposal or implemented note is fully superseded; no archive is required. Rejected certificate positioning/third-model work and deployment proposals are outside this change.

## Alternatives considered

- Show ID length problems only in the backend review tooltip: reuses existing metadata, but old saved results retain the vague message and operators cannot see the count while editing. The approved refinement adds a display-only count beside saved values and live drafts, without changing recognition, persisted evidence, validation status or export eligibility.
- Reuse GENERIC without adding a profile: immediately available and flexible, but cannot offer the requested five fixed required fields and predictable export columns.
- Whole-page OCR followed by unconstrained regex: smallest implementation, but can select emergency contacts, printed checkbox options and wrong-cell text. Use observed labels/cells and preserve ambiguity.
- Fixed crop coordinates: fast for these similar samples, but fail sideways pages, differing camera positions and handwriting outside cells.
- Automatically derive missing age/gender or repair ID digits: fills more fields, but mixes inference with recorded form values and can hide contradictory originals.
- Rotate every PDF page raster indiscriminately: simpler uniform code, but risks native-text/table coordinates and loses the text-layer speed advantage. Extend pure scanned pages only.
- Add another model: may improve handwriting, but has no supporting measurement here and expands deployment unnecessarily.

## Validation

Eight unchanged original photos are qualified under Windows CUDA with one resident model and serial calls. The final full-pipeline run fills34/40 target fields, with32/36 matching visually confirmed references; four ambiguous names are excluded. Five files have all five values. This is a same-template tuning set, not independent or Mac accuracy. One original contains19 written ID digits: preservation counts as transcription agreement, not valid identity. Wrong-cell candidates and cross-model disagreements remain manual.

Pipeline wall time is4.937–21.578 seconds, mean13.1855 seconds, including CPU preparation, model switches/loading and fallback; startup6.812 seconds is separate. No task times out. One Paddle repetition stop is preserved and falls back. The first full run is retained as failed qualification because intentional benchmark switching was misclassified as model death. The repaired second run preserves all source hashes and stops its runtime. [Report](../../../../output/interview-pipeline-20261014-v2/REPORT.md), [field metrics](../../../../output/interview-pipeline-20261014-v2/fields.csv), [call metrics](../../../../output/interview-pipeline-20261014-v2/cases.csv) and encrypted raw/reference evidence stay outside Git.

The780-test backend suite completes with only two old version-literal assertions failing; after updating them, all27 contract/runtime API tests pass. Thirty final targeted tests include the additional interview person-package name and complete-column export case. The182 frontend tests, typecheck/build, actual Edge upload/candidate/manual-save/XLSX/auth-isolation checks and eight account-layout browser groups pass. Synthetic tests cover ambiguous checkboxes, digit cells, contact contamination, malformed originals, wrong-cell/manual candidates, cross-model conflicts, truncation, bounded fallback, conservative region selection and cancellation. Raster tests cover all newly enabled entry paths; pure-scan PDF decisions are cached per page and native/mixed coordinates remain unchanged.

## Consequences

[Applicant ownership repairs](../bug-fix/2026-10-15-review-integrity-and-table-performance.md) enforce contact exclusion for headings outside tables and family/work sections. Generic phone labels require applicant ownership on multi-table pages. Ambiguous values remain missing for manual review; previously saved phones are not inferred or rewritten.

The ID-length hint counts non-whitespace characters against the existing18-character rule, including terminalX, and states the observed count and excess/shortfall. Empty fields keep their existing missing-value hint. A shared frontend helper serves result and review views so old batches benefit without rerunning OCR or rewriting saved results. It never trims, truncates, repairs or submits a number;18 characters alone do not establish validity. The184 frontend tests and build pass. The isolated real-HTTP/Edge probe verifies short/long live drafts, explicit save of an unchanged19-character value, the saved-result hint, manual correction to18 characters, unchanged original evidence, Excel values and account isolation. Backend validation metadata and export policy remain unchanged.

The first full eight-file serial probe reproduced an existing single-resident lifecycle race: health polling observes a model exiting during an intentional switch and marks it failed. Subsequent forms fall back without Paddle. The failed probe is retained; health polling uses the existing serial execution lock and all eight inputs are rerun. This is a prerequisite repair for the approved bounded alternate path, without changing residency or recovery policy; the [production residency decision](../architecture/2026-10-14-production-dual-residency.md) records the user-requested production change and benchmark-only switching invariant.

Handwritten digit/name ambiguity and checkbox marks may remain unrecognized. The application must keep the source available for manual entry rather than force a complete result. CPU orientation adds bounded work to scanned medical pages; do not claim lower total latency without measurement. Only one form family and eight photos are supplied. Mac deployment and handwriting fine-tuning are not part of this implementation.


## Local activation

Version1.26.0 is active on the Windows loopback service after isolated probes stop. The [activation verification](../../../../output/interview-activation-20261014-v1/verified.json) confirms both model load/warmup events and live owned processes, fixeddual_resident, all13 database tables unchanged against the pre-test snapshot,283 tasks,2 accounts and2881 material/key files preserved. All15 candidate static files match HTTP responses; anonymous business/full-health requests return401, public health is minimalok. The first static check caught a publication helper skipping nested index.html files; the help page was atomically corrected and the entire check passed. No Mac deployment, account login, commit or push occurs in this activation.

The final browser probe also verifies source-overlay size against the corrected image, and candidate buttons wrap instead of overflowing. Both the operator workflow and13-entry account-layout flow pass. The user manual and schema describe the implemented five-field behavior and limits.

The [twelve-visible-card correction](../bug-fix/2026-10-14-workbench-twelve-visible-cards.md) enforces12 visible entries for every layout independently of the13-type catalogue. Existing13-key preferences remain readable; excess cards are hidden rather than removed. This supersedes the interview extension display-cap increase, retaining the wire compatibility and original account rules.

The display-only ID-length refinement is published to the Windows service. Its [publication verification](../../../../output/id-length-hints-20261014-v1/publication/verified.json) confirms13 static files against their HTTP responses, healthy service and unchanged model processes. Existing task results and backend processes need no migration or restart.

[Shared number-length hints](2026-10-14-number-length-review-hints.md) extend the same saved/live presentation to bank and certificate fields. The ID rule and original-data preservation contract remain unchanged.
