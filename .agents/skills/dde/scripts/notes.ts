#!/usr/bin/env node
/**
 * DDE 笔记工具链统一 CLI 入口。
 *
 *   npx tsx scripts/notes.ts verify                       # 四线校验（tree/format/archived/module-docs，CI 用这个）
 *   npx tsx scripts/notes.ts query --scope src/server     # 反查管辖笔记
 *   npx tsx scripts/notes.ts query --topic "会话持久化"    # 全文检索
 *   npx tsx scripts/notes.ts query --related <笔记路径>    # 血缘邻域
 *   npx tsx scripts/notes.ts index [--check]              # 生成/校验 Agent 资产索引 .agents/index.json
 *   npx tsx scripts/notes.ts touch <笔记> [--date <日期>]  # 刷新 Last-verified 后重建索引
 *   npx tsx scripts/notes.ts archive <笔记> [--superseded-by <新笔记>]
 *   npx tsx scripts/notes.ts anchors                      # 代码锚点软报告
 *   npx tsx scripts/notes.ts board --init board.html "名字" | --bundle <notes目录> <输出.html> "名字"
 *
 * 这是一个纯调度层：子命令通过动态 import 复用各脚本的实现；
 * archive / anchors / board 通过重写 process.argv 透传参数（它们在
 * import 时读取自身 argv 并执行）。任何子脚本以非零码退出都会立即终止本进程。
 */
const HELP = `DDE notes CLI — subcommands:
  verify                        四线校验：目录树 / 头部格式与元数据 / 归档封印 / 模块文档契约
  query --scope <代码路径>       反查管辖该代码的笔记（Scope 元数据）
  query --topic <关键词>         全文检索笔记（含备选与代价；--archived 并入归档区）
  query --related <笔记路径>     血缘邻域：前置 / 派生 / 取代链
  query ... --json               机器可读输出（路径 + 行号锚点，供 Agent 回读源文件）
  index [--check]                生成/校验 .agents/index.json 资产索引（Agent 检索接口）
  touch <笔记> [--date <日期>]   核对一致后刷新 Last-verified，随后重建索引
  archive <笔记> [--superseded-by <新笔记>]   归档并封印，写入 Supersedes 互链
  anchors                       代码 // Note: 锚点软报告（不进 CI）
  board --init <输出.html> "项目名"           生成本地直读看板
  board --bundle <notes目录> <输出.html> "项目名"   打包内嵌数据的分发看板
  help                          显示本帮助`;

async function boot(): Promise<void> {
  const nodeBin = process.argv[0] ?? "node";
  const sub = process.argv[2];
  const rest = process.argv.slice(3);

  switch (sub) {
    case "verify": {
      // 依次执行四线校验；任何一线失败都会 process.exit(1) 并终止
      await import("./verify-agent-note-tree.ts");
      await import("./verify-agent-note-format.ts");
      await import("./verify-archived-agent-notes.ts");
      await import("./verify-module-docs.ts");
      return;
    }
    case "query": {
      const mod = await import("./query-notes.ts");
      process.exit(mod.runQuery(rest));
    }
    case "index": {
      const mod = await import("./agent-index.ts");
      process.exit(mod.runIndex(rest));
    }
    case "touch": {
      const mod = await import("./touch-note.ts");
      process.exit(mod.runTouch(rest));
    }
    case "archive": {
      process.argv = [nodeBin, "scripts/archive-agent-note.ts", ...rest];
      await import("./archive-agent-note.ts");
      return;
    }
    case "anchors": {
      process.argv = [nodeBin, "scripts/check-note-anchors.ts", ...rest];
      await import("./check-note-anchors.ts");
      return;
    }
    case "board": {
      process.argv = [nodeBin, "scripts/build-board.ts", ...rest];
      await import("./build-board.ts");
      return;
    }
    case undefined:
    case "help":
    case "--help":
    case "-h": {
      console.log(HELP);
      return;
    }
    default: {
      console.error(`未知子命令：${sub}\n`);
      console.log(HELP);
      process.exit(1);
    }
  }
}

boot().catch((err) => {
  console.error(err);
  process.exit(1);
});
