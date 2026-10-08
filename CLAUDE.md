# Claude Code project instructions

Read and follow [AGENTS.md](AGENTS.md) for project constraints, investigation, approval and verification rules.

## 重要改动必须留笔记

1. 非平凡改动（改了行为、架构、跨文件契约、流程与工具链、测试策略、落盘/网络/配置格式）前，遵循 [DDE Skill](.agents/skills/dde/SKILL.md) 写或更新笔记；机械性小改（样式、格式化、打标、不改行为的补丁）直接修改并验证。
2. 动手前先检索：`npx tsx scripts/notes.ts query --scope <要改的路径>`；并按主题检查 proposed、implemented、rejected 中的相关记录。有归属就地更新；新想法先放 proposed/，落地随同代码改动转 implemented/。决定或理由翻转时新建笔记并互链；完全取代旧决策时按 Skill 完成吸收、链接更新及归档，禁止归档未落地的提案。
3. 被放弃的方案先写它最强的理由，再解释为什么不用。
4. 提交前跑 `npx tsx scripts/notes.ts verify`（等价于 `npm run verify`），红了先修再交；尚未提交时，交付前也运行。

使用四态目录及六种按需创建的类目录，具体约束见 AGENTS.md 与 Skill。npx 首次执行可能下载 tsx；校验脚本本身只使用 Node 内置模块。
