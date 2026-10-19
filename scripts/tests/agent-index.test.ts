import assert from 'node:assert/strict';
import { after, beforeEach, test } from 'node:test';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join, resolve, sep } from 'node:path';

const tempParent = resolve('tmp');
mkdirSync(tempParent, { recursive: true });
const fixture = mkdtempSync(join(tempParent, 'agent-index-test-'));
const noteRoot = join(fixture, '.agents', 'notes');
const notesDir = join(noteRoot, 'implemented', 'process');
mkdirSync(notesDir, { recursive: true });
const originalNoteRoot = process.env.AGENT_NOTE_ROOT;
process.env.AGENT_NOTE_ROOT = noteRoot;
const { buildIndex, runIndex } = await import('../agent-index.ts');
const notePath = join(notesDir, '2024-01-01-example.md');
const indexPath = join(fixture, '.agents', 'index.json');
const oldTime = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000);
const verified = oldTime.toISOString().slice(0, 10);
const note = `# Agent Note: Example\n\nStatus: implemented\nScope: scripts\nLast-verified: ${verified}\n\n## Decision\n\nUse the original choice.\n`;

function snapshot(now = oldTime) {
  const value = buildIndex({ now });
  writeFileSync(indexPath, JSON.stringify(value, null, 2) + '\n');
  return value;
}

beforeEach(() => { writeFileSync(notePath, note); snapshot(); });
after(() => {
  if (originalNoteRoot === undefined) delete process.env.AGENT_NOTE_ROOT;
  else process.env.AGENT_NOTE_ROOT = originalNoteRoot;
  assert.ok(resolve(fixture).startsWith(tempParent + sep + 'agent-index-test-'));
  rmSync(fixture, { recursive: true, force: true });
});

test('unchanged source passes across the stale threshold without rewriting its snapshot', () => {
  const saved = readFileSync(indexPath, 'utf8');
  assert.equal(JSON.parse(saved).notes[0].freshness.state, 'fresh');
  assert.equal(buildIndex().notes[0].freshness.state, 'stale');
  assert.equal(runIndex(['--check']), 0);
  assert.equal(readFileSync(indexPath, 'utf8'), saved);
});

test('elapsed days do not produce freshness-number drift', () => {
  const earlier = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000);
  writeFileSync(notePath, note.replace(verified, earlier.toISOString().slice(0, 10)));
  const saved = snapshot(earlier);
  assert.notEqual(saved.notes[0].freshness.monthsSinceVerify, buildIndex().notes[0].freshness.monthsSinceVerify);
  assert.equal(runIndex(['--check']), 0);
});

test('source content and verification date changes still fail', () => {
  for (const changed of [note.replace('original choice', 'new choice'), note.replace(verified, '2024-01-02')]) {
    writeFileSync(notePath, changed);
    assert.equal(runIndex(['--check']), 1);
  }
});

test('added and removed notes still fail', () => {
  const additional = join(notesDir, '2024-01-02-additional.md');
  try {
    writeFileSync(additional, note);
    assert.equal(runIndex(['--check']), 1);
  } finally { rmSync(additional); }
  rmSync(notePath);
  assert.equal(runIndex(['--check']), 1);
});

test('corrupt snapshot freshness is not ignored', () => {
  const value = snapshot();
  value.notes[0].freshness.state = 'stale';
  writeFileSync(indexPath, JSON.stringify(value, null, 2) + '\n');
  assert.equal(runIndex(['--check']), 1);
});

test('changed links still invalidate the snapshot', () => {
  const target = join(notesDir, '2024-01-02-target.md');
  try {
    writeFileSync(target, note);
    snapshot();
    writeFileSync(notePath, note + '\n[Target](2024-01-02-target.md)\n');
    assert.equal(buildIndex().relations.length, 1);
    assert.equal(runIndex(['--check']), 1);
  } finally { rmSync(target); }
});

test('malformed JSON and missing or invalid snapshot times fail cleanly', () => {
  for (const invalid of ['{', '{}', '{"generatedAt":null}', '{"generatedAt":0}', '{"generatedAt":"invalid"}']) {
    writeFileSync(indexPath, invalid);
    assert.equal(runIndex(['--check']), 1);
    assert.equal(readFileSync(indexPath, 'utf8'), invalid);
  }
});

test('generation and live queries keep current freshness', () => {
  const before = Date.now();
  assert.equal(runIndex([]), 0);
  const saved = JSON.parse(readFileSync(indexPath, 'utf8'));
  assert.ok(Date.parse(saved.generatedAt) >= before);
  assert.equal(saved.notes[0].freshness.state, 'stale');
  assert.deepEqual(saved.stats.staleNotes, [saved.notes[0].id]);
  assert.equal(runIndex(['--check']), 0);
});
