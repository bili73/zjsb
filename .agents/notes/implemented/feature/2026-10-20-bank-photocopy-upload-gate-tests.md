# Agent Note: Pin the bank photocopy upload gates after the f0804c0 audit

Status: implemented
Scope: frontend/tests/upload-confirmation.test.ts
Last-verified: 2026-10-20

Integrity check of the backend's f0804c0 BANK_CARD_COPY frontend integration (frontend-handoff next-step candidate); the batch landed as test-only hardening of the gap the audit found.

## Problem

The audit concluded the implementation itself is complete (matrix below), but the upload gates that f0804c0 silently widened from `BANK_CARD` to both bank types had zero test coverage — `isBankCardType`, the gate messages, or the submit guard could regress unnoticed.

## Audit result (implementation complete — no product code changed)

- UploadPanel.vue: all five former `BANK_CARD` hard-codes generalized via `isBankCardType` (single-type PDF rejection, mixed-mode offender naming, photoOnly tip, submit-time extension guard) plus the typeMeta entry with its desc.
- business.ts (docTypes label「银行卡复印件」, isBankCardType guard, sampleQualification group), bankCrop.needsBankCrop, numberLength card_number hint, guide.ts upload-types/upload-files steps, workbenchEntries STORED_LAYOUT_MAX_KEYS 14 (12-cap splitEntries unchanged), ResultView/ReviewEditor/SourcePreview/TaskResultDrawer locate/candidate lists, BankCardRecovery photocopy branch (upload kind passthrough already pinned by detail-loading.test.ts).
- The help manual's bank copy text survived the 7009827 reorder byte-identically (machine-compared).

Gap: nothing pinned the generalized UploadPanel gates — `isBankCardType` or the gate messages could silently regress.

## Decision

- Extend the existing upload-confirmation.test.ts compile-mount harness (expose list gains docType/invalidReason/photoOnly) rather than add a new file — that harness already owns UploadPanel lifecycle behaviour (confirmations, submit fences).
- Four regressions: single-type BANK_CARD_COPY rejects a PDF at selection with the 银行卡及复印件 message and photoOnly true, with a DIPLOMA contrast proving the gate did not over-widen; mixed mode names the photocopy PDF offender file; submit refuses copy.pdf even though validateUpload accepts the extension; copy.jpg submits with type BANK_CARD_COPY passed through untouched.

## Alternatives considered

- Source-string assertions instead of mounting: rejected — cannot observe computed gates or the submit early-return.
- A dedicated new test file: rejected — duplicates the harness for no benefit.
- Leave untested: rejected — the gates silently changed scope in f0804c0 (one type to two); without a red-test tripwire a future refactor could narrow them back unnoticed.

## Verification

- upload-confirmation.test.ts alone: 12/12 (8 existing + 4 new).
- Full suite 289/289 pass, 0 fail — includes 4 tests belonging to the backend's separate in-flight frontend batch (natural filename ordering), not to this note.
- vue-tsc --noEmit + vite build exit 0 (chunk-size warning = known noise). Root npm run verify green with this note.
- Pre-commit 3-dimension review ran inline again (Workflow/Agent still absent this session, re-checked at batch start): correctness/contract via the audit matrix against every f0804c0 frontend hunk, test-quality via the harness-reuse rationale above.

## Consequences

- The photocopy entry now has the same regression protection as the original bank card path; narrowing isBankCardType, the gate messages, or the submit guard turns tests red.
