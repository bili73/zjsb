# Agent Note: Freeze updated diploma references before fresh serial inference

Status: implemented
Scope: scripts/probe_diploma_accuracy.py, tests/test_diploma_accuracy_protocol.py, IMPLEMENTATION_PLAN.md, RUNTIME.md
Last-verified: 2026-10-09

## Problem

The user requests fresh accuracy after school/date rule repairs. Prior fixed references include three uncertain graduate_date values because graduation formerly excluded study endpoints. Counting a populated field as correct, copying OCR into new answers or comparing different denominators would disguise errors. Three current original diplomas and three historical diploma controls are available; a degree control can detect unrelated regression.

## Decision

Visually inspect original images before inference. Copy historical references into a new encrypted fixture and record study endpoints under the user's approved graduation semantics; preserve printed month precision. Add the three current original diplomas with eleven current fields each, plus the historical degree control. Retain original references and samples untouched, distinguish the old common thirty-nine present-field controls from the expanded new reference set, and label these convenient/rule-development samples as provisional rather than held-out accuracy.

Reuse the isolated current-pipeline real HTTP runner, encrypted data/artifacts and published run/revision scorer. The new wrapper freezes cases, current profiles, source and code hashes before execution. Execute serially in single_resident mode, one request at a time, with startup separate from task and actual inference durations. Default certificate routing, retries and 180-second task budget remain unchanged. Pause only the idle, identity-verified production launcher; check old model-tree exit and release its GPU lock, then restore the dual-resident service when the owned probe has exited. The private probe never uses production task storage.

Public CSVs expose anonymous sample IDs, field keys/outcomes, durations, attempts, terminations and resource metrics, not material values. Freeze answers before model output exists; failed cases retain their planned denominators and unrun cases are labelled, not silently omitted. Preserve truncated/failed runs and all earlier outputs. A separate CPU-native institution check covers three first-page source lines; it is not mixed into fresh certificate model accuracy or whole-medical accuracy.

## Decision audit

- [Current pipeline acceptance](../../implemented/testing/2026-10-08-current-pipeline-acceptance.md): partial overlap; reuse its isolated server/process/scorer, retain its historical seven/nine-case denominators and residency conditions.
- [Diploma rule repair](../../implemented/bug-fix/2026-10-09-diploma-school-and-date-mapping.md): retain interval-end graduation, issuance separation and authority/conflict rules; this experiment adds fresh inference evidence.
- [Paired certificate diagnostic](../../implemented/testing/2026-09-30-dual-certificate-extraction.md): keep historical two-model paths and references separate; this tests the current application's certificate path.
- [Cover institution](../../implemented/bug-fix/2026-10-09-medical-cover-institution.md): independently owns the source-location mapper. No note is wholly superseded or archived.

## Alternatives considered

- Reuse frozen OCR only: inexpensive and isolates mapper changes, but the user explicitly requests a new measurement of recognition behavior.
- Keep the old uncertain dates unscored everywhere: most comparable to the old report, but fails to test the new study-interval rule. Keep a common-reference comparison and a separately expanded score.
- Call the live dual-resident service: convenient and closest to user operation, but violates standalone single-resident benchmark constraints and writes production tasks.
- Score the same image through both independent models: helps model comparison, but the user's current question is the repaired certificate application path; no routing/fusion change is requested.

## Verified invariants

New encrypted references are frozen before inference, old artifacts/samples are unchanged, all six diploma controls and the degree control keep their planned present/absent/uncertain denominators, and actual published snapshots provide scores. Public outputs separate full-field, diploma-only, date-role, old-common-control and native-institution results. Startup/task/model times are distinct and fresh GPU calls are identified. Owned inference processes exit, production storage remains unchanged and the normal local service is restored. Protocol/scorer and relevant backend regression tests plus DDE verify pass.

## Consequences

Agent visual labels are provisional and not independently double-reviewed. Samples overlap rule-development material and do not estimate general production accuracy or Mac performance. Single-resident fallback loading can consume the task budget; retain those outcomes rather than changing budgets mid-run.

Reusing the existing runner avoids a parallel benchmark framework while adding independently frozen references and comparable old controls. Maintaining two denominators and encrypted fixtures adds bookkeeping; it prevents semantic improvements from being mistaken for evidence on previously unscored fields. Confidence remains uncalibrated and every result is NEED_REVIEW.

## Verification

The v3 isolated single-resident run measures all seven planned cases through real HTTP/published snapshots: diplomas 65/66, 0 missing and 1 school error; date roles 18/18; degree 9/9 plus one correct absence; expanded total 74/75. Old common present39 becomes 38/39 versus 37/39: the degree award_date is now read and the same diploma school error persists. Raw OCR itself says 西安学院 where the frozen original says 西京学院. Do not guess a correction or attribute the full common-score difference to rules.

Seven GLM actual EOS calls, zero cache hits/retries/fallbacks/truncations/timeouts, original checkpoint revision unchanged. Diploma upload-to-result mean 5.560 seconds; session startup 26.329 seconds is separate. Current Windows RTX3060 12GB/31.81GiB RAM conditions do not qualify Mac or generalized throughput. Source/code/reference hashes match at run completion, and all thirty observed owned process handles are signaled.

Preparation v1 (incorrect Storage method) and startup v2 (old server protocol discriminator) fail before any model call and remain preserved. The wrapper now uses Storage.put, a separate fixture vault and the required current_pipeline_acceptance discriminator plus an explicit experiment subtype. Unrun cases remain not_run with no accuracy value; they are not silently excluded or scored as model zeroes. v3 copied the same pre-inference answers after those infrastructure corrections.

Two reference-contract tests and all 469 backend tests pass. The normal dual service is restored as 1.16.1 with GLM/Paddle ready; original 52 task ciphertexts, account and key hashes remain unchanged. [Report](../../../../output/accuracy-20261009-v1/REPORT.md), [chart CSV](../../../../output/accuracy-20261009-v1/chart_data.csv), [frozen v3 protocol](../../../../output/diploma-accuracy-20261009-v3/protocol.json), [completion](../../../../output/diploma-accuracy-20261009-v3/summary.json) and [restore check](../../../../output/accuracy-20261009-v1/service/after.json) retain the evidence. No frontend behavior, certificate routing, budget, model revision or production queue changes belong to this experiment.
