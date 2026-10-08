#!/usr/bin/env node

import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { join, resolve, relative, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const templatePath = resolve(__dirname, '../assets/agent-notes-board.html');
const args = process.argv.slice(2);

if (!existsSync(templatePath)) {
  console.error(`❌ Template not found at: ${templatePath}`);
  process.exit(1);
}

// 检查参数
const isInitMode = args.includes('--init');
const isForce = args.includes('--force') || args.includes('-f');
const isMetadataOnly = args.includes('--metadata-only');
const cleanArgs = args.filter((a: string) => !a.startsWith('--') && !a.startsWith('-'));

function checkTargetSafety(targetPath: string) {
  if (existsSync(targetPath) && !isForce) {
    try {
      const existing = readFileSync(targetPath, 'utf8');
      const isBoard = existing.includes('generator" content="dde-agent-notes-board"') || existing.includes('generator" content="agent-notes-board"') || existing.includes('id="brand-project-title"');
      if (!isBoard) {
        console.error(`❌ 错误：目标文件已存在 (${targetPath}) 且并非看板生成文件！`);
        console.error(`💡 为防止意外覆盖已有项目页面（如 Vite/React/Vue 项目的 index.html），请指定其他输出路径或传入 --force 确认覆盖。`);
        process.exit(1);
      }
    } catch {}
  }
}

if (isInitMode) {
  const targetPath = cleanArgs[0] ? resolve(cleanArgs[0]) : resolve(process.cwd(), 'board.html');
  const projectName = cleanArgs[1] || '工程决策看板';

  checkTargetSafety(targetPath);

  let template = readFileSync(templatePath, 'utf8');
  template = template.replace('id="brand-project-title">工程决策看板<', () => `id="brand-project-title">${projectName}<`);

  writeFileSync(targetPath, template, 'utf8');
  console.log(`✅ [日常开发模式] 轻量看板已生成 (仅 ~69KB): ${targetPath}`);
  console.log(`💡 用浏览器打开后，点击右上角「连接本地目录」选择 .agents/notes，后续新建/修改笔记切回浏览器即可自动热刷新！`);
  process.exit(0);
}

// 打包模式（生成内联完整数据的单文件，如 demo.html）
const notesDir = cleanArgs[0] ? resolve(cleanArgs[0]) : resolve(process.cwd(), '.agents/notes');
const outputPath = cleanArgs[1] ? resolve(cleanArgs[1]) : resolve(process.cwd(), 'demo.html');
const projectName = cleanArgs[2] || '工程决策看板';
const modulesDirIdx = args.indexOf('--modules');
const modulesDir = modulesDirIdx !== -1 && args[modulesDirIdx + 1]
  ? resolve(args[modulesDirIdx + 1])
  : resolve(notesDir, '..', '..', 'docs', 'modules'); // 默认：<仓库根>/docs/modules

checkTargetSafety(outputPath);

const LIFECYCLES = ['implemented', 'proposed', 'rejected', 'archived'];

if (!existsSync(notesDir)) {
  console.error(`❌ Notes directory not found at: ${notesDir}`);
  process.exit(1);
}

/** Blank out fenced code-block lines so `## ` headings and [](.md) links inside them are never parsed as note structure. */
function stripFencedBlocks(raw: string): string {
  let inFence = false;
  return raw
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((l) => {
      if (/^\s{0,3}```/.test(l)) {
        inFence = !inFence;
        return "";
      }
      return inFence ? "" : l;
    })
    .join("\n");
}

function parseNoteContent(raw: string, relPath: string, slugToId: Map<string, string>) {
  const parseable = stripFencedBlocks(raw);
  const slug = relPath.split('/').pop()!.replace(/\.md$/, '');
  const parts = relPath.split('/');
  const lifecycle = parts[0];
  const cls = parts[1] || 'architecture';

  let title = slug;
  let status = lifecycle;
  let date = '';

  const dMatch = /^(\d{4}-\d{2}-\d{2})/.exec(slug);
  if (dMatch) date = dMatch[1];

  const h1Match = /^# Agent Note[^:：]*[:：]\s*(.*)$/m.exec(parseable);
  if (h1Match) title = h1Match[1].trim();

  // 头部元数据块：Status 行之后、首个空行之前的 Key: value 行（与前端 parseMetaBlock 对齐）。
  // 纯字符串前缀解析。
  const meta = { scope: [] as string[], supersedes: '', lastVerified: '', archived: '' };
  const META_KEYS = ['Scope', 'Supersedes', 'Last-verified', 'Archived'] as const;
  for (const rawLine of parseable.split('\n').slice(3)) {
    const line = rawLine.trim();
    if (!line) break;
    let matchedKey: string | null = null;
    let valueStart = -1;
    for (const k of META_KEYS) {
      if (line.startsWith(k)) {
        const rest = line.slice(k.length);
        if (rest.startsWith(':') || rest.startsWith('：')) {
          matchedKey = k;
          valueStart = k.length + 1;
          break;
        }
      }
    }
    if (!matchedKey) break;
    const value = line.slice(valueStart).trim();
    if (matchedKey === 'Scope') meta.scope = value.split(/[,，]/).map((x) => x.trim()).filter(Boolean);
    else if (matchedKey === 'Supersedes') meta.supersedes = value;
    else if (matchedKey === 'Last-verified') meta.lastVerified = value;
    else if (matchedKey === 'Archived') meta.archived = value;
  }

  function extractSection(secNamePattern: string) {
    const re = new RegExp(`^## (?:${secNamePattern})\\s*\\n+([\\s\\S]*?)(?=^## |\\s*$)`, 'm');
    const m = re.exec(parseable);
    return m ? m[1].trim() : '';
  }

  const problem = extractSection('Problem|问题');
  const decision = extractSection('Decision|Proposal|决策|提案');
  const alternatives = extractSection('Alternatives considered|曾考虑的替代方案|曾考虑的备选');
  const consequences = extractSection('Consequences|后果');

  const links: string[] = [];
  for (const m of parseable.matchAll(/\]\(([^)]+\.md)\)/g)) {
    let targetHref = m[1].split('#')[0].trim();
    if (targetHref.includes('://')) continue;
    targetHref = targetHref.replace(/\.zh\.md$/, '.md');
    const segs = `${lifecycle}/${cls}/${targetHref}`.split('/');
    const resolved: string[] = [];
    for (const s of segs) {
      if (!s || s === '.') continue;
      if (s === '..') resolved.pop();
      else resolved.push(s);
    }
    const cleanTarget = resolved.join('/');

    let finalTarget = '';
    if (slugToId.has(cleanTarget)) {
      finalTarget = slugToId.get(cleanTarget)!;
    } else {
      const targetSlug = targetHref.split('/').pop()!.replace(/\.md$/, '');
      if (slugToId.has(targetSlug)) {
        finalTarget = slugToId.get(targetSlug)!;
      }
    }
    if (finalTarget && finalTarget !== relPath) {
      links.push(finalTarget);
    }
  }

  // 取代关系解析：元数据优先，正文指向 archived/ 的链接兜底
  let supersedes = '';
  if (meta.supersedes) {
    const cand = meta.supersedes.replace(/^\.?\//, '');
    if (slugToId.has(cand)) supersedes = slugToId.get(cand)!;
    else {
      const candSlug = cand.split('/').pop()!.replace(/\.md$/, '');
      if (slugToId.has(candSlug)) supersedes = slugToId.get(candSlug)!;
    }
  }

  return {
    id: relPath,
    slug,
    lifecycle,
    cls,
    date,
    title,
    status,
    problem,
    decision,
    alternatives,
    consequences,
    scope: meta.scope,
    supersedes,
    lastVerified: meta.lastVerified,
    archivedDate: meta.archived,
    outLinks: [...new Set(links)],
    rawBody: raw,
  };
}

function walk(dir: string, baseDir: string = dir): any[] {
  const noteFiles = new Map<string, string>(); // relPath -> fullPath

  function scan(currentDir: string) {
    const items = readdirSync(currentDir, { withFileTypes: true });
    for (const entry of items) {
      if (entry.name.startsWith('.')) continue;
      const fullPath = join(currentDir, entry.name);

      if (entry.isDirectory()) {
        scan(fullPath);
      } else if (entry.isFile() && entry.name.endsWith('.md')) {
        const isZh = entry.name.endsWith('.zh.md');
        const relPath = relative(baseDir, fullPath).replace(/\\/g, '/');
        const cleanRel = isZh ? relPath.replace(/\.zh\.md$/, '.md') : relPath;
        const parts = cleanRel.split('/');

        if (parts.length >= 3 && LIFECYCLES.includes(parts[0])) {
          if (!noteFiles.has(cleanRel) || isZh) {
            noteFiles.set(cleanRel, fullPath);
          }
        }
      }
    }
  }

  scan(dir);

  const slugToId = new Map<string, string>();
  for (const relPath of noteFiles.keys()) {
    const slug = relPath.split('/').pop()!.replace(/\.md$/, '');
    slugToId.set(slug, relPath);
    slugToId.set(relPath, relPath);
  }

  const results: any[] = [];
  for (const [relPath, fullPath] of noteFiles.entries()) {
    try {
      const raw = readFileSync(fullPath, 'utf8');
      results.push(parseNoteContent(raw, relPath, slugToId));
    } catch (err) {
      console.warn(`⚠️ Error reading ${relPath}:`, err);
    }
  }

  return results;
}

console.log(`🔍 [打包模式] 正在扫描笔记目录: ${notesDir}`);
const notes = walk(notesDir);
console.log(`✅ 解析完成，共发现 ${notes.length} 篇有效 Agent Notes。`);

// 模块文档：docs/modules/*.md（存在时随包内联，供模块 Wiki 视图使用）
function walkModuleDocs(dir: string): any[] {
  if (!existsSync(dir)) return [];
  const mods: any[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith('.md') || entry.name.startsWith('.')) continue;
    const raw = readFileSync(join(dir, entry.name), 'utf8');
    const lines = raw.split(/\r?\n/);
    const titleLine = lines.find((l) => /^#\s+/.test(l)) ?? '';
    const title = titleLine.replace(/^#\s+(?:Module[:：]\s*)?/, '').trim() || entry.name.replace(/\.md$/, '');
    const scopeLine = lines.find((l) => /^Scope\s*[:：]/.test(l)) ?? '';
    const scopeValue = scopeLine.replace(/^Scope\s*[:：]\s*/, '');
    mods.push({
      id: `docs/modules/${entry.name}`,
      title,
      scope: scopeValue.split(/[,，]/).map((s) => s.trim().replace(/\/+$/, '')).filter(Boolean),
      body: raw,
    });
  }
  return mods;
}
const modules = walkModuleDocs(modulesDir);
if (modules.length) {
  console.log(`📚 发现 ${modules.length} 份模块文档（${modulesDir}），将随包内联供 Wiki 视图使用。`);
}

if (isMetadataOnly) {
  console.log('🔒 [安全脱敏] 启用 --metadata-only 模式，已剥离所有笔记的具体正文和详细论证，仅保留决策元数据与关联拓扑。');
  for (const n of notes) {
    n.problem = '[正文已脱敏]';
    n.decision = '[正文已脱敏]';
    n.alternatives = '';
    n.consequences = '';
    n.rawBody = `# Agent Note: ${n.title}\n\nStatus: ${n.status}\n\n<!-- content redacted for public demo -->`;
  }
  for (const m of modules) {
    m.body = `# ${m.title}\n\n<!-- module doc redacted for public demo -->`;
  }
} else {
  console.log('⚠️ [安全提示] 正在生成包含完整正文的数据包。如需对外公开发布且避免泄露内部决策细节，请添加 --metadata-only 参数。');
}

let template = readFileSync(templatePath, 'utf8');

// 注入项目名
template = template.replace('id="brand-project-title">工程决策看板<', () => `id="brand-project-title">${projectName}<`);

// 注入数据
const jsonSafe = JSON.stringify(notes).replace(/</g, '\\u003c');
template = template.replace(
  'window.__INLINE_DATA__ = null;',
  () => `window.__INLINE_DATA__ = ${jsonSafe};`
);

// 注入模块文档
const modulesSafe = JSON.stringify(modules).replace(/</g, '\\u003c');
template = template.replace(
  'window.__INLINE_MODULES__ = null;',
  () => `window.__INLINE_MODULES__ = ${modulesSafe};`
);

writeFileSync(outputPath, template, 'utf8');
console.log(`🎉 [打包完成] 看板已生成: ${outputPath}`);
console.log(`💡 该文件内置了 ${notes.length} 篇笔记数据，可脱机分发、离线演示或部署至 GitHub Pages。`);
