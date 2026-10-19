# Agent Note: Keep contract document headers in sync with their bodies

Status: implemented
Scope: SPEC.md, openapi.yaml, ARCHITECTURE.md, RUNTIME.md, IMPLEMENTATION_PLAN.md, FRONTEND_FIELDS.md, LOCAL_OCR.md, README.md, CLAUDE.md
Last-verified: 2026-10-19

## Problem

The contract documents plus README carry version references in headers, badges and cross-links（依据/对应业务/API版本/更新日期/对应 SPEC vX/badges）. Through 2026-10-16, batches advanced SPEC.md, openapi.yaml and application code to v1.33 / 1.26.0 but left other documents at older values: IMPLEMENTATION_PLAN.md cited SPEC v1.23 / OpenAPI 1.17.3 with 更新日期 2026-10-09 and its content stopped at 2026-10-12; ARCHITECTURE.md banner said v1.15 / 1.13.0 with 更新日期 2026-10-08; FRONTEND_FIELDS.md said SPEC v1.31 / 1.25.0; the openapi description cited SPEC v1.28 and its app-version example said 1.12.0; README badge said v1.31. Stale "11类/11种" catalogue claims survived the two later catalogue additions（TABLE on 2026-10-14 and INTERVIEW_FORM on 2026-10-15，13 entries since）, and fixed seven-day retention claims survived the 2026-10-15 configurable-retention change. No existing note assigned ownership of these header lines, so drift accumulated across every batch.

## Decision

Any batch that changes the body, contract version, or enumerated current-state capability of a contract document must, in the same batch, update that document's header and cross-references: 依据/对应 lines, 对应业务/API版本, 更新日期（or the dated section header）, 对应 SPEC vX lines, README badges, and app-version examples in openapi.yaml. The authoritative values are SPEC.md's version line, `version.py` APP_VERSION（imported by API/diagnostics and kept equal to openapi.yaml info.version and frontend package/lock versions）, and DocTypeEnum in code. Historical narrative inside dated records（RUNTIME.md per-round sections）is never rewritten; ambiguous "当前" statements there get a date prefix instead. Mechanical reference repair must not invent acceptance records or change contract semantics.

The 2026-10-18 drift repair is the first application: headers of all seven contract documents plus README badges now read SPEC v1.33 / OpenAPI 1.26.0 / 2026-10-18 where they state current state; "11类" claims became "13类（12种业务类型及TABLE）"; fixed-seven-day retention claims became admin-configurable retention; IMPLEMENTATION_PLAN.md gained subsystem code entries and a dated catch-up section for the v1.25–v1.33 features landed 2026-10-10～10-18, with links only to notes that exist.

Current-state summaries in SPEC.md, FRONTEND_FIELDS.md, IMPLEMENTATION_PLAN.md and ARCHITECTURE.md also follow the implemented rules: saved business results need required values and no unresolved explicit export disputes, while TABLE keeps its own header/structure/completeness gates; neither export path requires COMPLETED. Ordinary review save acknowledges confirmable disputes without a separate confirmation button, and this does not waive the stricter completion checks. Production stays dual_resident; single_resident is isolated benchmark-only. Browser access uses named Cookie sessions with CSRF and revocation; legacy API keys remain bootstrap-only while web_users is empty. Material retention is administrator-configurable at 7/15/30 days or never, applies to old and new uploads with confirmation, and protects queued/active work until it stops. These are description repairs, not new product decisions; dated historical acceptance records remain unchanged.

## Decision audit

A query of .agents/notes for header/version-sync rules found none. The closest is the DDE workflow note（2026-09-29-dde-project-workflow.md）, which governs notes discipline but not contract header fields. This note extends it; no older process decision is superseded.

## Alternatives considered

- Regenerate all headers from one template on every release. Rejected: the documents intentionally use different header styles（banner vs bullets vs badge）; a generator adds tooling for seven files and a new drift surface of its own.
- Centralize current-state in SPEC.md and strip headers from the other documents. Rejected: readers and CLAUDE.md rely on per-document headers for fast orientation; removal reduces discoverability.
- Repair the drift without a rule. Rejected: drift re-accumulates batch by batch; this repair would decay the same way within weeks.

## Consequences

After a batch lands, every contract document header can be trusted without cross-checking. Reviewers get a mechanical check: header values vs SPEC/openapi versions vs code enums. The rule costs a few minutes per contract-touching batch and does not constrain historical dated sections, which stay immutable.

## Verification

- 2026-10-18: the seven contract documents and README state SPEC v1.33 / 1.26.0 / 13类 consistently where they describe current state; openapi.yaml app-version example updated to 1.26.0; no x-implemented semantics or acceptance records were altered.
- 2026-10-18: `npm run verify` passes after the repair batch (124 notes, tree and relative links green).
- 2026-10-19: current export summaries and bank-card confirmation text are checked against `exporting.py`, `export_disputes.py`, `review.py` and `ReviewEditor.vue`; production mode against `launcher.py`/`start.ps1`; browser/bootstrap authentication against `auth.py`; retention against its existing implemented decision. The four edited contract documents carry the new verification date while SPEC v1.33 / API 1.26.0 and historical acceptance records are unchanged. No runtime code, service state or business data is changed by this documentation repair.
