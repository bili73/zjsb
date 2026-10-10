# Agent Note: Add evidence-bound card and document profiles

Status: implemented
Scope: backend/ocr_app, tests, frontend, scripts, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, requirements-app.lock.txt
Last-verified: 2026-10-10

## Problem

The UI offers material families which the production backend rejects. The user approves bank cards, both ID sides, generic recognition, business licences, Xuexin diploma tables, passports and household registers. Only bank and Xuexin samples are available for the new families; the three Xuexin samples are diploma registration tables, including alphanumeric verification codes.

## Decision

A backend document catalogue owns field names, editability, conditional applicability and required fields. GET /doc-types supplies that catalogue to the UI. Pure versioned validation distinguishes FORMAT, CHECKSUM and OFFICIAL outcomes; unknown rule coverage is not failure or authenticity. Identifiers remain strings. Extraction retains evidence and conflicting candidates, never repairs characters to satisfy a checksum. Reliable native PDF labels and coordinates precede OCR.

Canonical types are ID_CARD_FRONT, ID_CARD_BACK, BANK_CARD, DIPLOMA, DEGREE_CERT, MEDICAL_REPORT, BUSINESS_LICENSE, XUEXIN_DIPLOMA_TABLE, PASSPORT, HOUSEHOLD_REGISTER and GENERIC. Passport scope is TD3 data pages and MRZ, compatible with old and revised document codes. Licence applicability follows entity type and printed fields; household applicability distinguishes collective households. Generic text and editable key/value pairs require explicit review, not an empty-template automatic completion.

The user-requested bank crop rotation uses local left/right90-degree controls, resets the selection on rotation and binds cropping to rotated pixel content rather than a CSS-only display transform. Changing images or closing the dialog clears rotation state and owned preview URLs. The [automatic photo input and recovery decision](2026-10-09-bank-auto-recognition.md) partially supersedes the original crop-only boundary after the user requests automatic recognition first. Full single photos now reach encrypted source storage and queued OCR; missing PAN is a per-task review issue. The original crop-only rationale minimized security-code persistence and used a pure-number memory admission, but rejected entire batches on incidental OCR labels and required manual work on every card. This rationale remains recorded rather than silently rewritten. No CVV fields/export columns are added; detected explicit secret text is still rejected before OCR-attempt text is recorded, without claiming a universal detector. BIN support includes six/eight-digit evidence, but there is no invented complete issuer database. Unknown BINs remain UNKNOWN. The user additionally requests automatic issuing-bank lookup after card-number extraction. Use a pinned, licensed offline BIN snapshot with source commit, data-modified date and retrieval/hash metadata; derive bank_name, matched bin_code and explicitly covered card_type, not bank authentication. Manual or recognized PAN input with non-decimal characters or outside the explicitly supported10–19-digit compatibility range is a blocking FORMAT failure for review completion; do not confuse malformed input with an unknown bank range. Prefix matching prioritizes the most specific supported6/8-digit prefix and PAN length; more-specific unsupported/ambiguous or length-incompatible records must abstain instead of falling back to a conflicting shorter prefix. Keep a visibly derived origin with lookup provenance rather than pretend the bank name was OCR text. Recompute previously derived bank fields after manual card-number correction, preserving manual input and exposing disagreements for review. The old static source can be stale, confidence remains null and the existing human review gate stays active. Optional printed information can be entered manually.

Model lifecycle, independent FIFO queues, deadlines and frozen benchmarks are preserved. New serial sample runs use separate encrypted outputs. Unavailable confidence remains null.

## Decision audit

The [durable tasks](../../implemented/feature/2026-09-30-durable-document-tasks.md), [HR fields](../../implemented/feature/2026-10-08-hr-document-field-profile.md), [field mapping](../../implemented/bug-fix/2026-09-30-evidence-bound-field-mapping.md), [frontend rebuild](../../implemented/feature/2026-10-08-frontend-rebuild-element-plus.md) and [independent queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) partially overlap and remain active. No note is fully superseded or archived. The [review/export proposal](2026-10-08-human-review-and-xlsx-export.md) owns completion and editing.

## Alternatives considered

The [shared required-field settings](2026-10-10-configurable-required-fields.md) make required sets administrator configurable by material type for current and historical tasks. Existing tables are defaults; uncustomized types retain conditional rules. Current metadata, review and atomic export use the same persisted policy. Config revision is separate from task revision, and settings changes preserve OCR/manual values and ciphertext. This partly overlaps the required-field source without superseding presence-only export, monitoring, permissions or evidence preservation.

- Only expanding the accepted type whitelist enables uploads quickly, but leaves empty profiles, unchecked identifiers and unsafe card persistence. Implement catalogue, extraction and admission together.
- An online card-information API can provide fresher issuer mappings with little bundled data, but it would disclose card values and make local recognition depend on a network provider. Use a licensed pinned offline table; record its age and leave uncovered ranges unknown.
- A small hand-written popular-bank prefix list is easy to audit but gives sample-specific coverage and misses nested8-digit/legacy exceptions. Use a public licensed snapshot and conservative longest-prefix/length checks.
- A third semantic model can broaden interpretation, but adds loading and calibration work before the missing typed contracts are fixed. Reuse deployed recognizers and evidence-bound mapping.
- CSS-only bank rotation is small and fast but leaves visible coordinates inconsistent with uploaded pixels. Rotate the local pixel buffer used for preview and cropping. Keeping originals local was part of the earlier crop-only policy, superseded by the later user-requested full-photo workflow.
- A fixed company/family-household template is simpler, but creates impossible required fields on valid licence and collective-household variants. Use narrowly specified applicability rules.

## Verified behavior

All supported catalogue types have stable field metadata and evidence-bound extraction or explicit missing issues. Official-source rule examples and invalid checksums are tested. Other Xuexin reports are not forced into the diploma table template. Identifier conflicts require selection. The former crop-only pre-persistence screening is a frozen checkpoint, now partially superseded by automatic-photo input. Full source images are encrypted; the previous no-input-on-screening-failure guarantee no longer describes the current photo workflow. Real bank and Xuexin results are measured separately from synthetic rule coverage.

## Consequences

No ID, licence, passport or household sample set is available to qualify recognition accuracy. Card-region screening is conservative and not a universal CVV classifier. Unknown layouts and historical numbering remain reviewable rather than guessed.



## Verification

All 11 catalogue types and validation paths are implemented. CPU rule and schema tests cover representative valid/invalid/unknown examples; bank memory admission has synthetic pre-persistence regressions and shared 40-second batch budget. Native-only real Xuexin PDFs each populate 17/19 fields without model calls, but four graphical regions per document remain unprocessed, so this is not full-report success or accuracy. The first GPU preflight did not start while the existing application owned the shared lock; that failed v1 and the prepared encrypted fixtures are preserved. After an idle application shutdown, a new serial single-resident GLM run in output/document-profile-samples-20261008-v2 completed six cases with startup29.047s. Three manually cropped card-number rows agree with the provisional old reference3/3; admission inference takes0.453–0.500s and end-to-end processing0.578–0.610s. This is one field on three manual crops, not full-card accuracy or automatic localization. Two Xuexin PDFs take9.516/9.531s with4 model calls each, and one image takes8.828s with1 call; all are NEED_REVIEW with zero unresolved regions. Filled fields are16/19,16/19,17/19, not accuracy. A narrow duration normalization fixes whitespace-only number-plus-year conflicts while preserving source text and true disagreements. A separate CPU replay reuses saved predictions with0 model calls and obtains17/19 on each Xuexin file, with every old encrypted blob hash unchanged. New card profiles have7 fields after removal of the redundant masked display field; the true card number and source remain unchanged. Frozen GPU times and original denominators remain preserved; no new-model, Mac or production concurrency benchmark is claimed.

## Final offline-bank and review verification

The pinned MIT hexindai/bcbc snapshot contains1709 prefix rows and275 bank names, with data-modified2020-12-11 separate from retrieval2026-10-08. The new CPU replay in output/bank-bin-mapping-replay-20261008-v2 covers3/3 saved card-number samples and derives bank_name/bin_code/card_type with0 model requests, unchanged PAN/evidence and unchanged encrypted source blobs. This is lookup coverage, not independently labelled issuing-bank accuracy. The frozen replay precedes the final PAN gate change in validation.py/review.py; its original hashes/timings remain intact. Final malformed-PAN regressions cover nonnumeric, short and long values, non-acceptable FORMAT issues, HTTP EXPORT_BLOCKED, and successful correction to a valid unknown-range PAN. Unknown BIN/Luhn applicability remains UNKNOWN and reviewable. The final backend suite passes402 tests in12.136s; final sources are recorded separately in output/document-review-acceptance-20261008-v1/source-hashes-release.json. Existing stored recognition results are not rewritten and need rerun to use the new extractor.

## Export-policy boundary

The later [required-fields-only export decision](../simplification/2026-10-08-required-fields-only-export.md) allows saved nonempty required values to export even when validation or confidence remains unresolved. The strict FORMAT review issue still cannot be accepted and does not manufacture COMPLETED. The402-test reference above is a frozen pre-policy checkpoint; the final409-test suite verifies the new export semantics. BIN lookup and original evidence are unaffected.


## Current input-policy refinement

The [automatic bank-photo recognition](2026-10-09-bank-auto-recognition.md) replaces only mandatory crop/pure-number upload admission and crop-only server sources. The catalogue, offline BIN snapshot, validation, actual-pixel rotation, export policy and all frozen manual-crop timings/denominators remain active. Full-photo recognition has flow coverage, not a new real-bank accuracy measurement.
