# Agent Note: Reuse certificate footer rules for degree school and award dates

Status: implemented
Scope: backend/ocr_app/extraction.py, tests/test_certificate_mapping.py, tests/test_diploma_mapping_repair.py, tests/test_degree_mapping_repair.py
Last-verified: 2026-10-12

## Problem

Read-only inspection of two recent recognitions of the same degree image identifies concrete differences. One OCR output misreads the heading school but reads the signing institution correctly. Both are currently unlabelled candidates of equal authority, so school_name is unresolved. Its complete award date has a spurious opening parenthesis and is rejected by the standalone-date grammar. The existing Chinese/O year normalizer already converts the inner date correctly; this is not evidence that rules can restore unreadable characters or correct every rotated image.

The user approves extending the successful diploma mapping rules to degrees and auditing reusable rules in other documents. Image decoding already applies EXIF orientation. No new model or orientation pipeline is required for these verified mapping failures.

## Decision

Share school whitespace normalization and signature boundaries between diploma and degree extraction. In degrees, an unlabelled institution immediately adjacent to a signing title within the same text block has the same authority as an explicit school label, above narrative and bare heading text. Conflicting equally authoritative labels or signing institutions still abstain. Preserve source text and uncalibrated confidence; never resolve by filename, a guessed school dictionary or another person's document.

Reuse the calendar-validated complete-date grammar, including a retained day numeral with missing 日, only for diploma issue_date and degree award_date. Permit peripheral parentheses and punctuation within these labelled or certificate-number-anchored date contexts. Preserve month precision, reject invalid/masked/unknown suffixes, and keep birth/study dates excluded from footer recovery. Use each certificate profile's own number aliases and token boundaries; the diploma's generic 编号 aliases do not become global degree/card aliases.

Other document families already share date conversion, cell evidence and conflict detection. Their identifier and date-role semantics stay separate; no speculative cross-parser framework is introduced. Mapping replay uses frozen OCR only, keeps previous outputs and saved human revisions unchanged, and is not a fresh model accuracy benchmark.

## Decision audit

- [Diploma mapping](../../implemented/bug-fix/2026-10-09-diploma-school-and-date-mapping.md) partially overlaps. Its former degree-date exclusion is narrowed by the newly approved award-date extension; study interval semantics, diploma-only partial number labels and all other rules remain. Neither note is fully superseded.
- [Evidence-bound mapping](../../implemented/bug-fix/2026-09-30-evidence-bound-field-mapping.md) partially overlaps and remains the source/conflict contract.
- [Document profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) partially overlaps and retains per-type identifiers, roles and required fields.
- [Rejected certificate localization](../../rejected/feature/2026-10-09-certificate-field-localization.md) is unrelated to the approved mapper fix and stays rejected.
- Proposed host/auth notes and medical notes are unrelated to the changed certificate rules. Active proposed/implemented/rejected notes were searched; no proposal or implemented note is fully absorbed.

## Alternatives considered

- Keep every unlabelled school at equal authority: exposes every OCR disagreement, but discards an institution with signing context because a decorative heading was misread. Rank only observed explicit/signing context; same-tier disagreement still needs review.
- Add fuzzy school correction or a school dictionary: can improve apparent fill rates, but may silently choose the wrong issuer and hides genuine OCR errors. Use only observed source values.
- Rerun or rotate every image through another model: can recover text absent from OCR, but adds latency and does not fix a date already present being rejected. Repair and replay these verified mapping defects first.
- Relax all dates and number labels globally: provides broad reuse with less code, but creates unsupported birth/validity dates and unrelated identifiers. Keep the permissive grammar and aliases bound to their semantic roles.

## Verification

The anonymous observed reproduction fails before the fix and recovers its signing school and printed award date after it. The 14 new regression tests cover spaced signatures/schools, explicit versus signing conflicts, bare school conflicts, parentheses, missing 日, month precision, invalid/masked dates, identifiers and birth/study exclusion. A related diploma case reproduces the overlapping 学校/校长 boundary that previously discarded the labelled university and selected 本校网络教育学院. All 577 backend tests pass; the full [test log](../../../../output/degree-mapping-20261012-v1/backend-tests.log) and initial failing reproductions are retained.

Read-only [mapping replay](../../../../output/degree-mapping-20261012-v1/replay.json) covers 48 frozen historical EOS outputs (36 diploma, 12 degree) and 156 saved production EOS attempts (143 diploma, 13 degree). There are 13 field changes across 12 production outputs: five previously missing degree award dates, the reported conflicting degree school, and seven diploma school values restored to their explicit printed university label rather than 本校网络教育学院. Repeats are not independent samples. The frozen reference outcomes are identical before/after; these provisional historical labels are not a new accuracy measurement. All 153 saved certificate tasks retain their ciphertext results and revisions, and all consumed originals/frozen files retain their hashes. No model calls or production result writes occur.

Idle local activation loads this mapper into the running service with both recognition models ready. The [activation evidence](../../../../output/degree-mapping-20261012-v1/activation.json) verifies unchanged pre-restart rows, encrypted blobs and keys for 206 tasks and two accounts, matching static assets and the anonymous-write authentication gate. During startup an authenticated original-image preview appends one access-history artifact and audit event; these legitimate new records are preserved and verified separately rather than restoring a stale database snapshot. The initial readiness check preceded Paddle warmup, and the stricter whole-store check detected that append; both diagnostic outcomes remain recorded.

## Consequences

The subsequent [certificate photo preparation](../feature/2026-10-12-certificate-image-upright.md) adds source-preserving CPU orientation/deskew before OCR. It supplements this mapper without replacing its field/date authority or conflict policy.

Signing context is useful evidence, not a guarantee against OCR errors. Damaged or same-tier contradictory text remains reviewable. These changes do not add geometric deskew, calibrated confidence or a new model; real tilted-image recognition quality still depends on the OCR output.
