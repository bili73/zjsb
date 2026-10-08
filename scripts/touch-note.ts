/**
 * 刷新笔记的 Last-verified 元数据——Agent 核对过笔记与代码一致后的
 * "回写"入口（防止新鲜度漂移、老化横幅误报）。
 *
 *   npx tsx scripts/notes.ts touch <笔记路径或slug> [--date 2026-09-21]
 *
 * 规则：
 *   - 只作用于活跃区笔记；归档件是冻结终态，拒绝修改。
 *   - 日期不得早于笔记自身 date，也不得晚于今天。
 *   - 元数据块不存在时按 schema v2 顺序（Scope → Supersedes → Last-verified）
 *     插入到 Status 行之后、空行终结符之前。
 * 本模块是库：不读 process.argv，由 notes.ts 调度。
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { agentNoteRoot, walkAgentNoteTree } from "./agent-note-tree.ts";

const META_LINE = /^(Scope|Supersedes|Last-verified|Archived)\s*[:：]/;
const TODAY = new Date().toISOString().slice(0, 10);

function findActiveNote(arg: string) {
  const normalized = arg.replace(/\\/g, "/").replace(/^\.agents\/notes\//, "").replace(/^\.\//, "");
  const withMd = normalized.endsWith(".md") ? normalized : normalized + ".md";
  for (const n of walkAgentNoteTree().notes) {
    if (n.rel === normalized || n.rel === withMd) return n.rel;
    const base = n.rel.split("/").pop()!;
    if (base === withMd || base === normalized) return n.rel;
  }
  return null;
}

/** 入口：由 notes.ts 调度。返回进程退出码。 */
export function runTouch(argv: string[]): number {
  const positional = argv.find((a) => !a.startsWith("--"));
  const dateIdx = argv.indexOf("--date");
  const dateArg = dateIdx !== -1 ? argv[dateIdx + 1] : TODAY;

  if (!positional) {
    console.log("Usage: notes.ts touch <笔记路径或文件名> [--date YYYY-MM-DD]");
    console.log("  核对笔记与代码一致后刷新 Last-verified，随后按提示重建索引。");
    return 0;
  }
  if (positional.startsWith("archived/")) {
    console.error("拒绝：归档笔记是冻结终态，不可 touch（如需复活请走新建笔记 + Supersedes 流程）。");
    return 1;
  }

  const rel = findActiveNote(positional);
  if (!rel) {
    console.error("未找到活跃笔记：" + positional);
    return 1;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateArg)) {
    console.error("日期格式必须是 YYYY-MM-DD：" + dateArg);
    return 1;
  }
  if (dateArg > TODAY) {
    console.error(`拒绝：日期 ${dateArg} 晚于今天 ${TODAY}。`);
    return 1;
  }

  const full = join(agentNoteRoot, rel);
  const raw = readFileSync(full, "utf8");
  const eol = raw.includes("\r\n") ? "\r\n" : "\n";
  const lines = raw.split(/\r?\n/);

  // 笔记自身日期下界
  const slugDate = rel.split("/").pop()!.slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}$/.test(slugDate) && dateArg < slugDate) {
    console.error(`拒绝：日期 ${dateArg} 早于笔记日期 ${slugDate}。`);
    return 1;
  }

  const statusIdx = lines.findIndex((l) => /^Status\s*[:：]/.test(l));
  if (statusIdx === -1) {
    console.error("笔记缺少 Status 行，头部不符合 schema——请先运行 notes.ts verify 排查。");
    return 1;
  }

  // 找到元数据块范围与 Last-verified 位置
  let blockEnd = statusIdx + 1; // 首个不匹配元数据的行（含空行）
  for (let i = statusIdx + 1; i < lines.length; i++) {
    if (lines[i].trim() === "" || !META_LINE.test(lines[i])) { blockEnd = i; break; }
    blockEnd = i + 1;
  }
  const existingIdx = lines.findIndex((l) => /^Last-verified\s*[:：]/.test(l));

  if (existingIdx !== -1 && existingIdx < blockEnd) {
    const prev = lines[existingIdx].replace(/^Last-verified\s*[:：]\s*/, "").trim();
    lines[existingIdx] = `Last-verified: ${dateArg}`;
    writeFileSync(full, lines.join(eol), "utf8");
    console.log(`ok: ${rel} Last-verified ${prev || "(空)"} → ${dateArg}`);
  } else {
    // 按 Scope → Supersedes → Last-verified 顺序找插入点
    let insertAt = statusIdx + 1;
    for (let i = statusIdx + 1; i < blockEnd; i++) {
      if (/^Supersedes\s*[:：]/.test(lines[i])) insertAt = i + 1;
      else if (/^Scope\s*[:：]/.test(lines[i])) insertAt = i + 1;
    }
    lines.splice(insertAt, 0, `Last-verified: ${dateArg}`);
    writeFileSync(full, lines.join(eol), "utf8");
    console.log(`ok: ${rel} 插入 Last-verified: ${dateArg}`);
  }

  console.log("后续步骤：");
  console.log("  1. npx tsx scripts/notes.ts verify   # 确认头部格式仍合法");
  console.log("  2. npx tsx scripts/notes.ts index    # 重建 .agents/index.json（CI --check 会拦截漂移）");
  return 0;
}
