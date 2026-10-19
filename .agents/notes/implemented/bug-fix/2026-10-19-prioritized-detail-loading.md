# Agent Note: Prioritize detail images and avoid redundant durable progress

Status: implemented
Scope: frontend/src/components/SourcePreview.vue, frontend/src/components/TaskResultDrawer.vue, backend/ocr_app/task_store.py, frontend/tests, tests, ARCHITECTURE.md, RUNTIME.md
Last-verified: 2026-10-19

## Problem

The user prioritizes loading speed. SourcePreview starts every intersecting page immediately, with a150percent browser-root margin and no concurrency bound; queued background pages can compete with the selected page and other APIs. Completed controllers remain in its map. Separate open/task-key watchers can start duplicate result reads in the same Vue update. The pipeline also publishes identical OCR checkpoints before/after neighboring regions; TaskStore.progress encrypts and updates them again, forcing avoidable durable commits on the measured mechanical disk.

## Decision

Active preview requests are limited to two per mounted component, same-page callers share a promise, and explicit location/jump requests precede pending background pages. The observer uses the actual scroll viewport and75percent margin after mount and responsive size changes. An overflow:auto column that grows to content height is not a viewport: the nearest bounded scrolling ancestor is selected. Queued background pages leaving that viewport are dropped. Version/account/API/permission/close/unmount changes cancel pending and active work; stale results cannot create URLs or overwrite newer entries. Smooth single-click location, manual retry and existing full-image pixels remain.

Open/task-key result watchers coalesce into one update without discarding dirty drafts or bypassing stale-result protection. Save/export contracts are unchanged. Only identical progress writes are suppressed after the existing run/cancel/stop guards: same stage, bounded percentage and full page snapshot. A changed page/status still persists even if percentage stays equal. Schema, retention, auth, fsync, task-budget and production model concurrency are unchanged.

## Related decisions

[Preview renditions](../feature/2026-10-19-preview-renditions.md) partially changes the full-pixel list choice to a bounded display image, retaining original pixels for explicit enlargement and region OCR. Its separate original request is cancellable; the two-request queue remains the background-page bound.

[Read amplification](../../implemented/bug-fix/2026-10-19-batch-read-amplification.md) removes unnecessary history polling. [Preview/diagnostic repair](../../implemented/bug-fix/2026-10-19-preview-and-diagnostic-read-cost.md) shortens actual writer holds. [Smooth location](../../implemented/bug-fix/2026-10-18-source-preview-scroll-performance.md) keeps visual navigation behavior. [Measured progress](../../implemented/bug-fix/2026-10-10-measured-task-progress.md) still owns counters and checkpoints; identical snapshots are not a separate heartbeat contract. No decision is completely superseded.

## Alternatives considered

- More HTTP workers would accept more simultaneous image/SQLite work but leave redundant reads/writes and selected-page starvation.
- A cross-user image cache could avoid encoding but adds authorization/version/privacy invalidation; keep component-local loaded images and server authorization per request.
- Time-based progress throttling reduces more writes but can drop real page/region changes on failure. Skip only exact duplicates.

## Testing

Actual Vue setup tests bound pending previews, prioritize explicit pages, coalesce same-page requests, reject late versions after reset/unmount and preserve smooth location after image completion. Responsive viewport selection excludes an unbounded tall column. A simultaneous drawer open/task update requests the result once and dirty drafts remain protected. All254 frontend tests, typecheck and isolated production build pass. Store regressions reproduce6 identical UPDATEs before the fix versus1 after, while changed page/stage checkpoints persist and cancelled/stale runs remain rejected. Focused backend runs pass70 pipeline/store tests and32 authorization/contention/probe tests.

The final combined backend run passes115 tests in63.072s, including summary reads and diagnostic recovery; its log is retained beside the254-test frontend and4-test Paddle CPU logs in output/cuda-isolation-20261019-103529. Final authenticated health reports dual models ready and queue0, then logout succeeds and anonymous business access is401.

Actual narrow-window browser checks expose the initial style-only viewport mistake: a21-page report eventually loads all21 images. The corrected bounded viewport initially loads1 image; after bringing the field into view, its first location click loads page4, scrolls smoothly and displays its red bbox in the viewport. Locator auto-scroll from an offscreen button is not treated as a human click acceptance test. The latest build's16 served files match their hashes; assets are staged and index switched last without restarting ready models. No business field is edited or saved by the browser check. Evidence and interface timings are retained in output/cuda-isolation-20261019-103529 and output/windows-request-profile-20261019-104845.

## Consequences

Two active background images can still briefly delay a selection; aborting a fetch cannot guarantee that a server-side operation has stopped. The limit applies to active client requests, not a global API worker budget. Removing duplicate writes reduces no-op updated_at changes, while actual task-stage/page changes remain durable.

Smooth scrolling through a long report can load pages along its path; the guarantee is bounded active requests and viewport-based loading, not a fixed total cache of one page. The first selected uncached page still needs one request and decode. Cold diagnostic scans and full-resolution image encoding remain measurable costs; these changes do not promise a universal response deadline or change storage durability.
