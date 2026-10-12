# Agent Note: Identity-card front-only recognition with an optional back

Status: implemented
Scope: backend/ocr_app/task_store.py, frontend/src/business.ts, tests/test_person_packages.py, frontend/tests/person-packages.test.ts, SPEC.md, openapi.yaml, FRONTEND_FIELDS.md, RUNTIME.md, frontend/public/help/index.html
Last-verified: 2026-10-12

## Problem

The user explicitly requires recognizing only the identity-card portrait side. The missing-back warning in the newly implemented person package suggests a mandatory document despite existing independent front-side extraction and export rules.

## Decision

Treat the back as an optional material. Preserve independent ID_CARD_FRONT tasks and their own required fields; no back upload is needed for completion or export. Keep missing_back as a compatible presence state but display 国徽面未上传（可选，可仅识别人像面） and emit no MISSING_ID_BACK warning. If supplied, the back is a separate task using its own existing field requirements. Back-only and both-present states retain their original-comparison guidance. Do not combine issuer/validity fields into the front profile.

## Decision audit

This partially overrides the mandatory-looking front-only warning in [person packages](../../implemented/feature/2026-10-12-person-material-packages.md), while retaining package attribution, append versions, expiry, independent tasks and the presence-only pairing boundary. No older note is wholly superseded.

## Alternatives considered

- Require both sides: gives more complete issuing and validity information, but conflicts with the approved front-only workflow and adds unnecessary collection.
- Merge both sides into one task/profile: presents one combined card result, but makes optional back fields and independent file evidence more complex without meeting any additional requested behavior.

## Verification

The previous warning reproduces in two failing tests before the change. All615 backend tests and115 frontend tests pass, including a synthetic front-only package with filled front fields, no back task, no missing-back warning and a successful XLSX without issuer/validity columns. Typecheck and production build pass.

An isolated browser displays 国徽面未上传（可选，可仅识别人像面）, enables export when front fields are filled and downloads the front-only XLSX successfully. Console has no warning/error. Evidence is retained in output/pm-remediation-20261012-v1/, including optional-id-back-browser.png. Synthetic fixture values are not model accuracy measurements.

## Consequences

Front-only processing needs no back-side collection. Optional absence does not establish document validity or authenticity. Uploaded back-task fields still follow the administrator's per-type configuration when that task is selected for export. Existing pairing enum values remain compatible.
