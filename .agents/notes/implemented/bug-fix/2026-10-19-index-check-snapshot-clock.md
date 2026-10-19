# Agent Note: Compare note indexes at their recorded snapshot time

Status: implemented
Scope: scripts/agent-index.ts, scripts/tests, package.json
Last-verified: 2026-10-19

## Problem

An unchanged index generated on October18 fails index --check on October19. Rebuilding at the saved generatedAt yields no difference; a current-time build changes only generatedAt and24 freshness.monthsSinceVerify values. Freshness state/rule and stats.staleNotes also change when time crosses the six-month threshold. These are elapsed-time changes rather than unsynchronized source documents.

## Decision

For --check, validate the saved generatedAt and rebuild the current source tree at that timestamp. Compare every indexed property as before, including freshness, dates, hashes, relations and anchors. Malformed JSON or missing/invalid generatedAt fails with a regeneration instruction. Generating an index and live queries continue using the current time, so current stale-note warnings remain available; --check verifies snapshot/source consistency rather than current age. Keep the index schema and all notes unchanged by checks. Add isolated Node built-in tests run through existing tsx; no application dependency or runtime change.

## Related decisions

The [project DDE workflow](../../implemented/process/2026-09-29-dde-project-workflow.md) owns the copied tooling. This is a narrow local fix to its upstream script copy; the installed Skill template and license remain intact, and future upstream sync must retain or replace this regression coverage. The [contract documentation sync](../../implemented/process/2026-10-18-contract-doc-header-sync.md) remains responsible for the separate authorized wording corrections. Other scope-query hits govern OCR features and do not determine index consistency.

## Alternatives considered

- Ignoring all freshness fields is easy and avoids clock dependence, but also stops detecting corruption of snapshot freshness metadata. Rebuilding at the recorded time preserves those comparisons.
- Rebuilding and committing daily avoids changing tooling, but produces source-free churn and cannot keep CI stable across time thresholds.
- Removing freshness entirely reduces derived fields, but weakens live discovery and changes the index format unnecessarily.

## Testing

The regression suite first reproduces two failures with the original script: elapsed-day freshness rounding and a fresh snapshot crossing the stale threshold. After the fix, npm run test:notes passes8 isolated tests covering both cases without snapshot writes, note content/Last-verified changes, membership changes, links, corrupt freshness, malformed JSON and invalid/missing generatedAt. Generation and live buildIndex calls still report current staleness. Tests use a temporary AGENT_NOTE_ROOT below the repository's ignored tmp directory and Node builtins through the existing tsx command; no live business data or models are used.

Independent read-only review finds no blocking defect and reruns all8 tests successfully. The tested host uses Node24.21.0; Node18 remains the compatibility target but was not separately executed. The installed Skill template and business source remain unchanged.

## Consequences

Snapshot freshness describes generatedAt, not today's assessment; consumers must read the existing snapshot disclaimer or use a live query. Local changes mean the repository script is no longer byte-identical to the installed upstream template; document this boundary rather than silently overwriting either copy.
