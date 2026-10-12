# Agent Note: Keep adjacent document labels out of field values

Status: implemented
Scope: backend/ocr_app/document_fields.py, backend/ocr_app/extraction.py, tests/test_document_profiles.py, tests/test_document_field_boundaries.py
Last-verified: 2026-10-12

## Problem

A saved ID-card prediction reads 性别 男 民族汉. The existing mapper returns the entire 男 民族汉 as gender and leaves ethnicity missing. The shared household member mapper has the same defect. Inspection also identifies compact birth-date/nationality labels following gender, same-line combined validity labels following an issuing authority, and certificate holder names followed by a compact 性别 label as related boundary cases.

## Decision

Retain the existing evidence-bound extraction. Split a closed gender token only when followed by an explicit demographic label present in the current profile. Preserve the original source and genuine disagreements. Do not infer demographics from document numbers. Recognize combined 有效期限 and 营业期限 labels internally when the profile contains both corresponding date fields, including table cells; never expose an extra catalogue field. Name boundaries in shared profiles and certificates recognize an explicit compact gender label followed by a closed gender token. Other unlabelled or ambiguous text remains missing or reviewable. A demographic tail containing another known label is not copied as one field; invalid compact birth dates remain missing rather than accepted as demographics.

## Decision audit

The [card/document profiles](../../implemented/feature/2026-10-08-card-and-document-profiles.md) and [certificate mapping](../../implemented/bug-fix/2026-09-30-evidence-bound-field-mapping.md) remain active. This repairs adjacent-field boundaries without replacing field catalogues, certificate date roles, validation, ownership, medical summaries or model routing. No previous note is fully superseded.

## Alternatives considered

- Removing all label separators would support many compact OCR layouts with one regex change. It also misreads labels embedded in ordinary values such as 民族团结路, so only explicit closed-value contexts are extended.
- Taking the first character of every gender value is short and would fix this example. It could silently accept unrelated or corrupt text; require an explicit adjacent label and retain evidence instead.
- Rewriting saved tasks makes the correction visible immediately, but can overwrite manual edits and detach a result from its recorded run. Apply the mapper to new recognition runs and read-only saved-output replays.

## Verification

The initial ID tests fail four subcases before the fix. The cross-family boundary suite independently reproduces fourteen failing subcases, then an additional shared-name test reproduces four more. Final backend verification passes629 tests in36.981s. Tests cover plain text, combined table cells, native aligned values, household page boundaries, Xuexin/passport demographics, validity ranges, ordinary-value false positives, certificates and bank/generic non-regression.

The read-only CPU replay in output/document-field-boundaries-20261012-v2/ compares204 saved task texts:164 diploma,15 degree,18 bank,6 Xuexin and1 ID front. The affected ID changes only gender and ethnicity, resolving to M and 汉 with the actual original attempt source retained. Four diploma results gain a previously missing gender; their other fields remain unchanged. Other replayed values are unchanged. All selected encrypted input files and saved result ciphertext hashes match before/after; there are0 model calls and no production task writes. These are historical task replays, potentially repeated source materials, not an independently labelled OCR accuracy denominator. There are no real back-side, licence, passport or household samples in this replay; synthetic flow coverage does not establish those families' recognition accuracy. Before-fix logs and intermediate replay outputs remain intact.

## Consequences

Unknown compact labels and ambiguous multi-field merged values can still require review. Missing real licence, passport and household samples prevent a claim of end-to-end recognition accuracy for those families. No automatic rewrite of old or manually corrected results is included.

## Local activation

The idle Windows service is restarted from a verified SQLite backup in output/document-field-boundary-activation-20261012-v1/. Both models report ready/dual_resident, the queue is empty, served static assets match the existing build and anonymous business requests return401. All250 original task rows,2 accounts and2,440 original encrypted/key files retain their hashes. The initial exact whole-table check detects two concurrent original-preview reads after restart: two new preview_full audit rows and matching access_history artifacts/files. The retained diff explains the first check failure. Final verification permits only those additive read records, proves every preexisting row/file unchanged, and records the two reads explicitly rather than hiding the difference. No production rerun or manual-result rewrite is performed for acceptance.
