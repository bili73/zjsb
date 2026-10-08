/**
 * Verify module docs (docs/modules/*.md) — the "职责分明" gate.
 *
 * Rules (see references/module-wiki.md):
 *   1. First non-empty line is an H1 (`# Module: 名称` preferred).
 *   2. Exactly one `Scope:` line with at least one repo-relative path; every
 *      path must exist on disk (module docs must not rot away from code).
 *   3. Module docs must NOT carry decision sections (## Problem / ## Decision /
 *      ## Alternatives / ## Consequences) — the why belongs to Agent Notes.
 *   4. No two module docs may declare overlapping Scope (single-writer rule:
 *      one area of the codebase is narrated by exactly one module doc).
 *
 * Absence of docs/modules is not an error — the convention is opt-in.
 * Run: npx tsx scripts/verify-module-docs.ts   (or: notes.ts verify)
 */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { agentNoteRoot } from "./agent-note-tree.ts";

// 仓库根 = .agents/notes 的上两级（notes → .agents → repo root）
const repoRoot = resolve(agentNoteRoot, "..", "..");
const modulesDir = join(repoRoot, "docs", "modules");

const errors: string[] = [];
const fail = (msg: string) => errors.push(msg);

interface ModuleDoc {
  file: string;
  scope: string[];
}

if (!existsSync(modulesDir)) {
  console.log("ok: no docs/modules directory — module wiki convention not adopted (opt-in)");
} else {
  const docs: ModuleDoc[] = [];
  const entries = readdirSync(modulesDir, { withFileTypes: true })
    .filter((e) => e.isFile() && e.name.endsWith(".md") && !e.name.startsWith("."));

  if (!entries.length) {
    console.log("ok: docs/modules exists but is empty");
  } else {
    for (const entry of entries) {
      const rel = `docs/modules/${entry.name}`;
      const raw = readFileSync(join(modulesDir, entry.name), "utf8").replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
      const lines = raw.split("\n");

      // 1. H1 required
      const firstContent = lines.find((l) => l.trim() !== "") ?? "";
      if (!/^#\s+\S/.test(firstContent)) {
        fail(`${rel} — first non-empty line must be an H1 heading (preferred: "# Module: <名称>")`);
      }

      // 2. Scope line: exactly one, paths must exist
      const scopeLines = lines.filter((l) => /^Scope\s*[:：]/.test(l));
      if (scopeLines.length === 0) {
        fail(`${rel} — missing "Scope: <路径>" line (module docs must declare the code they narrate)`);
      } else {
        if (scopeLines.length > 1) fail(`${rel} — multiple Scope lines; merge into one comma-separated line`);
        const value = scopeLines[0].replace(/^Scope\s*[:：]\s*/, "");
        const paths = value.split(/[,，]/).map((s) => s.trim().replace(/\/+$/, "")).filter(Boolean);
        if (!paths.length) fail(`${rel} — Scope line has no paths`);
        for (const p of paths) {
          if (/^([a-zA-Z]:|\/|\\)/.test(p) || p.includes("..")) {
            fail(`${rel} — Scope "${p}" must be repo-relative (no absolute paths, no ..)`);
            continue;
          }
          const phys = p.replace(/\/\*\*$/, "");
          if (!existsSync(join(repoRoot, phys))) {
            fail(`${rel} — Scope "${p}" does not exist under ${repoRoot}`);
          }
        }
        docs.push({ file: rel, scope: paths });
      }

      // 3. 决策内容属于笔记，不属于模块文档（职责分明）
      const banned = /^##\s+(Problem|Decision|Alternatives considered|Consequences|Proposal|问题|决策|决定|提议|提案|方案|备选方案|替代方案|后果|影响|结果)\b/;
      const inFence = { on: false };
      lines.forEach((l, idx) => {
        if (/^\s{0,3}```/.test(l)) { inFence.on = !inFence.on; return; }
        if (inFence.on) return;
        if (banned.test(l)) {
          fail(`${rel}:${idx + 1} — module docs must not contain decision section "${l.trim()}"（"为什么/放弃了什么"属于 .agents/notes/，模块文档只写"是什么/边界在哪"）`);
        }
      });
    }

    // 4. Scope 互斥：同一片代码只允许一份模块文档叙述
    const phys = (p: string) => p.replace(/\/\*\*$/, "").replace(/\/+$/, "");
    for (let i = 0; i < docs.length; i++) {
      for (let j = i + 1; j < docs.length; j++) {
        const a = docs[i]!;
        const b = docs[j]!;
        const overlap = a.scope.some((sa) => b.scope.some((sb) => {
          const x = phys(sa);
          const y = phys(sb);
          return x === y || x.startsWith(y + "/") || y.startsWith(x + "/");
        }));
        if (overlap) {
          fail(`${a.file} × ${b.file} — Scope 重叠管辖。模块文档职责必须互斥：一片代码只有一份文档叙述，否则后期维护必然出现冲突与漂移`);
        }
      }
    }

    if (errors.length) {
      for (const e of errors) console.error(`module-docs: ${e}`);
      process.exit(1);
    }
    console.log(`ok: ${docs.length} module doc(s) verified (scope exists, no decision sections, no overlap)`);
  }
}
