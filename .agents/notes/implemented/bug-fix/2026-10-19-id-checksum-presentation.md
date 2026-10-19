# Agent Note: Explain failed ID checks without invalidating human confirmations

Status: implemented
Scope: backend/ocr_app/validation.py, backend/ocr_app/export_disputes.py, backend/ocr_app/task_store.py, tests, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, frontend/public/help
Last-verified: 2026-10-19

## Problem

The id_cn_v1 CHECKSUM failure shares the neutral PASS message. Operators cannot tell what failed. Message text also participates in v1 dispute fingerprints, so a direct wording replacement would revoke historical human confirmations. The user approves a compatible presentation change on2026-10-19.

## Decision

Keep PASS wording and every check outcome/value unchanged. FAIL says the last check digit disagrees, asks the operator to inspect the original, and states local-only verification. Normalize only this known new ID-checksum failure message to its old text when constructing v1 dispute fingerprints, including legacy generated task-level failures with no rule ID. All other fingerprint inputs remain unchanged.

Public projection updates the exact old failure wording in a copied validation-check/review-issue object, without rewriting saved ciphertext, source, OCR text, user values or confirmation history. Existing confirmations retain their IDs and actor/time. Changes to value, source, run, field or other rule still require review. No checksum-based digit repair, global fingerprint version change or migration is introduced.

## Decision audit

[Dispute export gates](../../implemented/feature/2026-10-14-disputed-results-export-gate.md) retain semantic evidence and all unrelated messages in the fingerprint. [Ordinary-save confirmation](../../implemented/feature/2026-10-14-save-confirms-export-disputes.md) retains the approved save interaction. Both partially overlap and remain active; proposed/rejected searches find no competing checksum presentation decision.

## Alternatives considered

- Replace the validation string only: minimal code and works for new results, but changes fingerprints and leaves old stored failure explanations neutral.
- Remove all messages from every fingerprint: makes future editorial changes easier, but changes all v1 IDs and weakens unrelated compatibility boundaries; freeze only the specific approved wording.
- Rewrite historical rows: would align stored messages, but creates unnecessary migration and preservation risks; project copied responses instead.

## Testing

Six dedicated tests pass, including frozen pre-change field/task fingerprints, household-member and interview contexts, copied public projection, and value/source/run invalidation. The real-HTTP test seeds legacy encrypted results and confirmations, reads task/detail, exports Excel and performs an empty ordinary save: the saved number/source, original run row, historical confirmation IDs/actor/time and export eligibility remain unchanged. Reads and exports leave the result ciphertext byte-for-byte unchanged. PASS text and unrelated conflict explanations remain unchanged.

The combined109-test preview/checksum/audit/contract/review/authorization regression passes. The final dedicated preview/checksum run passes12 tests after the metadata and resize-version regression additions. The complete Windows backend suite runs993 tests in462.656s (986 pass,7 existing environment skips); a final32-test checksum/contract/audit run also verifies preservation with the frontend confirm_export_disputes=true save flag. The current Windows process and Mac services are not restarted or deployed by this change.

## Consequences

The legacy fingerprint wording is a deliberate compatibility constant. Future changes to rule meaning must not reuse this editorial alias to retain an obsolete acknowledgment.
