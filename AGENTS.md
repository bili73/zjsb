# Project instructions

Keep conversation in Chinese; use English for code and technical terms.

Investigate relevant code, tests, configuration and existing notes before asking questions. Before non-trivial implementation, state the goal and acceptance criteria, blocking questions (or None), specific assumptions, and the file-level plan. Obtain approval when the plan is not already authorized by the user; do not repeat an approval already given. If a material assumption proves false, explain it and resolve the changed plan before continuing.

Use the smallest implementation that satisfies the approved scope. Verify behavior with relevant tests. Distinguish measurements from assumptions and proposed work from implemented behavior.

Standalone accuracy benchmarks keep one recognition model resident and execute serially. The user authorizes current Windows production cross-model inference: after serial successful dual-model loading/warmup, GLM and Paddle have independent FIFO queues, one in-flight request per model. Single-resident/startup-degraded execution remains serial; failed concurrent models are not automatically reloaded while another model is working. Production concurrency probes require separate outputs and must not be reported as serial accuracy benchmarks. Preserve original samples, previous outputs and failed/truncated measurements. Do not claim support for a 16 GB HR machine or Mac until tested there.

## 重要改动必须留笔记

1. 非平凡改动（改了行为、架构、跨文件契约、流程与工具链、测试策略、落盘/网络/配置格式）前，遵循 [DDE Skill](.agents/skills/dde/SKILL.md) 写或更新笔记；机械性小改（样式、格式化、打标、不改行为的补丁）直接修改并验证。
2. 动手前先检索：`npx tsx scripts/notes.ts query --scope <要改的路径>`；并按主题检查 proposed、implemented、rejected 中的相关记录。有归属就地更新；新想法先放 proposed/，落地随同代码改动转 implemented/。决定或理由翻转时新建笔记并互链；完全取代旧决策时按 Skill 完成吸收、链接更新及归档，禁止归档未落地的提案。
3. 被放弃的方案先写它最强的理由，再解释为什么不用。
4. 提交前跑 `npx tsx scripts/notes.ts verify`（等价于 `npm run verify`），红了先修再交；尚未提交时，交付前也运行。

笔记位于 `.agents/notes/{proposed,implemented,rejected,archived}/`。类子目录仅限 feature、bug-fix、simplification、architecture、process、testing，按需创建。文件名使用首次提出日期；不得把未实施的运行时方案标为 implemented。脚本来自 NianLog/DDE，许可证见 scripts/DDE-LICENSE.txt。
