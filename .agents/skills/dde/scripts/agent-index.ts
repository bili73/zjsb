/**
 * Agent 资产索引：把笔记库 + 模块文档编译成一个机器可读的知识地图
 * `.agents/index.json`，供 AI Agent 检索项目资产与关系，避免每次重新扫描
 * 全库分析（省 token、省时间）。
 *
 *   npx tsx scripts/notes.ts index            # 生成/刷新 .agents/index.json
 *   npx tsx scripts/notes.ts index --check    # CI 门禁：索引与笔记库是否同步
 *
 * 设计约束（务必保持）：
 *   1. 索引是派生快照，不是事实源——每条记录都带 source.path 与行号锚点，
 *      Agent 按锚点回读源文件即可核对或同步更新，绝不允许"只信索引"。
 *   2. 全部路径为仓库相对路径，跨机器稳定。
 *   3. 本模块是库：不读 process.argv，由 notes.ts 调度（安全扫描边界）。
 */
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, relative, resolve } from "node:path";
import { agentNoteRoot, walkAgentNoteTree } from "./agent-note-tree.ts";

const STALE_MONTHS = 6;
const META_LINE_KEYS = ["Scope", "Supersedes", "Last-verified", "Archived"];

interface LineAnchor {
  title: number;
  status: number;
  scope: number[];
  supersedes: number | null;
  lastVerified: number | null;
  archived: number | null;
  sections: { title: string; line: number }[];
}

interface RawNote {
  id: string;
  repoPath: string;
  lifecycle: string;
  cls: string;
  title: string;
  date: string;
  scope: string[];
  supersedes: string;
  lastVerified: string;
  archivedDate: string;
  summary: string;
  raw: string;
  lines: LineAnchor;
  outHrefs: string[];
}

function toRepoPath(fullPath: string): string {
  const repoRoot = resolve(agentNoteRoot, "..", "..");
  return relative(repoRoot, fullPath).split("\\").join("/");
}

function parseNote(raw: string, id: string, repoPath: string, lifecycle: string, cls: string, date: string): RawNote {
  const lines = raw.split(/\r?\n/);

  // 标题
  let title = id.split("/").pop()!.replace(/\.md$/, "");
  const titleLine = lines.findIndex((l) => /^# Agent Note/.test(l));
  if (titleLine !== -1) {
    const t = lines[titleLine].replace(/^# Agent Note[^:：]*[:：]\s*/, "").trim();
    if (t) title = t;
  }

  // 状态行（约定第 3 行）
  const statusLine = lines.findIndex((l, i) => i >= 1 && /^Status\s*[:：]/.test(l));

  // 元数据块：Status 行之后到首个空行
  const metaLines: number[] = [];
  if (statusLine !== -1) {
    for (let i = statusLine + 1; i < lines.length; i++) {
      if (!lines[i].trim()) break;
      if (META_LINE_KEYS.some((k) => lines[i].startsWith(k + ":") || lines[i].startsWith(k + "："))) metaLines.push(i);
      else break;
    }
  }
  const scope: string[] = [];
  let supersedes = "";
  let lastVerified = "";
  let archivedDate = "";
  let supersedesLine: number | null = null;
  let lastVerifiedLine: number | null = null;
  let archivedLine: number | null = null;
  for (const i of metaLines) {
    const l = lines[i];
    if (l.startsWith("Scope:")) {
      scope.push(...l.slice(6).trim().split(/[,，]/).map((x) => x.trim()).filter(Boolean));
    } else if (l.startsWith("Supersedes:")) {
      supersedes = l.slice(11).trim();
      supersedesLine = i + 1;
    } else if (l.startsWith("Last-verified:")) {
      lastVerified = l.slice(14).trim();
      lastVerifiedLine = i + 1;
    } else if (l.startsWith("Archived:")) {
      archivedDate = l.slice(9).trim();
      archivedLine = i + 1;
    }
  }

  // 小节起始行号
  const sections: { title: string; line: number }[] = [];
  lines.forEach((l, i) => {
    const m = l.match(/^##\s+(.+?)\s*$/);
    if (m) sections.push({ title: m[1].trim(), line: i + 1 });
  });

  // 摘要：Decision/决策 首个段落
  let summary = "";
  const decIdx = sections.findIndex((s) => /^(Decision|决策|Proposal|提案)/.test(s.title));
  if (decIdx !== -1) {
    const start = sections[decIdx].line;
    const end = decIdx + 1 < sections.length ? sections[decIdx + 1].line : lines.length + 1;
    const body = lines.slice(start, end - 1).join("\n").trim();
    summary = body
      .split(/\n\s*\n/)[0]
      .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
      .replace(/[#>*`]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 240);
  }

  // 正文出链
  const outHrefs: string[] = [];
  for (const m of raw.matchAll(/\]\(([^)]+\.md)\)/g)) {
    const href = m[1].split("#")[0].trim();
    if (href && !href.includes("://")) outHrefs.push(href);
  }

  return {
    id,
    repoPath,
    lifecycle,
    cls,
    title,
    date,
    scope,
    supersedes,
    lastVerified,
    archivedDate,
    summary,
    raw,
    lines: {
      title: titleLine !== -1 ? titleLine + 1 : 1,
      status: statusLine !== -1 ? statusLine + 1 : null as unknown as number,
      scope: metaLines.filter((i) => lines[i].startsWith("Scope:")).map((i) => i + 1),
      supersedes: supersedesLine,
      lastVerified: lastVerifiedLine,
      archived: archivedLine,
      sections,
    },
    outHrefs,
  };
}

function collectAllNotes(): { active: RawNote[]; archived: RawNote[] } {
  const active: RawNote[] = [];
  for (const n of walkAgentNoteTree().notes) {
    const full = join(agentNoteRoot, n.rel);
    const [lifecycle, cls] = n.rel.split("/");
    active.push(parseNote(
      readFileSync(full, "utf8"),
      n.rel,
      toRepoPath(full),
      lifecycle,
      cls,
      n.date,
    ));
  }

  const archived: RawNote[] = [];
  const archDir = join(agentNoteRoot, "archived");
  const scanArch = (dir: string, prefix: string) => {
    if (!existsSync(dir)) return;
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.name.startsWith(".")) continue;
      const full = join(dir, e.name);
      if (e.isDirectory()) scanArch(full, prefix ? prefix + "/" + e.name : e.name);
      else if (e.isFile() && e.name.endsWith(".md") && !e.name.endsWith(".zh.md")) {
        const rel = "archived/" + (prefix ? prefix + "/" : "") + e.name;
        const dLine = e.name.slice(0, 10);
        const date = /^\d{4}-\d{2}-\d{2}$/.test(dLine) ? dLine : "";
        archived.push(parseNote(
          readFileSync(full, "utf8"),
          rel,
          toRepoPath(full),
          "archived",
          prefix || "uncategorized",
          date,
        ));
      }
    }
  };
  scanArch(archDir, "");
  return { active, archived };
}

function resolveHref(href: string, fromId: string, known: Map<string, string>): string {
  const target = href.replace(/\.zh\.md$/, ".md");
  const segs = (fromId.split("/").slice(0, 2).join("/") + "/" + target).split("/");
  const resolved: string[] = [];
  for (const s of segs) {
    if (!s || s === ".") continue;
    if (s === "..") resolved.pop();
    else resolved.push(s);
  }
  const clean = resolved.join("/");
  if (known.has(clean)) return clean;
  const slug = target.split("/").pop()!.replace(/\.md$/, "");
  return known.get(slug) ?? "";
}

function monthsSince(dateStr: string, now: Date): number {
  const t = Date.parse(dateStr);
  if (Number.isNaN(t)) return NaN;
  return (now.getTime() - t) / (30.44 * 24 * 3600 * 1000);
}

function freshnessOf(n: RawNote, now: Date) {
  if (n.lifecycle === "archived") return { state: "archived", monthsSinceVerify: null, rule: "已归档：终态，不再需要复核" };
  const anchor = n.lastVerified || n.date;
  if (!anchor) return { state: "undated", monthsSinceVerify: null, rule: "无日期：无法判定新鲜度" };
  const m = monthsSince(anchor, now);
  const stale = m > STALE_MONTHS;
  return {
    state: stale ? "stale" : "fresh",
    monthsSinceVerify: Math.round(m * 10) / 10,
    rule: stale
      ? `超过 ${STALE_MONTHS} 个月未复核（最后确认 ${anchor}）：索引内容可能滞后于代码，改动前必须回读源文件与代码`
      : `最近复核 ${anchor}`,
  };
}

interface ModuleDoc {
  id: string;
  path: string;
  title: string;
  scope: string[];
  line: { title: number; scope: number | null };
}

function collectModules(): ModuleDoc[] {
  const modRoot = resolve(agentNoteRoot, "..", "..", "docs", "modules");
  if (!existsSync(modRoot)) return [];
  const out: ModuleDoc[] = [];
  const scan = (dir: string, prefix: string) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.name.startsWith(".")) continue;
      const full = join(dir, e.name);
      if (e.isDirectory()) scan(full, prefix ? prefix + "/" + e.name : e.name);
      else if (e.isFile() && e.name.endsWith(".md") && !e.name.endsWith(".zh.md")) {
        const raw = readFileSync(full, "utf8");
        const lines = raw.split(/\r?\n/);
        const id = (prefix ? prefix + "/" : "") + e.name.replace(/\.md$/, "");
        let title = id;
        const tIdx = lines.findIndex((l) => /^#\s+/.test(l));
        if (tIdx !== -1) title = lines[tIdx].replace(/^#\s+(?:Module[:：]\s*)?/, "").trim() || id;
        let scope: string[] = [];
        let scopeLine: number | null = null;
        const sIdx = lines.findIndex((l) => /^Scope\s*[:：]\s*.+/.test(l));
        if (sIdx !== -1) {
          scope = lines[sIdx].replace(/^Scope\s*[:：]\s*/, "").split(/[,，]/).map((x) => x.trim()).filter(Boolean);
          scopeLine = sIdx + 1;
        }
        out.push({
          id,
          path: toRepoPath(full),
          title,
          scope,
          line: { title: tIdx !== -1 ? tIdx + 1 : 1, scope: scopeLine },
        });
      }
    }
  };
  scan(modRoot, "");
  return out;
}

function scopeCovers(pattern: string, codePath: string): boolean {
  const p = pattern.replace(/^\.\//, "").replace(/\/+$/, "");
  const c = codePath.replace(/^\.\//, "").replace(/\/+$/, "");
  if (p.endsWith("/**")) return c.startsWith(p.slice(0, -2)) || c === p.slice(0, -3);
  return p === c || c.startsWith(p + "/");
}

export interface BuildOptions {
  now?: Date;
}

/** 编译完整索引对象（不落盘）。 */
export function buildIndex(opts: BuildOptions = {}) {
  const now = opts.now ?? new Date();
  const { active, archived } = collectAllNotes();
  const known = new Map<string, string>();
  for (const n of [...active, ...archived]) {
    known.set(n.id, n.id);
    known.set(n.id.split("/").pop()!.replace(/\.md$/, ""), n.id);
  }

  // 关系边
  const citesOf = new Map<string, string[]>();
  const citedBy = new Map<string, string[]>();
  const relations: { type: string; from: string; to: string; source?: number }[] = [];
  for (const n of [...active, ...archived]) {
    const seen = new Set<string>();
    for (const href of n.outHrefs) {
      const t = resolveHref(href, n.id, known);
      if (!t || t === n.id || seen.has(t)) continue;
      seen.add(t);
      relations.push({ type: "cite", from: n.id, to: t });
      citesOf.set(n.id, [...(citesOf.get(n.id) ?? []), t]);
      citedBy.set(t, [...(citedBy.get(t) ?? []), n.id]);
    }
  }
  const supersededBy = new Map<string, string[]>();
  const resolvedSupersedesOf = new Map<string, string>();
  for (const n of [...active, ...archived]) {
    const t = n.supersedes ? (known.get(n.supersedes.replace(/^\.\//, "")) ?? n.supersedes) : "";
    if (!t) continue;
    relations.push({ type: "supersede", from: n.id, to: t });
    resolvedSupersedesOf.set(n.id, t);
    supersededBy.set(t, [...(supersededBy.get(t) ?? []), n.id]);
  }

  const noteEntry = (n: RawNote) => ({
    id: n.id,
    path: n.repoPath,
    anchor: `// Note: .agents/notes/${n.id}`,
    title: n.title,
    lifecycle: n.lifecycle,
    class: n.cls,
    date: n.date || null,
    scope: n.scope,
    supersedes: resolvedSupersedesOf.get(n.id) ?? null,
    supersededBy: supersededBy.get(n.id) ?? [],
    cites: citesOf.get(n.id) ?? [],
    citedBy: citedBy.get(n.id) ?? [],
    lastVerified: n.lastVerified || null,
    archivedDate: n.archivedDate || null,
    freshness: freshnessOf(n, now),
    summary: n.summary || null,
    bodySha256: createHash("sha256").update(n.raw).digest("hex").slice(0, 16),
    lines: n.lines,
    updateHint: `编辑 ${n.repoPath} 后运行：npx tsx scripts/notes.ts verify && npx tsx scripts/notes.ts index`,
  });

  // 模块文档与管辖笔记
  const moduleDocs = collectModules();
  const modules = moduleDocs.map((m) => {
    const governing = active.filter((n) =>
      n.lifecycle === "implemented" && n.scope.some((sp) => m.scope.some((ms) => scopeCovers(ms, sp) || scopeCovers(sp, ms))));
    const overlaps = moduleDocs.filter((o) => o.id !== m.id && o.scope.some((os) =>
      m.scope.some((ms) => scopeCovers(os, ms) || scopeCovers(ms, os))));
    return {
      id: m.id,
      path: m.path,
      title: m.title,
      scope: m.scope,
      lines: m.line,
      governingNoteIds: governing.map((n) => n.id),
      overlapWith: overlaps.map((o) => o.id),
      updateHint: `编辑 ${m.path} 后运行：npx tsx scripts/notes.ts verify && npx tsx scripts/notes.ts index`,
    };
  });

  const byLifecycle: Record<string, number> = {};
  for (const n of active) byLifecycle[n.lifecycle] = (byLifecycle[n.lifecycle] ?? 0) + 1;
  const staleIds = active.filter((n) => freshnessOf(n, now).state === "stale").map((n) => n.id);

  return {
    version: 1,
    schema: "dde-agent-index/1",
    generatedAt: now.toISOString(),
    generator: "npx tsx scripts/notes.ts index",
    disclaimer: [
      "本索引是笔记库的派生快照，用于快速导航与关系检索，不是事实源。",
      "凡涉及代码修改、实现细节核对、或笔记 freshness.state 为 stale/undated 时，",
      "必须回读 source.path/lines 指向的源文件与相关代码，避免被过期记录误导。",
    ].join("\n"),
    usage: {
      retrieve: "npx tsx scripts/notes.ts query --scope <代码路径> | --topic <关键词> | --related <笔记路径> [--json]",
      refreshIndex: "npx tsx scripts/notes.ts index",
      verify: "npx tsx scripts/notes.ts verify",
      updateNote: "直接编辑 notes[].path 指向的文件（行号锚点见 lines），然后 refreshIndex",
      markRechecked: "npx tsx scripts/notes.ts touch <笔记路径>   # 刷新 Last-verified 元数据",
    },
    stats: {
      activeNotes: active.length,
      archivedNotes: archived.length,
      modules: modules.length,
      relations: relations.length,
      byLifecycle,
      staleNotes: staleIds,
    },
    notes: [...active, ...archived].map(noteEntry),
    modules,
    relations,
  };
}

function stripVolatile(json: string): string {
  // generatedAt 每次必然变化，比较同步性时剔除
  return json.replace(/"generatedAt":\s*"[^"]*"/, '"generatedAt":"-"');
}

/** 入口：由 notes.ts 调度。返回进程退出码。 */
export function runIndex(argv: string[]): number {
  const flag = (name: string): string | undefined => {
    const i = argv.indexOf(name);
    return i !== -1 ? argv[i + 1] : undefined;
  };
  const outArg = flag("--out");
  const check = argv.includes("--check");

  let outPath: string;
  if (outArg) {
    if (/^\\\\/.test(outArg) || /^\/\/[A-Za-z]/.test(outArg) || /^[A-Za-z]:[\\/]/.test(outArg)) {
      console.error("拒绝绝对/网络路径：" + outArg + "（只接受仓库内相对路径）");
      return 1;
    }
    outPath = resolve(process.cwd(), outArg);
  } else {
    outPath = resolve(agentNoteRoot, "..", "index.json");
  }

  const index = buildIndex();
  const content = JSON.stringify(index, null, 2) + "\n";

  if (check) {
    if (!existsSync(outPath)) {
      if (index.notes.length === 0) {
        console.log("ok: no notes and no index — agent index not adopted (opt-in; runs once notes exist)");
        return 0;
      }
      console.error(`agent-index: ${toRepoPath(outPath)} 不存在——请运行 npx tsx scripts/notes.ts index 生成后提交`);
      return 1;
    }
    const disk = readFileSync(outPath, "utf8");
    if (stripVolatile(disk) !== stripVolatile(content)) {
      console.error(`agent-index: ${toRepoPath(outPath)} 与笔记库不同步——请运行 npx tsx scripts/notes.ts index 并提交`);
      return 1;
    }
    console.log(`ok: agent index in sync (${index.notes.length} notes, ${index.relations.length} relations, ${index.modules.length} modules)`);
    return 0;
  }

  writeFileSync(outPath, content, "utf8");
  console.log(`ok: agent index written → ${toRepoPath(outPath)}`);
  console.log(`   ${index.notes.length} notes · ${index.modules.length} modules · ${index.relations.length} relations · ${index.stats.staleNotes.length} stale`);
  console.log(`   提醒：索引随笔记派生，笔记变更后重新运行本命令（CI --check 会拦截漂移）。`);
  return 0;
}
