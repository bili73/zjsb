# 按需阅读：模块 Wiki（docs/modules/）

> DDE 的第三层文档：决策笔记回答「为什么这样定、放弃了什么」，模块文档回答「这个模块是什么、边界在哪」，Wiki 视图负责把两者**实时聚合**成一部可浏览的项目百科。
>
> 核心纪律一句话：**各层只说自己的话，绝不重复叙述**——同一件事只在一处成文，其余全部链接。这是防后期维护疏忽、防两处叙述漂移冲突的机械保证。

## 目录

§0 三层职责分离 ｜ §1 文件契约 ｜ §2 Scope 语法 ｜ §3 机械校验（四条门禁） ｜ §4 看板集成 ｜ §5 写作纪律

---

## 0. 三层职责分离

| 层 | 位置 | 只回答 | 绝不回答 |
|---|---|---|---|
| 决策笔记 | `.agents/notes/**` | 为什么这样定、考虑过什么、放弃了什么、代价 | 模块结构导览 |
| 模块文档 | `docs/modules/<模块>.md` | 模块职责、边界、入口、结构地图 | 任何决策的理由 |
| Wiki 视图 | 看板「模块 Wiki」页 | 实时聚合：模块文档正文 + 按 Scope 归属的管辖决策 + 新鲜度 | ——（纯派生，零维护） |

**为什么严禁跨层重复**：一旦「为什么走消息通道」同时写在笔记和模块文档里，代码演进时必然只改其中一处——半年后两处矛盾，读者不知该信谁。所以：模块文档里需要提决策时，写链接（`[跨插件通信契约](../.agents/notes/implemented/architecture/xxx.md)`），不复制内容。

## 1. 文件契约

每模块一份，放在仓库根 `docs/modules/` 下：

```markdown
# Module: 会话存储（server）

Scope: src/server/**

会话生命周期与持久化边界。入口 `src/server/session.ts`；
并发模型见 [文件句柄持久化](../../.agents/notes/implemented/architecture/2026-08-27-handle-based-session-persistence.md)。

## 结构

- `session.ts` — 池化句柄
- `store.ts` — 事件溯源写入
```

- 第一行必须是 H1（推荐 `# Module: <名称>` 前缀，便于人扫读）。
- `Scope:` 行声明管辖范围（见 §2）。
- 正文自由，但不得出现 `## Problem` / `## Decision` / `## Alternatives` / `## Consequences` 等决策小节——那是笔记的骨架，出现即校验报错。
- 不建 INDEX.md——Wiki 视图就是索引，且它是派生的、永不腐化。

## 2. Scope 语法

- 仓库相对路径，正斜杠：`src/server/**`。
- 三种形态：文件 `src/server/session.ts`、目录 `src/server`（等价于整棵子树）、显式子树 `src/server/**`。
- 多范围逗号分隔：`Scope: src/tools, src/shared/render.ts`。
- 语义与笔记头部的 `Scope:` 完全一致；模块文档的 Scope 与笔记的 Scope 前缀重叠时，该笔记即被视为此模块的「管辖决策」。

## 3. 机械校验（四条门禁）

`npx tsx scripts/verify-module-docs.ts`（已并入 `notes.ts verify`）：

1. 首行必须 H1；
2. `Scope:` 恰好一行、至少一个路径、每个路径在磁盘上存在——模块文档不许与代码脱节；
3. 不得含决策小节（职责分明）；
4. **任意两份模块文档的 Scope 不得重叠**——一片代码只允许一份文档叙述（单一叙述者原则），重叠即报错。

没有 `docs/modules/` 不是错误——这是可选约定，个人小项目可以只用笔记层。

## 4. 看板集成

- **本地直读**：看板授权仓库根目录后自动扫描 `docs/modules/*.md`；改文档切回浏览器即热刷新。
- **打包分发**：`npx tsx scripts/build-board.ts --bundle .agents/notes demo.html "名字" --modules docs/modules`（不传 `--modules` 时默认取 `<notes 目录>/../../docs/modules`）。
- **模块健康度**：由管辖笔记的新鲜度推导（绿 = 3 个月内复核过；黄 = 3–6 个月；红 = 超 6 个月；灰 = 无管辖笔记）。红灯先看 Wiki，再进笔记补 `Last-verified:`。

## 5. 写作纪律

- 模块文档写「是什么/在哪/边界」，一行能说完的不要一段；决策一律链接。
- 新增模块时先建模块文档再写代码笔记，让 Scope 归属从第一天就成立。
- 模块拆分/合并时，同批更新所有相关笔记的 `Scope:`（verify 会拦住路径失效）。
- 拿不准某句话属于哪层？问一句：「这句话三年后还会因为重新选型而改吗？」会 → 笔记；不会 → 模块文档。
