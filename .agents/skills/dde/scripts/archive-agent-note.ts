/**
 * CLI tool to archive an implemented Agent Note with frozen manifest sealing.
 * Usage: npx tsx scripts/archive-agent-note.ts .agents/notes/implemented/<class>/<filename>.md [--superseded-by <new-note-path>]
 * --superseded-by writes a relative link into the NEW note, never into the archived file.
 */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { agentNoteRoot, AGENT_NOTE_CLASSES, walkAgentNoteTree } from "./agent-note-tree.ts";

const args = process.argv.slice(2);
const targetArg = args[0];
const supersededByArgIdx = args.indexOf("--superseded-by");
const supersededByArg = supersededByArgIdx !== -1 ? args[supersededByArgIdx + 1] : undefined;
if (supersededByArgIdx !== -1 && !supersededByArg) {
  console.error("Error: --superseded-by requires a note path");
  process.exit(1);
}
if (!targetArg) {
  console.error("Usage: npx tsx scripts/archive-agent-note.ts <path-to-note> [--superseded-by <new-note-path>]");
  process.exit(1);
}

let successorPath: string | undefined;
let successorRel: string | undefined;
if (supersededByArg) {
  successorPath = resolve(process.cwd(), supersededByArg);
  if (!existsSync(successorPath)) {
    console.error(`Error: --superseded-by target not found at ${successorPath}`);
    process.exit(1);
  }
}

const targetPath = resolve(process.cwd(), targetArg);
if (!existsSync(targetPath)) {
  console.error(`Error: target note not found at ${targetPath}`);
  process.exit(1);
}

const relToRoot = relative(agentNoteRoot, targetPath).replace(/\\/g, "/");
const segs = relToRoot.split("/");

if (segs[0] !== "implemented" || segs.length !== 3) {
  console.error(`Error: only notes in .agents/notes/implemented/<class>/ can be archived (got: ${relToRoot})`);
  process.exit(1);
}

const [, cls, filename] = segs;
if (!AGENT_NOTE_CLASSES.includes(cls as any)) {
  console.error(`Error: unknown class "${cls}"`);
  process.exit(1);
}

// 1. Read and update content with Archived line
const raw = readFileSync(targetPath, "utf8");
const lines = raw.split("\n");
const statusIdx = lines.findIndex((l) => l === "Status: implemented");
if (statusIdx === -1) {
  console.error("Error: note must contain `Status: implemented` to be archived");
  process.exit(1);
}

// Local calendar date, not UTC — toISOString() would roll the archived stamp
// back one day for evening runs east of the prime meridian.
const nowLocal = new Date();
const pad2 = (n: number) => String(n).padStart(2, "0");
const today = `${nowLocal.getFullYear()}-${pad2(nowLocal.getMonth() + 1)}-${pad2(nowLocal.getDate())}`;
// DDE 契约：`Archived:` 终止头部元数据块——插在 Status 之后的
// Scope / Supersedes / Last-verified 元数据行（若有）之后、空行之前。
const META_LINE = /^(Scope|Supersedes|Last-verified)\s*[:：]/;
if (!lines.some((l) => l.startsWith("Archived:"))) {
  let insertAt = statusIdx + 1;
  while (insertAt < lines.length && META_LINE.test(lines[insertAt] ?? "")) insertAt++;
  lines.splice(insertAt, 0, `Archived: ${today}`);
}

if (successorPath) {
  const rel = relative(agentNoteRoot, successorPath).replace(/\\/g, "/");
  successorRel = rel;
  const successorSegs = rel.split("/");
  if (successorSegs.length !== 3 || !["proposed", "implemented", "rejected"].includes(successorSegs[0] ?? "")) {
    console.error(`Error: --superseded-by target must be an active note in {lifecycle}/{class}/ (got: ${rel})`);
    process.exit(1);
  }
}

const updatedContent = lines.join("\n");

// 2. Determine archived destination
const archivedDir = join(agentNoteRoot, "archived", cls);
mkdirSync(archivedDir, { recursive: true });
const archivedPath = join(archivedDir, filename);

if (existsSync(archivedPath)) {
  console.error(`Error: target archived note already exists at ${archivedPath}`);
  console.error("Refusing to overwrite existing archived note. Please inspect and resolve name collision manually.");
  process.exit(1);
}

writeFileSync(targetPath, updatedContent, "utf8");
renameSync(targetPath, archivedPath);
console.log(`Moved: ${relToRoot} -> archived/${cls}/${filename}`);

// 3. Update archived/manifest.json with SHA-256 seal
const manifestPath = join(agentNoteRoot, "archived", "manifest.json");
interface Manifest {
  version: 1;
  files: Record<string, string>;
}
let manifest: Manifest = { version: 1, files: {} };
if (existsSync(manifestPath)) {
  try {
    manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch (e) {
    console.warn("Warning: existing manifest.json was invalid, creating fresh");
  }
}

const newArchivedRel = `archived/${cls}/${filename}`;
const sha256 = `sha256:${createHash("sha256").update(readFileSync(archivedPath)).digest("hex")}`;
manifest.files[newArchivedRel] = sha256;

// Deterministic sort keys
const sortedFiles = Object.fromEntries(
  Object.entries(manifest.files).sort(([a], [b]) => a.localeCompare(b))
);
writeFileSync(manifestPath, JSON.stringify({ version: 1, files: sortedFiles }, null, 2) + "\n", "utf8");
console.log(`Sealed in archived/manifest.json with hash ${sha256.slice(0, 16)}...`);

// 4. Scan inbound links in active notes (precise markdown-link resolution)
const { notes } = walkAgentNoteTree();
const inboundFound: string[] = [];
const LINK_REGEX = /\[([^\]]+)\]\(([^)]+)\)/g;
for (const note of notes) {
  const noteFullPath = resolve(agentNoteRoot, note.rel);
  const content = readFileSync(noteFullPath, "utf8");
  let match: RegExpExecArray | null;
  LINK_REGEX.lastIndex = 0;
  while ((match = LINK_REGEX.exec(content)) !== null) {
    const rawTarget = match[2]?.trim();
    if (!rawTarget || rawTarget.startsWith("http://") || rawTarget.startsWith("https://") || rawTarget.startsWith("#") || rawTarget.startsWith("mailto:")) continue;
    const fileTarget = rawTarget.split("#")[0];
    if (!fileTarget) continue;
    // resolve the link relative to the linking note, then compare with the archived note's original location
    const resolvedTarget = resolve(dirname(noteFullPath), fileTarget);
    if (resolvedTarget === targetPath) {
      inboundFound.push(note.rel);
      break;
    }
  }
}

if (inboundFound.length > 0) {
  console.log("\n[Notice] The following active notes link to the archived note:");
  for (const rel of inboundFound) {
    console.log(`  - ${rel}`);
  }
  console.log("Please review and update their relative markdown links if necessary.");
} else {
  console.log("\nNo active notes link to this archived note.");
}

if (successorPath && successorRel) {
  const oldArchivedRel = `archived/${cls}/${filename}`;
  // 1) 吸收完整性报告：旧篇的备选条目数应被新篇覆盖（advisory）
  const countAltItems = (raw: string): number => {
    const altStart = raw.split("\n").findIndex((l) => /^## (?:Alternatives considered|.{0,8}?(?:替代方案|备选方案))\s*$/.test(l));
    if (altStart === -1) return 0;
    const bodyLines = raw.split("\n").slice(altStart + 1);
    let count = 0;
    for (const l of bodyLines) {
      if (/^##\s/.test(l)) break;
      if (/^\s*(?:[-*]\s|#{3,4}\s)/.test(l)) count++;
    }
    return count;
  };
  const newRaw = readFileSync(successorPath, "utf8");
  const oldItems = countAltItems(raw);
  const newItems = countAltItems(newRaw);
  if (newItems < oldItems) {
    console.warn(`\n⚠️ [吸收检查] 旧篇有 ${oldItems} 条备选方案，新篇只有 ${newItems} 条。`);
    console.warn(`   归档契约要求新笔记接管旧篇全部独特理由/备选/后果——请确认差异是有意为之，而不是遗漏搬运。`);
  }

  // 2) 在新笔记头部元数据块写入结构化 Supersedes（机器可读、图谱可画）
  if (!newRaw.includes("Supersedes:")) {
    const succLines = newRaw.split("\n");
    const succStatusIdx = succLines.findIndex((l) => /^Status[:：]/.test(l));
    if (succStatusIdx !== -1) {
      let insertAt = succStatusIdx + 1;
      while (insertAt < succLines.length && META_LINE.test(succLines[insertAt] ?? "")) insertAt++;
      succLines.splice(insertAt, 0, `Supersedes: ${oldArchivedRel}`);
      writeFileSync(successorPath, succLines.join("\n"), "utf8");
      console.log(`Linked from ${successorRel}: Supersedes: ${oldArchivedRel}`);
    } else {
      console.warn(`\n⚠️ ${successorRel} 缺少 Status 行，未写入 Supersedes 元数据。`);
    }
  } else {
    console.log(`Linked from ${successorRel}: 已存在 Supersedes 元数据，未重复写入。`);
  }
}
