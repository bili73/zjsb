# Agent 检索接口（.agents/index.json）

> 面向 AI Agent 的机器可读资产索引：一次生成，全库导航。Agent 开工先读索引，
> 不再每次全库扫描重新"了解项目"，节省 token 与时间。

## 为什么需要它

Agent 每次进入项目都要重新回答三个问题：**这个项目有哪些决策资产？它们互相什么关系？
我要动的代码归哪些决策管？** 没有索引时只能全库扫描；有了索引，一次检索即可定位，
再按行号锚点精准回读源文件。

## 接口总览

| 命令 | 用途 |
| --- | --- |
| `npx tsx scripts/notes.ts index` | 生成/刷新 `.agents/index.json`（笔记变更后必跑） |
| `npx tsx scripts/notes.ts index --check` | CI 门禁：索引与笔记库不同步即失败 |
| `npx tsx scripts/notes.ts query --scope <代码路径> [--json]` | 反查管辖某代码的笔记 |
| `npx tsx scripts/notes.ts query --topic <关键词> [--json]` | 全文检索（含备选与代价） |
| `npx tsx scripts/notes.ts query --related <笔记> [--json]` | 血缘邻域（引用/被引/取代链） |
| `npx tsx scripts/notes.ts touch <笔记> [--date <日期>]` | 核对一致后刷新 Last-verified |

`.agents/index.json` 应当提交进版本库（类似 lockfile）：它是全队 Agent 与人的共享地图。

## 索引结构（schema `dde-agent-index/1`）

```jsonc
{
  "version": 1,
  "disclaimer": "派生快照，不是事实源……",      // 见下方安全规则
  "usage": { "retrieve": "...", "refreshIndex": "...", "markRechecked": "..." },
  "stats": { "activeNotes": 0, "archivedNotes": 0, "modules": 0, "relations": 0,
             "byLifecycle": {}, "staleNotes": [] },
  "notes": [{
    "id": "implemented/architecture/2026-09-10-seams-v2.md",
    "path": ".agents/notes/implemented/architecture/2026-09-10-seams-v2.md",  // 仓库相对路径
    "anchor": "// Note: .agents/notes/...",   // 代码内锚点格式
    "title": "…", "lifecycle": "implemented", "class": "architecture", "date": "2026-09-10",
    "scope": ["src/server/**"],               // 管辖代码范围（globs）
    "supersedes": "archived/…md", "supersededBy": [],   // 取代链（双向）
    "cites": [], "citedBy": [],               // 引用关系（双向）
    "lastVerified": "2026-09-10",
    "freshness": { "state": "fresh|stale|archived|undated", "monthsSinceVerify": 0.4, "rule": "…" },
    "summary": "Decision 首段摘要（≤240 字）",
    "bodySha256": "前 16 位内容哈希",           // 任何正文修改都会让 CI --check 拦截
    "lines": {                                 // ★ 来源行号锚点：改哪里、去哪核对
      "title": 1, "status": 3, "scope": [4], "supersedes": 5, "lastVerified": 6,
      "archived": null,
      "sections": [{ "title": "Problem", "line": 8 }, …]
    },
    "updateHint": "编辑 <path> 后运行：verify && index"
  }],
  "modules": [{ "id": "session-store", "path": "docs/modules/session-store.md",
                "scope": ["src/server/session/**"], "governingNoteIds": […],
                "overlapWith": [], "lines": {…} }],
  "relations": [{ "type": "cite|supersede", "from": "…", "to": "…" }]
}
```

## 安全规则（Agent 必读）

1. **索引是地图，不是领土。** 它是派生快照，唯一事实源是 `path` 指向的文件与代码本身。
2. **必须回读源码的情形**——出现以下任一情况，禁止只凭索引行动：
   - 涉及**代码修改**或实现细节核对（索引只存摘要，不存正文）；
   - `freshness.state` 为 `stale`（>6 个月未复核）或 `undated`；
   - 用户描述与索引内容冲突（可能索引滞后，先 `index` 重建再判断）。
3. **代码审查、文档滞后排查**永远直接读代码库——索引负责"去哪找"，不负责"事实是什么"。
4. 索引过期不用于推断：CI 的 `index --check` 会拦截漂移；本地发现不同步时先重建再引用。

## Agent 标准工作流

```text
开工:  读 .agents/index.json（或 query --json 定向检索）
定位:  要动的代码 → query --scope <路径> 拿管辖笔记 → 按 lines 锚点回读全文
核对:  freshness=stale 或涉代码 → 读 src 实现确认笔记仍成立
行动:  实施变更
回写:  事实变了 → 编辑笔记正文（path + lines 定位）
       核对过没变 → notes.ts touch <笔记> 刷新 Last-verified
收尾:  notes.ts verify && notes.ts index（否则 CI --check 拦截）
```

## 实现位置

- 生成器：`scripts/agent-index.ts`（`buildIndex()` 可编程调用）
- 查询层：`scripts/query-notes.ts`（`--json` 复用 buildIndex，单一事实源）
- 回写层：`scripts/touch-note.ts`
- 调度入口：`scripts/notes.ts`（index / touch / query 子命令）
