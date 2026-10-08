/**
 * Verify frozen archived Agent Notes: exact head layout, manifest.json seals,
 * append-only extension vs a git baseline (skipped gracefully without git).
 * Usage:
 *   npx tsx scripts/verify-archived-agent-notes.ts          # verify only
 *   npx tsx scripts/verify-archived-agent-notes.ts --write  # verify, then seal unsealed files
 * Env: AGENT_NOTE_ARCHIVE_BASE_REF (default HEAD) — git ref the manifest is compared against.
 */
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { agentNoteRoot } from "./agent-note-tree.ts";

const isWrite = process.argv.includes("--write");
const errors: string[] = [];
const warnings: string[] = [];
const fail = (msg: string) => { errors.push(msg); };

// --- collect archived files (skip accidental .zh.md)
const archivedDir = join(agentNoteRoot, "archived");
const files: string[] = [];
function scan(dir: string) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith(".")) continue;
    const full = join(dir, entry.name);
    if (entry.isDirectory()) scan(full);
    else if (entry.isFile() && entry.name.endsWith(".md") && !entry.name.endsWith(".zh.md")) {
      files.push(relative(archivedDir, full).split("\\").join("/"));
    }
  }
}
if (existsSync(archivedDir)) scan(archivedDir);

// --- head layout: L1 title / L2 blank / L3 Status / L4.. metadata block
//     (Scope / Supersedes / Last-verified optional; exactly one Archived line
//     anywhere in the block) / blank line after the block.
const TITLE_RE = /^# Agent Note[:：] ?\S/;
const ARCHIVED_RE = /^Archived: \d{4}-\d{2}-\d{2}$/;
const ARCHIVED_META_RE = /^(Scope: .+|Supersedes: .+|Last-verified: \d{4}-\d{2}-\d{2})$/;
for (const rel of files) {
  const lines = readFileSync(join(archivedDir, rel), "utf8").replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n").split("\n");
  const fail2 = (msg: string) => fail(`${rel} — ${msg}`);
  if (!TITLE_RE.test(lines[0] ?? "")) fail2("line 1 must be `# Agent Note: <title>`");
  if (lines[1] !== "") fail2("line 2 must be blank");
  if (lines[2] !== "Status: implemented") fail2("line 3 must be `Status: implemented`");

  let i = 3;
  let archivedSeen = false;
  while (i < lines.length && lines[i] !== "") {
    const l = lines[i];
    if (ARCHIVED_RE.test(l)) {
      if (archivedSeen) fail2(`line ${i + 1}: duplicate Archived line`);
      archivedSeen = true;
    } else if (!ARCHIVED_META_RE.test(l)) {
      fail2(`line ${i + 1}: expected \`Archived:\`, optional Scope/Supersedes/Last-verified, or blank (got ${JSON.stringify(l)})`);
    }
    i++;
  }
  if (!archivedSeen) fail2("metadata block must contain `Archived: YYYY-MM-DD` below Status");
  if (lines[i] !== "") fail2("metadata block must end with a blank line before the body");
}

// --- manifest seals
const manifestPath = join(archivedDir, "manifest.json");
interface Manifest { version: 1; files: Record<string, string>; }
let manifest: Manifest = { version: 1, files: {} };
if (existsSync(manifestPath)) {
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch {
    fail("archived/manifest.json exists but is not valid JSON");
  }
} else if (files.length > 0 && !isWrite) {
  fail("archived/manifest.json missing — run with --write to seal existing archived notes");
}

const sealOf = (relFromRoot: string) =>
  `sha256:${createHash("sha256").update(readFileSync(join(agentNoteRoot, relFromRoot))).digest("hex")}`;

for (const rel of files) {
  const key = `archived/${rel}`;
  const entry = manifest.files[key];
  if (!entry) {
    if (isWrite) {
      manifest.files[key] = sealOf(key);
    } else {
      fail(`${key} — missing seal in manifest.json (run with --write)`);
    }
  } else if (entry !== sealOf(key)) {
    fail(`${key} — seal mismatch: archived note was modified after sealing (frozen notes must never change)`);
  }
}
for (const key of Object.keys(manifest.files)) {
  if (!existsSync(join(agentNoteRoot, key))) fail(`${key} — sealed entry has no file on disk`);
}

// --- append-only vs git baseline (skipped without git)
// Windows: execFileSync does not resolve PATHEXT, so plain "git" can ENOENT
// even when git is installed; probe "git" then "git.exe" once.
const gitBin = (() => {
  for (const bin of process.platform === "win32" ? ["git.exe", "git"] : ["git"]) {
    try {
      execFileSync(bin, ["--version"], { encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] });
      return bin;
    } catch {
      // try next
    }
  }
  return null;
})();
const repoRoot = (() => {
  if (!gitBin) return null;
  // agentNoteRoot may not exist yet (notes not adopted); rev-parse from a missing cwd fails
  const gitCwd = existsSync(agentNoteRoot) ? agentNoteRoot : process.cwd();
  try {
    return execFileSync(gitBin, ["rev-parse", "--show-toplevel"], { cwd: gitCwd, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }).trim();
  } catch {
    return null;
  }
})();
if (repoRoot) {
  const baseRef = process.env.AGENT_NOTE_ARCHIVE_BASE_REF || "HEAD";
  const manifestRel = relative(repoRoot, manifestPath).split("\\").join("/");
  let baselineRaw: string | null = null;
  try {
    baselineRaw = execFileSync(gitBin, ["show", `${baseRef}:${manifestRel}`], { cwd: repoRoot, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] });
  } catch {
    // manifest absent at baseline — nothing to compare
  }
  if (baselineRaw !== null) {
    try {
      const baseline = JSON.parse(baselineRaw) as Manifest;
      for (const [key, seal] of Object.entries(baseline.files ?? {})) {
        if (manifest.files[key] !== seal) {
          fail(`${key} — seal added/changed/removed relative to ${baseRef}; archived seals are append-only`);
        }
      }
    } catch {
      fail(`archived/manifest.json at ${baseRef} was not valid JSON`);
    }
  }
} else {
  warnings.push("not a git repository — append-only check skipped (seal hashes still verified against disk)");
}

if (errors.length) {
  for (const e of errors) console.error(`archived: ${e}`);
  process.exit(1);
}

if (isWrite) {
  const sorted = Object.fromEntries(Object.entries(manifest.files).sort(([a], [b]) => a.localeCompare(b)));
  writeFileSync(manifestPath, JSON.stringify({ version: 1, files: sorted }, null, 2) + "\n", "utf8");
}

for (const w of warnings) console.warn(`warning: ${w}`);
console.log(`ok: ${files.length} archived note(s) verified, ${Object.keys(manifest.files).length} seal(s) in manifest`);
