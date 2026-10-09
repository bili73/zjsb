# Agent Note: Recover printed diploma school and date fields without suppressing genuine conflicts

Status: implemented
Scope: backend/ocr_app/extraction.py, backend/ocr_app/doc_profiles.py, backend/ocr_app/task_store.py, frontend/src, tests, scripts/replay_oct9_repairs.py, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-10-09

## Problem

Read-only production audit and original-image review identify concrete mapping misses. Zhao's frozen GLM EOS output prints the complete school label followed on the same line by 院长; the extractor lacks this signatory boundary and rejects the combined school value. Kong's certificate body prints 岭南师范学院, while its decorative cover is OCRed as 莆南师范学院; equally ranked title and explicit labelled candidates become a conflict. This is not proof that every school miss is a mapping defect, but these examples already contain usable source text.

Current graduate_date accepts only explicit graduation labels, while a standalone certificate footer goes to issue_date. Existing tests intentionally prohibit inventing graduation from a study interval. Thus many visible footer dates do not fill the required graduation field. The date grammar also excludes Latin O in year digit positions and some inline footer dates, although the original printed Chinese-year style is visible in samples. Frozen attempts and current fields are in [triage audit](../../../../output/triage-20261009-v1/audit.json).

## Decision

Add observed signatory boundaries including 院长 with spaced-label forms; these delimiters do not restore removed signatory fields. Rank an explicit printed 校名/学校名称 field above an unlabelled cover/title candidate. Distinct equally authoritative explicit labels remain conflicts, and lower-authority text stays available as source evidence. Do not fuzzy-correct a school against a guessed dictionary or choose by filename.

Parse observed Chinese date typography, including O/0/〇 within a validated date context, and source-bound certificate footer dates on the same line as a certificate number without modifying the certificate number. Never globally replace identifier characters. Keep actual date precision and invalid/conflicting dates unresolved.

The user explicitly resolves date meaning on 2026-10-09: in a printed study interval, the first date is enroll_date and the second is graduate_date. The certificate footer remains issue_date and must never substitute for graduation. Preserve month-only or day precision exactly as printed. Both endpoints need valid calendar values and chronological order; incompatible explicit graduation labels or distinct intervals remain conflicts. This replaces the old deliberate interval-end abstention through a new decision rather than silently rewriting its historical rationale.

First replay current frozen OCR outputs and original sample labels to isolate mapping changes from model changes. Preserve original runs and manual corrections. New recognition uses the corrected mapper; old results can be rerun/version-corrected without silently replacing saved human fields. Still unreadable or equally authoritative conflicts require review rather than fabricated confidence or a third model.

## Decision audit

[Evidence-bound mapping](2026-09-30-evidence-bound-field-mapping.md) partly overlaps: source-bound extraction and conservative abstention remain, while school authority ranking and the user-confirmed study-interval date roles are new decisions. [HR profiles](../feature/2026-10-08-hr-document-field-profile.md) keep removed principal/study-mode fields absent. [Business Excel](../feature/2026-10-09-business-xlsx-layout.md) exports the saved mapping, not raw OCR. Related notes were searched; no complete supersession or archival is warranted.

## Alternatives considered

- Keep all school candidates equally ranked: reliably exposes disagreement, but lets decorative-cover OCR override a clear printed field. Prioritize explicit field context and retain true same-tier conflicts.
- Add only more school aliases: small, but does not fix the unsupported signatory boundary or cover/body ranking. Fix the observed boundaries and authority rule.
- Substitute a complete footer date for graduation: convenient when the interval ends at month precision, but the user explicitly rejects that meaning. Use the printed interval endpoint for graduation and keep footer issuance separate.
- Fill a missing day in a month-only interval: yields uniform full dates, but fabricates unsupported precision. Preserve YYYY-MM.
- Rerun both models on every certificate: can help unreadable source text, but costs inference and cannot repair an already-read field being rejected by the same mapper. Repair/replay rules first.

## Verified invariants

- Frozen Zhao output yields the exact printed school without 院长; Kong yields the labelled body school while preserving cover evidence. Two different explicit school labels remain a conflict.
- O/0/〇 date-context cases, inline footer, spaced Chinese dates, invalid calendar dates, multiple footer candidates and unchanged identifiers pass focused tests.
- The confirmed interval convention is explicit in SPEC/OpenAPI, source and tests. Both endpoints are mapped; a standalone footer never supplies graduation and no day is fabricated from month-only evidence.
- Replay all available frozen certificate samples with separately reported present/absent/uncertain references and unchanged original output hashes. Do not report mapping replay as fresh model accuracy.

## Verification

Six focused diploma tests and the existing certificate regression pass. The original frozen outputs replay as Zhao: 西安交通大学城市学院, 2014-08 / 2018-07 / 2018-07-03; Kong: 岭南师范学院, 2021-09 / 2025-06 / 2025-06-19; Zhang: 河南信息统计职业学院, 2020-10 / 2023-07 / 2023-07-01 (enrollment / graduation / issuance). No new model is called or saved production revision changed. The [replay summary](../../../../output/repairs-20261009-v1/replay/summary.json) preserves the input hash and explicit limitations. All 447 backend tests pass in [verification log](../../../../output/repairs-20261009-v1/backend-verified.log).

## Consequences

Authority ranking can suppress a genuine difference without a printed field context; only observed field/narrative authority is ranked. The user's correction authorizes interval mapping; candidates, original runs and printed precision remain protected. Unreadable or equally authoritative conflicts still require human review, and frozen replay is not fresh model accuracy.

The subsequent [fresh serial accuracy measurement](../testing/2026-10-09-diploma-accuracy-refresh.md) adds actual inference evidence without rewriting this replay: six diplomas65/66, date roles18/18, 0 missing. The remaining school error is already in raw OCR and is not a mapper omission.
