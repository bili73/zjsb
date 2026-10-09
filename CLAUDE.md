# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

对话使用中文，代码与技术名词保留英文。先读并遵循 [AGENTS.md](AGENTS.md)：调查在先、提问在后，非平凡计划先经授权（已授权的不重复确认），区分实测与假设，遵守并发与基准授权边界。

## 契约文档（动手前先读；冲突需指出具体条款，不擅自选择一侧）

| 文件 | 职责 |
|---|---|
| `SPEC.md` | 业务行为与验收标准（业务契约及版本基线） |
| `openapi.yaml` | 接口路径、DTO 与枚举 |
| `ARCHITECTURE.md` | 技术决策、当前实现边界与理由 |
| `RUNTIME.md` | 启动/运行方式、各轮验收记录与边界 |
| `LOCAL_OCR.md` | 模型环境、权重 revision 与离线测试方法 |
| `IMPLEMENTATION_PLAN.md` | 当前实现状态与代码入口清单 |

不得宣称未验收的能力（Mac 迁移、16 GB 人资机、CPU-only、全报告准确率、日吞吐）。

## 常用命令

应用环境为 `.venvs/app`（Windows 布局，解释器在 `Scripts\python.exe`）。

```powershell
# 启动应用（API + 模型，仅绑定 127.0.0.1；无前端产物时根路径 503，业务 API 可用）
./start.ps1                        # 或双击 start.cmd
./start.ps1 -Mode dual_resident|single_resident -Port 8766 -NoBrowser

# 后端测试（unittest，CPU-only，无需 GPU/权重；在仓库根目录运行）
.venvs/app/Scripts/python.exe -m unittest discover -s tests -v
.venvs/app/Scripts/python.exe -m unittest tests.test_task_store                 # 单个模块
.venvs/app/Scripts/python.exe -m unittest tests.test_task_store.Class.test_method

# 应用环境初始化（已存在则勿重建）
.venvs/glm-ocr/Scripts/python.exe -m venv .venvs/app
.venvs/app/Scripts/python.exe -m pip install -r requirements-app.lock.txt

# DDE 笔记（Node >= 18；首次 npx 可能下载 tsx，校验脚本只用 Node 内置模块）
npx tsx scripts/notes.ts query --scope <要改的路径>
npm run verify                    # 等价 npx tsx scripts/notes.ts verify

# 本机运维
access-key.cmd                    # 查看当前 Windows 用户的 operator API Key
collect-diagnostics.cmd           # HTTP 不可用时也可导出安全诊断 ZIP
```

离线 OCR 冒烟/基准脚本（`scripts/run_ocr_smoke_test.py` 等）必须用各自模型 venv（`.venvs/glm-ocr`、`.venvs/paddleocr-vl`、`.venvs/chandra`）逐个串行运行，与启动器共享本机执行锁，禁止并行；用法见 `LOCAL_OCR.md`。

## 架构（big picture）

多进程设计，API 与模型严格隔离（API 进程不导入 torch）：

```text
backend/launch.py → ocr_app/launcher.py（单实例执行锁、业务准备、Windows 退出监督）
 ├─ API 进程（FastAPI，仅 loopback）：api.py / routes.py / auth.py / diagnostics.py
 │   business.py · task_store.py · db.py · storage.py：准入、持久化、run/revision 版本保护、加密与到期清理
 └─ runtime 协调器（runtime_worker.py，唯一任务与 GPU 调度入口）
     ├─ 文件进程（双驻留时证书、体检各一）：task_worker.py
     │   documents.py · pipeline.py · extraction.py：解码、保守分区、证据留存、字段/表格整理
     └─ 模型进程（各自独立 venv）：model_worker.py 私有协议 + winjob.py Job Object 进程树监督
```

- 并发模型：默认 `dual_resident`，GLM 与 Paddle 各自 FIFO 队列、同模型同时最多一个推理请求、跨模型可重叠；启动加载/预热仍串行。`single_resident` 全串行降级。并发会话中故障模型本会话禁用，不自动重载。
- 乐观并发：`run_id` / `result_revision` 保护发布、取消与重跑；旧执行不能覆盖新结果，版本冲突须重新查询。
- 预算：Task 领取后共享 180 秒（含模型队列等待与换模）；watchdog 约 181 秒定向停止；医疗生成 20 秒软预算、主备模型各最多一次。
- 数据：SQLite 在 `.runtime/data/`（WAL、Alembic 迁移位于 `backend/migrations/`）；敏感产物 AES-GCM 加密，部署密钥在 `.runtime/secrets/`（Windows DPAPI，跨用户复制不可恢复）；任务自创建起 7 天到期清理。
- 前端：旧 Vue 前端已移出，独立重构中（历史副本在本机 `output/frontend-retired-20261008-v1/`，不入库）；`frontend/dist/` 已在 `.gitignore`。
- `scripts/` 两类：DDE 笔记工具链（TypeScript/tsx）与离线实验/probe 脚本（Python，按各轮报告组织，串行执行）。

## 重要改动必须留笔记（DDE）

非平凡改动（行为、架构、跨文件契约、流程与工具链、测试策略、落盘/网络/配置格式）前，先 `npx tsx scripts/notes.ts query --scope <路径>` 检索 `.agents/notes/{proposed,implemented,rejected,archived}/`，按主题核对 proposed/implemented/rejected；写或更新笔记并随代码同批落地；机械性小改直接修改并验证。被放弃的方案先写其最强理由再解释为何不用。提交前（未提交时为交付前）跑 `npm run verify`，红了先修再交。完整规则、笔记格式与操作流见 [AGENTS.md](AGENTS.md) 与 [DDE Skill](.agents/skills/dde/SKILL.md)。

## 仓库边界

`models/`、`.venvs/`、`output/`、`outputs/`、`.runtime/`、`tmp/`、`.cache/`、`frontend/dist/` 均在 `.gitignore`：本机运行态、权重与实验产物不随源码提交。服务仅绑定 127.0.0.1，不对内网提供推理服务。
