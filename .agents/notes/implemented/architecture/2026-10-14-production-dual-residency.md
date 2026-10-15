# Agent Note: Fix production to dual residency and retain isolated benchmark mode

Status: implemented
Scope: backend/ocr_app, tests, frontend/src, SPEC.md, RUNTIME.md, ARCHITECTURE.md, openapi.yaml, frontend/public/help, start.ps1, README.md
Last-verified: 2026-10-14

## Problem

The user now deploys to a shared machine and explicitly removes single-resident production operation because reloads waste recognition time. Existing launcher preferences and startup resource fallback still permit switching. The interview serial benchmark also reproduced health polling misclassifying an intentional unload as a crash.

## Decision

The application launcher always selects dual_resident, accepts the old explicit dual flag for compatibility, rejects single, and replaces a saved single preference on launch. Load and warm both models sequentially. Failure of one model leaves a visible degraded state and the healthy model resident; never unload it to recover the failed peer. Existing independent FIFO queues and task deadlines remain. No database or account migration is required.

Internal RuntimeConfig single_resident remains only for explicit standalone serial accuracy/resource tests, not as an application option. Serialize health polling with its existing execution lock so deliberate benchmark switching cannot poison model readiness. Preserve failed measurements and rerun.

## Related-note audit

[Lifecycle](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) is partially superseded for production fallback/preferences; ownership, sequential loading and benchmark history remain. [Queues](../../implemented/architecture/2026-10-08-independent-model-queues.md) retain one request per model and serial degraded dispatch. [Interview implementation](../feature/2026-10-14-interview-registration-and-shared-upright.md) depends on accurate serial qualification. No note is wholly superseded or archived. Deployment-branch integration is separate; this change is in the Windows development tree.

## Alternatives considered

- Keep automatic low-memory fallback: offers availability on small PCs, but contradicts the user's new shared-host policy and introduces reload latency.
- Delete internal serial runtime too: less code, but prevents comparison with earlier isolated benchmarks and violates the established benchmark protocol. Keep it unavailable to the normal launcher.
- Reload a failed model while its peer works: may recover transient faults, but risks disrupting healthy work; retain explicit fault reporting and restart recovery.

## Validation

Launcher tests confirm it accepts only dual; legacy saved single cannot select it. Synthetic startup/runtime tests confirm failures keep the surviving model and never trigger peer unload or failed-model reload. Normal dual queues remain independent. Serial benchmark health polling skips intentional unload and still detects genuine idle crashes. Local activation verifies stored accounts and results against the pre-test snapshot.

## Consequences

Both models require memory throughout application uptime. A failed model remains unavailable until restart. Mac deployment needs synchronization and separate validation.

Local1.26.0 activation confirms both models warmed, dual residency active and existing283 tasks/2 accounts unchanged; evidence is recorded in the [interview activation](../feature/2026-10-14-interview-registration-and-shared-upright.md#local-activation). The Mac deployment copy is not changed.
