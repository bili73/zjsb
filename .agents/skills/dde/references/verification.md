# 按需阅读：校验与检索脚本

> SKILL §6 的展开。接入 CI 时对照；本地轻量使用时跳过。
>
> 所有子命令都有统一入口：`npx tsx scripts/notes.ts <子命令>`。单脚本直跑依然支持。

## 统一 CLI（scripts/notes.ts）

```sh
npx tsx scripts/notes.ts verify                       # 四线校验（CI 用这个）
npx tsx scripts/notes.ts query --scope <代码路径>      # 反查管辖该代码的笔记
npx tsx scripts/notes.ts query --topic <关键词>        # 全文检索（含备选与代价）
npx tsx scripts/notes.ts query --related <笔记路径>    # 血缘邻域（前置/派生/取代链）
npx tsx scripts/notes.ts query ... --json              # 机器可读输出（路径 + 行号锚点）
npx tsx scripts/notes.ts index [--check]               # 生成/校验 .agents/index.json 资产索引
npx tsx scripts/notes.ts touch <笔记> [--date <日期>]  # 刷新 Last-verified（随后 index）
npx tsx scripts/notes.ts archive <笔记> [--superseded-by <新笔记>]
npx tsx scripts/notes.ts anchors                      # 代码锚点软报告
npx tsx scripts/notes.ts board --init <输出.html> "项目名"        # 本地直读看板
npx tsx scripts/notes.ts board --bundle <notes目录> <输出.html> "项目名" [--modules <dir>] [--metadata-only]
```

## 检查脚本（均为 tsx，零新增依赖）

1. **`verify-agent-note-tree`**（`scripts/agent-note-tree.ts` + `scripts/verify-agent-note-tree.ts`）
   - 校验 lifecycle 封闭集 `proposed/implemented/rejected` + `archived`、class 封闭集 6 个、路径深度 `{lifecycle}/{class}/file.md`、文件名 `yyyy-mm-dd-topic.md`、禁止 `INDEX.md`、活跃笔记内部相对 Markdown 链接有效性。

2. **`verify-agent-note-format`**（`scripts/verify-agent-note-format.ts`）
   - 头部：第 1 行 `# Agent Note:` 标题（半角/全角冒号都收，中文输入法常打出全角）、第 2 行空行、第 3 行 `Status:` 与 lifecycle 一致且全篇唯一。
   - **元数据块（schema v2）**：`Status:` 之后、空行之前只允许 `Scope` / `Supersedes` / `Last-verified` / `Archived` 四键，键不重复；`Scope` 路径必须仓库相对且磁盘存在；`Supersedes` 必须解析到现存笔记；`Last-verified` 不得早于笔记日期或晚于今天；`Archived` 在活跃区出现即报错。
   - 骨架：首节必须 `## Problem`/`## 问题`；per-lifecycle 必需节匹配中英别名（`## Decision`/`## 决策`、`## Consequences`/`## 后果` 等；`## Decision（说明）` 这类括号后缀会先剥掉再匹配）；`implemented` 禁用提案式标题（`## Proposal`/`## Plan`/`## Migration plan`/`## Acceptance criteria` 及其中文别名）。现在时是散文纪律，不扫正文。
   - 备选方案：`## Alternatives considered` / `## 备选方案` / `## 已考虑的替代方案` 等别名必写。脚本不检查「不做/复用」档，也不接受占位注释豁免。
   - 兼容：CRLF/BOM 自动归一。

3. **`verify-archived`**（`scripts/verify-archived-agent-notes.ts`，标配）
   - 每篇归档：头部布局（L1 标题 / L2 空行 / L3 `Status: implemented`，随后元数据块内恰有一行 `Archived: YYYY-MM-DD`，块以空行结束）。不承认 `Superseded-by:` 字段。
   - `archived/manifest.json`：每个文件有封印条目、每条目有对应文件、sha256 与磁盘内容一致（冻结 = 不可篡改的机械含义）。
   - append-only：有 git 时与基线 ref 的 manifest 逐条对比（env `AGENT_NOTE_ARCHIVE_BASE_REF`，本地默认 HEAD）。CI 必须指向变更前的 commit（本仓库 workflow：PR 用 `pull_request.base.sha`，push 用 `github.event.before`），用 HEAD 等于没查。已封印条目被改/删即报错；**无 git 自动降级**为哈希自校验并打印提示——不用 git 一样能跑，只是少了版本基线对照。
   - `--write`：先证明既有封印未变，再为未封印文件追加封印（历史语料补齐用这个）。

4. **`verify-module-docs`**（`scripts/verify-module-docs.ts`，标配，opt-in）
   - `docs/modules/*.md` 存在时校验四条：首行 H1；`Scope:` 恰一行且路径存在；不含决策小节（职责分明）；任意两份模块文档 Scope 不重叠（单一叙述者）。目录不存在视为未采用该约定，直接通过。见 `references/module-wiki.md`。

5. **`check-note-anchors`**（`scripts/check-note-anchors.ts`，软报告，退出码恒 0，**不进 CI**）
   - 扫描源码（env `AGENT_NOTE_CODE_ROOT` 指定根，默认 cwd；自动跳过 node_modules/.git/dist 等）里的 `// Note:` / `# Note:` 物理锚点：报告悬空锚点、没有锚点指向的 implemented 笔记、缺路径的锚点行。宿主没用锚点就不必跑。

6. **`agent-index`**（`scripts/agent-index.ts`，Agent 检索接口）
   - 编译 `.agents/index.json`：全量笔记 + 模块文档的资产/关系（引用、取代链双向）/新鲜度（>6 个月未复核标 stale）/正文哈希/来源行号锚点。仓库相对路径，跨机器稳定。
   - `--check`：内存重建后与磁盘索引比对（剔除 generatedAt），任何笔记正文或结构变化（bodySha256）都会拦截——索引必须随笔记同步提交。
   - 防误导契约：索引是派生快照，唯一事实源是文件与代码；涉代码判断或 stale 条目必须回读源文件。完整 schema 与工作流见 `references/agent-interface.md`。

7. **`touch-note`**（`scripts/touch-note.ts`）
   - 刷新活跃笔记的 `Last-verified:`（存在则替换，缺失则按 Scope → Supersedes → Last-verified 顺序插入元数据块）。拒绝归档件与非法日期（早于笔记日期 / 晚于今天）。CRLF 保持原样。

## 归档 CLI

`notes.ts archive <path> [--superseded-by <新笔记>]` 一次完成：插入 `Archived:`（终止元数据块）→ 物理移入 `archived/` → SHA-256 封印 → 入站死链报告 → 在新笔记头部写入 `Supersedes: archived/...` 元数据 + **吸收完整性检查**（新篇备选条目少于旧篇时警告）。参数与免疫规则见 `references/archiving.md`。

## 接入建议

- 轻量（个人/无 git）：前两个脚本即可，归档封印在第一次归档后自然生效。
- 完整（团队）：`npx tsx scripts/notes.ts verify` 四线进 CI，失败即红（本仓库 `.github/workflows/verify-notes.yml` 可作模板）。

校验脚本方法上来自 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（经 [write-notes-like-deepseek](https://github.com/czm15053/write-notes-like-deepseek) 移植），按通用中文单语宿主裁过：无双语三件套、无 DSH 迁仓豁免。锚点体检是可选软报告，不是 DSH 门禁。元数据块（Scope/Supersedes/Last-verified）、模块文档校验、统一 CLI 与 Agent 资产索引是 DDE 的扩展。
