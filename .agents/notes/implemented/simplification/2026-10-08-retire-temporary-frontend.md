# Agent Note: Retire the temporary frontend for an independent rewrite

Status: implemented
Scope: start.cmd, start.ps1, backend/ocr_app/launcher.py, backend/ocr_app/api.py, RUNTIME.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md, scripts, tests
Last-verified: 2026-10-08
Supersedes: archived/feature/2026-10-08-temporary-recognition-workbench.md

## Problem

The user requests removal of the temporary UI before another agent rebuilds it. No Git snapshot existed at removal time. The old source, tests, manifests, dependencies and dist occupy about92MB; moving that tree preserves recovery at little cost. Startup wrappers formerly required dist even with NoBrowser although the backend supports an absent static directory.

## Decision

The complete old frontend tree is moved inside this workspace to output/frontend-retired-20261008-v1/frontend. Absolute paths and absence of reparse points are checked; all1287 file SHA256 values match before and after. The active frontend directory is absent. This local recovery copy, dependencies and build artifacts are excluded from Git. A later agent can create frontend independently; this change does not choose its framework, contact that agent or remove new files it creates. Original samples, business state, models and earlier measurements remain intact.

Both startup wrappers permit an absent frontend build. The launcher opens a browser only if frontend/dist/index.html exists and NoBrowser is not specified. It still loads the configured recognition models. Without a UI, root responds503 and health/authenticated business APIs remain available. CPU acceptance uses FakeRuntime and isolated storage rather than starting GPU models.

## Retained reconstruction boundaries

The retired same-origin workbench supported authenticated three-type upload, polling, cancellation/rerun and partial results. Its local source comparison used submitted request order and explicit returned task IDs, checked count/identity, kept only the latest batch and revoked object URLs on replacement/logout/unmount. Historical source was never guessed from filenames. Source page selection requested PDF#page; original images did not claim corrected bbox alignment and unsupported HEIC preview had a fallback.

File removal and manual selection/upload navigation were explicit; polling did not steal scroll. Medical name/alias/category search and status filters projected only returned items, keeping local matched/returned counts distinct from unknown full-report stats. Source pages, NEED_REVIEW, null confidence and server-masked numbers were retained. A local original was never represented as an authenticated backend reveal API.

Completed/new executions cleared obsolete cancellation/rerun notices. The API key stayed only in page memory; reads had bounded retries, writes had no automatic retry, and run/revision guards plus safe diagnostic redaction remained. The UI did not implement review editing/export, historical backend preview/reveal, extra document types or remote deployment. These contracts belong to the surviving API, task and diagnostics decisions and remain reconstruction constraints; the retired UI source is historical evidence.

## Decision audit

The temporary-workbench note is fully absorbed and archived by the DDE CLI. Its unique reasons, alternatives, verification gaps and source ownership are retained here. Other runtime, durable-task, diagnostics, mapping and HDR-admission notes remain implemented: their frontend portion is retired and their Scope now covers surviving code. The Mac and HR-field proposals remain proposed.

## Alternatives considered

- Permanently deleting the tree most literally satisfies deletion, but no Git recovery existed. A same-volume move removes active code while preserving all files.
- Leaving framework scaffolding and manifests provides a head start, but constrains the requested independent rewrite and can serve stale dist. Remove the whole active tree.
- Zipping source and deleting dependencies makes a small backup, but adds verification/deletion steps and requires npm ci to restore. Preserve the complete tree with one move.
- Blocking backend startup without dist prevents incomplete UI launch, but also blocks API testing during reconstruction. Keep the APIs available and skip opening a missing webpage.
- Replacing the framework or adding a component library could improve UI consistency. The temporary workbench deferred that investment because the user already planned a separate rewrite; the retirement leaves that choice open.
- Full authenticated preview/reveal supports history and identifiers, but requires artifact permissions, masking and audit contracts. The retired UI used only supplied-file comparison and did not claim those endpoints.
- Keeping every uploaded original supports session history, but grows browser memory. The retired preview kept one batch and clearly described the limit.
- Calling the returned list length full coverage is convenient, but would turn missing evidence into false completeness. Full medical counts and confidence remain unknown until proven.

## Testing

The old workbench had31 frontend tests and a passing TypeScript/build. Final synthetic browser attempt003 covered12 cases with no pageerrors: file removal, identical filenames with explicit task IDs, PNG blob hash/size, page requests, filters, notices, URL cleanup, unsupported preview, no guessed history and no automatic write retry. A390px viewport had no whole-page overflow. These historical checks did not use private materials or a real key, did not qualify OCR/concurrency, and did not independently prove the PDF plugin's final rendered page. The later actual-route HDR acceptance supplemented synthetic admission checks, not accuracy.

Removal preserves1287 hashes (92144546 bytes), and16 existing CPU API tests pass with the UI absent. PowerShell/Python parsing and all four browser-open combinations pass. DDE verify and index --check are delivery gates. Local archive manifest/summary and historical browser reports stay in ignored output; a clean source clone does not contain these local measurements.

## Consequences

There is no active webpage until the replacement is built. Old browser/DOM probes are historical and cannot qualify the new UI. Backend APIs, task storage and diagnostics remain usable. The recoverable tree retains disk space until explicitly removed. Browser PDF/HEIC support and corrected-source alignment require separate verification. Refresh lost the retired UI's local originals/key while backend results persisted; the rebuild must respect its own verified ownership and API contract. Removing frontend files does not stop backend tasks or models.
