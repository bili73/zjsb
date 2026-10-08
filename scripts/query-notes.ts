/**
 * Structured retrieval over the Agent Note tree — the retrieval library
 * behind `npx tsx scripts/notes.ts query ...` (the standard way for agents
 * and humans to consult the decision base before acting).
 *
 *   notes.ts query --scope src/server/session.ts   # 反查管辖笔记
 *   notes.ts query --topic "会话持久化"             # 全文检索（全字段）
 *   notes.ts query --related implemented/architecture/xxx.md   # 血缘邻域
 *
 * Output is plain `lifecycle/class/slug.md — title` lines, grouped by
 * relation; designed to be pasted straight into an agent's context.
 * This module is a library: no CLI entry here — notes.ts dispatches it.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { agentNoteRoot, walkAgentNoteTree } from "./agent-note-tree.ts";
import { buildIndex } from "./agent-index.ts";

const META_LINE_KEYS = ["Scope", "Supersedes", "Last-verified", "Archived"];

interface NoteInfo {
  rel: string;
  lifecycle: string;
  title: string;
  date: string;
  scope: string[];
  supersedes: string;
  lastVerified: string;
  body: string;
  outLinks: string[];
}

function readMeta(lines: string[]) {
  const meta = { scope: [] as string[], supersedes: "", lastVerified: "" };
  for (const l of lines.slice(3)) {
    if (!l.trim()) break;
    const hit = META_LINE_KEYS.find((k) => l.startsWith(k + ":") || l.startsWith(k + "："));
    if (!hit) break;
    const value = l.slice(hit.length + 1).trim();
    if (hit === "Scope") meta.scope = value.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
    else if (hit === "Supersedes") meta.supersedes = value;
    else if (hit === "Last-verified") meta.lastVerified = value;
  }
  return meta;
}

function titleFrom(raw: string, fallback: string): string {
  const line = raw.split(/\r?\n/).find((l) => /^# Agent Note/.test(l)) ?? "";
  return line.replace(/^# Agent Note[^:：]*[:：]\s*/, "").trim() || fallback;
}

function linksFrom(raw: string): string[] {
  const out: string[] = [];
  for (const m of raw.matchAll(/\]\(([^)]+\.md)\)/g)) out.push(m[1].split("#")[0]);
  return out;
}

/** 收集活跃 + 归档笔记的轻量索引（归档仅取头部，供血缘/取代链解析）。 */
function collectNotes(): { active: NoteInfo[]; archived: NoteInfo[] } {
  const active: NoteInfo[] = [];
  for (const n of walkAgentNoteTree().notes) {
    const raw = readFileSync(join(agentNoteRoot, n.rel), "utf8");
    active.push({
      rel: n.rel,
      lifecycle: n.lifecycle,
      title: titleFrom(raw, n.rel),
      date: n.date,
      ...readMeta(raw.split(/\r?\n/)),
      body: raw,
      outLinks: linksFrom(raw),
    });
  }

  const archived: NoteInfo[] = [];
  const archDir = join(agentNoteRoot, "archived");
  const scanArch = (dir: string, prefix: string) => {
    if (!existsSync(dir)) return;
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      if (e.name.startsWith(".")) continue;
      const full = join(dir, e.name);
      if (e.isDirectory()) scanArch(full, prefix ? prefix + "/" : e.name);
      else if (e.isFile() && e.name.endsWith(".md") && !e.name.endsWith(".zh.md")) {
        const raw = readFileSync(full, "utf8");
        const rel = "archived/" + (prefix ? prefix + "/" : "") + e.name;
        const dLine = e.name.slice(0, 10);
        const date = /^\d{4}-\d{2}-\d{2}$/.test(dLine) ? dLine : "";
        archived.push({
          rel,
          lifecycle: "archived",
          title: titleFrom(raw, e.name),
          date,
          ...readMeta(raw.split(/\r?\n/)),
          body: raw,
          outLinks: linksFrom(raw),
        });
      }
    }
  };
  scanArch(archDir, "");
  return { active, archived };
}

function normalizeScopePath(p: string): string {
  return p.replace(/^\.\//, "").replace(/\/\*\*$/, "").replace(/\/+$/, "");
}

/** 双向覆盖：pattern 覆盖 path，或 path 是 pattern 的祖先目录。 */
function scopeRelated(pattern: string, path: string): boolean {
  const a = normalizeScopePath(pattern);
  const b = normalizeScopePath(path);
  return a === b || a.startsWith(b + "/") || b.startsWith(a + "/");
}

/** 把笔记内的相对链接解析成 notes-root 相对路径（尽力而为）。 */
function resolveLinkHref(href: string, fromRel: string, known: Map<string, string>): string {
  const target = href.replace(/\.zh\.md$/, ".md");
  if (target.startsWith("archived/") && known.has(target)) return target;
  const segs = (fromRel.split("/").slice(0, 2).join("/") + "/" + target).split("/");
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

/**
 * 本地路径消毒闸：只接受仓库内相对路径；UNC 网络路径（\\host\share）与
 * 盘符绝对路径一律拒绝——本工具是纯本地读取，永不触网，这里把该边界写成显式校验。
 */
export function sanitizeLocalPathArg(v: string): string {
  const s = v.trim();
  if (/^\\\\/.test(s) || /^\/\/[A-Za-z]/.test(s) || /^[A-Za-z]:[\\/]/.test(s)) {
    throw new Error("拒绝绝对/网络路径参数：" + v + "（只接受仓库内相对路径，例如 src/server 或 .agents/notes/...）");
  }
  if (s.includes("\0")) throw new Error("路径参数包含非法字符");
  return s;
}

/**
 * 检索入口：由 notes.ts 调度。返回进程退出码。
 * --json 输出机器可读结构（含仓库相对路径与行号锚点，供 Agent 直接定位源文件）。
 */
export function runQuery(argv: string[]): number {
  const flag = (name: string): string | undefined => {
    const i = argv.indexOf(name);
    return i !== -1 ? argv[i + 1] : undefined;
  };

  const topicArg = flag("--topic");
  const includeArchived = argv.includes("--archived");
  const jsonMode = argv.includes("--json");

  let scopeArg: string | undefined;
  let relatedArg: string | undefined;
  try {
    const scopeRaw = flag("--scope");
    const relatedRaw = flag("--related");
    scopeArg = scopeRaw ? sanitizeLocalPathArg(scopeRaw) : undefined;
    relatedArg = relatedRaw ? sanitizeLocalPathArg(relatedRaw) : undefined;
  } catch (err) {
    console.error((err as Error).message);
    return 1;
  }

  if (!scopeArg && !topicArg && !relatedArg) {
    console.log("Usage:\n" +
      "  notes.ts query --scope <代码路径>     # 反查管辖该代码的笔记\n" +
      "  notes.ts query --topic <关键词>       # 全文检索（标题/背景/裁定/备选/代价/正文）\n" +
      "  notes.ts query --related <笔记路径>   # 血缘邻域（前置/派生/取代链）\n" +
      "Options:\n" +
      "  --archived   topic/related 结果包含归档区\n" +
      "  --json       机器可读输出（路径 + 行号锚点，供 Agent 回读源文件）");
    return 0;
  }

  // --json 模式：复用 agent-index 的编译结果（单一事实源，带行号锚点）
  if (jsonMode) return runQueryJson({ scopeArg, topicArg, relatedArg, includeArchived });

  const { active, archived } = collectNotes();
  const known = new Map<string, string>();
  for (const n of [...active, ...archived]) {
    known.set(n.rel, n.rel);
    known.set(n.rel.split("/").pop()!.replace(/\.md$/, ""), n.rel);
  }

  const printGroup = (label: string, items: NoteInfo[]) => {
    if (!items.length) return;
    console.log("\n== " + label + "（" + items.length + "）==");
    for (const n of items) {
      const tags: string[] = [];
      if (n.scope.length) tags.push("Scope: " + n.scope.join(", "));
      if (n.supersedes) tags.push("取代 " + n.supersedes);
      if (n.lastVerified) tags.push("复核 " + n.lastVerified);
      console.log("  " + n.rel + " — " + n.title + (tags.length ? "  [" + tags.join(" | ") + "]" : ""));
    }
  };

  if (scopeArg) {
    const hits = active.filter((n) => n.scope.some((sp) => scopeRelated(sp, scopeArg as string)));
    if (!hits.length) {
      console.log("// 没有笔记声明管辖 " + scopeArg + "（Scope 元数据）。可改用 --topic 做全文检索。");
      return 0;
    }
    for (const lc of ["implemented", "proposed", "rejected"]) {
      printGroup(lc, hits.filter((n) => n.lifecycle === lc));
    }
    console.log("\n改动前先读上面这些笔记：implemented 是现行约束，rejected 是被否过的老路。");
    return 0;
  }

  if (topicArg) {
    const q = topicArg.toLowerCase();
    const pool = includeArchived ? [...active, ...archived] : active;
    const hits = pool.filter((n) => n.body.toLowerCase().includes(q) || n.title.toLowerCase().includes(q));
    if (!hits.length) {
      console.log('// 全文未命中 "' + topicArg + '"' + (includeArchived ? "" : "（试试加 --archived 把归档区也算进来）"));
      return 0;
    }
    for (const lc of ["implemented", "proposed", "rejected", "archived"]) {
      printGroup(lc, hits.filter((n) => n.lifecycle === lc));
    }
    return 0;
  }

  // --related
  const relPathArg = relatedArg as string;
  const normalized = relPathArg
    .replace(/\\/g, "/")
    .replace(/^\.agents\/notes\//, "")
    .replace(/^\.\//, "");
  const pool = [...active, ...archived];
  const self = pool.find((n) => n.rel === normalized)
    ?? pool.find((n) => n.rel.split("/").pop() === normalized.split("/").pop());
  if (!self) {
    console.error("未找到笔记：" + relPathArg);
    return 1;
  }

  console.log("\n== 本篇 ==\n  " + self.rel + " — " + self.title);
  if (self.scope.length) console.log("  Scope: " + self.scope.join(", "));

  const outgoing = self.outLinks.map((l) => resolveLinkHref(l, self.rel, known)).filter((r) => r && r !== self.rel);
  const incoming = pool.filter((n) =>
    n.outLinks.some((l) => resolveLinkHref(l, n.rel, known) === self.rel));
  const supersededByMe = self.supersedes
    ? [known.get(self.supersedes.replace(/^\.\//, "")) ?? self.supersedes]
    : [];
  const mySuccessors = pool.filter((n) =>
    n.supersedes && (n.supersedes === self.rel || known.get(n.supersedes.replace(/^\.\//, "")) === self.rel));

  printGroup("前置先决依据（本篇引用）", outgoing.map((r) => pool.find((n) => n.rel === r)!).filter(Boolean));
  printGroup("派生制约影响（被引用）", incoming);
  printGroup("本篇取代", supersededByMe.map((r) => pool.find((n) => n.rel === r)!).filter(Boolean));
  printGroup("已被取代（后继）", mySuccessors);
  if (!outgoing.length && !incoming.length && !supersededByMe.length && !mySuccessors.length) {
    console.log("\n// 独立节点：无引用与取代关系");
  }
  return 0;
}

/* ============ --json 机器可读模式 ============ */

interface JsonQueryArgs {
  scopeArg?: string;
  topicArg?: string;
  relatedArg?: string;
  includeArchived: boolean;
}

function runQueryJson(args: JsonQueryArgs): number {
  const idx = buildIndex();
  const byId = new Map(idx.notes.map((n) => [n.id, n]));

  const out = {
    query: {
      mode: args.scopeArg ? "scope" : args.topicArg ? "topic" : "related",
      arg: args.scopeArg ?? args.topicArg ?? args.relatedArg,
      includeArchived: args.includeArchived,
    },
    results: [] as unknown[],
    hint: "结果为派生索引；涉代码判断或 freshness.state=stale 时，必须按 path/lines 回读源文件与相关代码。",
    refresh: "npx tsx scripts/notes.ts index",
  };

  const entry = (id: string, relation: string) => {
    const n = byId.get(id);
    if (!n) return null;
    return {
      id: n.id, path: n.path, anchor: n.anchor, title: n.title,
      lifecycle: n.lifecycle, class: n.class, date: n.date,
      scope: n.scope, supersedes: n.supersedes, supersededBy: n.supersededBy,
      cites: n.cites, citedBy: n.citedBy,
      lastVerified: n.lastVerified, freshness: n.freshness,
      summary: n.summary, lines: n.lines, relation,
    };
  };

  if (args.scopeArg) {
    const hits = idx.notes.filter((n) =>
      n.lifecycle !== "archived" && n.scope.some((sp) => scopeRelated(sp, args.scopeArg as string)));
    out.results = hits.map((n) => entry(n.id, "governs")).filter(Boolean);
  } else if (args.topicArg) {
    const q = args.topicArg.toLowerCase();
    const { active, archived } = collectNotes();
    const pool = args.includeArchived ? [...active, ...archived] : active;
    const hitIds = pool
      .filter((n) => n.body.toLowerCase().includes(q) || n.title.toLowerCase().includes(q))
      .map((n) => n.rel);
    out.results = hitIds.map((id) => entry(id, "full-text-match")).filter(Boolean);
  } else if (args.relatedArg) {
    const normalized = (args.relatedArg as string)
      .replace(/\\/g, "/")
      .replace(/^\.agents\/notes\//, "")
      .replace(/^\.\//, "");
    const self = byId.get(normalized)
      ?? [...byId.values()].find((n) => n.id.split("/").pop() === normalized.split("/").pop());
    if (!self) {
      console.error(JSON.stringify({ error: "note not found", arg: args.relatedArg }));
      return 1;
    }
    out.results = [
      entry(self.id, "self"),
      ...self.cites.map((id) => entry(id, "cites")),
      ...self.citedBy.map((id) => entry(id, "citedBy")),
      ...(self.supersedes ? [entry(self.supersedes, "supersedes")] : []),
      ...self.supersededBy.map((id) => entry(id, "supersededBy")),
    ].filter(Boolean);
  }

  console.log(JSON.stringify(out, null, 2));
  return 0;
}
