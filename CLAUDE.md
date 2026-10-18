# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

对话使用中文，代码与技术名词保留英文。先读并遵循 [AGENTS.md](AGENTS.md)：调查在先、提问在后，非平凡计划先经授权（已授权的不重复确认），区分实测与假设，遵守并发与基准授权边界。

## 契约文档（动手前先读；冲突需指出具体条款，不擅自选择一侧）

| 文件 | 职责 |
|---|---|
| `SPEC.md` | 业务行为与验收标准（业务契约及版本基线） |
| `openapi.yaml` | 接口路径、DTO 与枚举；标 `x-implemented: false` 的路径（rename/retry/reject/restore/replace-file 与 DELETE /tasks/{task_id}，共 6 处）是规划目标，`routes.py` 未实现，不能当可用接口调用 |
| `ARCHITECTURE.md` | 技术决策、当前实现边界与理由（置顶追加式记录，最新在文件顶部） |
| `RUNTIME.md` | 启动/运行方式、各轮验收记录与边界（最新事实在置顶章节） |
| `LOCAL_OCR.md` | 模型环境、权重 revision 与离线测试方法 |
| `IMPLEMENTATION_PLAN.md` | 当前实现状态与代码入口清单（头部更新日期/依据行＋现状表格＋按日期追加的补录章节） |
| `FRONTEND_FIELDS.md` | 前端字段字典与当前可用 API 入口（字段交接契约，被 SPEC 引用） |

各契约文档头部版本曾互相漂移，2026-10-18 已统一修复（基线：SPEC v1.33、openapi 1.26.0）；此后若再发现不一致，判断现状以 `SPEC.md`/`openapi.yaml` 版本号与 `RUNTIME.md` 置顶章节为准。应用版本号三处同步：`openapi.yaml` info.version、`api.py` FastAPI(version=)、`diagnostics.py` APP_VERSION。

不得宣称未验收的能力（Mac 迁移、16 GB 人资机、CPU-only、全报告准确率、日吞吐）。
同一批次改动契约文档正文时，必须同步该文档头部（版本/依据/对应行/更新日期）及交叉引用版本号；规则见 [契约文档头部同步](.agents/notes/implemented/process/2026-10-18-contract-doc-header-sync.md)。

## 常用命令

应用环境为 `.venvs/app`（Windows 布局，解释器在 `Scripts\python.exe`）。本机另有 5 个模型/离线 venv：`glm-ocr`、`paddleocr-vl`（生产运行时只用这两个）、`chandra`、`paddleocr-vl-1.6`、`image-upright`（均仅离线实验/基准）。

```powershell
# 启动应用（API + 双模型，仅绑定 127.0.0.1；无前端产物时根路径 503，业务 API 可用）
./start.ps1                        # 或双击 start.cmd
./start.ps1 -Port 8766 -NoBrowser

# 后端测试（unittest，CPU-only，无需 GPU/权重；在仓库根目录运行）
.venvs/app/Scripts/python.exe -m unittest discover -s tests -v
.venvs/app/Scripts/python.exe -m unittest tests.test_task_store                 # 单个模块

# 前端（在 frontend/ 目录，Node >= 22.12；node:test 内置 runner 直跑 TS，无浏览器/无 vitest）
npm test                           # node --experimental-strip-types --test tests/*.test.ts
npm run typecheck                  # vue-tsc --noEmit
npm run build                      # vue-tsc --noEmit && vite build（产物 frontend/dist/ 由后端同源托管）

# 应用环境初始化（已存在则勿重建）
.venvs/glm-ocr/Scripts/python.exe -m venv .venvs/app
.venvs/app/Scripts/python.exe -m pip install -r requirements-app.lock.txt

# DDE 笔记（Node >= 18；首次 npx 可能下载 tsx，校验脚本只用 Node 内置模块）
npx tsx scripts/notes.ts query --scope <要改的路径>
npm run verify                    # 等价 npx tsx scripts/notes.ts verify

# 本机运维
access-key.cmd                    # 查看当前 Windows 用户的 operator API Key（过渡机制；一旦存在 web 账号即失效）
collect-diagnostics.cmd           # HTTP 不可用时也可导出安全诊断 ZIP
backend/manage_account.py         # 部署期账号 CLI（创建/重置/禁用命名账号，用 .venvs/app 运行；网页端账号管理的恢复工具）
```

离线 OCR 冒烟/基准脚本（`scripts/run_ocr_smoke_test.py` 等）必须用各自模型 venv（`.venvs/glm-ocr`、`.venvs/paddleocr-vl`、`.venvs/chandra`；Paddle 版本对照实验另用 `.venvs/paddleocr-vl-1.6`）逐个串行运行，避免 12 GB 显存争用；带 GPU 探针的实验脚本与启动器共享本机执行锁（`output/two-model-retest-gpu.lock` 字节锁，文件名是历史遗留），禁止并行；用法见 `LOCAL_OCR.md`。

## 架构（big picture）

多进程设计，API 与模型严格隔离（API 进程不导入 torch，全 backend 仅 `model_worker.py` 延迟导入）：

```text
backend/launch.py → ocr_app/launcher.py（GPU 执行通道字节锁=单实例、固定 dual_resident、业务准备、Windows 退出监督）
 ├─ API 进程（FastAPI，仅 loopback；client.py 经私有协议 spawn/监督 runtime 协调器）
 │   api.py · routes.py：应用工厂、/api/v1 路由全集（内存式 multipart/JSON 解析、角色依赖、准入槽位、写事务内会话与权限复验）
 │   auth.py：命名账号（argon2）+ 30 天单会话 HttpOnly cookie + CSRF + 登录限速；角色 operator/admin/viewer；DPAPI bootstrap operator key（存在任何 web 账号后 X-API-Key 即失效）
 │   business.py · task_store.py · db.py · storage.py：业务装配与 watchdog、SQLite 持久化（WAL、BEGIN IMMEDIATE、busy→SERVICE_BUSY 503）、run_id+result_revision 乐观并发、每账号公平领取（claim 轮转）、AES-GCM 加密 blob + DPAPI 主密钥
 │   admission.py（上传/导出并发准入）· audit.py（事务内操作审计，/admin/audit/* 查询导出）· diagnostics*.py（白名单 JSONL 诊断 + 固定中文文案，与审计分离）
 │   复核与导出：review.py · preview.py · exporting.py（xlsx 仅文本单元格）· export_disputes.py（异议阻断导出）· required_fields.py · retention.py · person_packages.py · workbench_preferences.py · validation.py · privacy.py
 │   API 进程内 CPU 子系统：document_classification.py（POST /classify 分类建议）· region_ocr.py → 一次性子进程 region_ocr_worker.py（框选补录：RapidOCR onnx、单槽 10s、结果不落库仅审计）
 └─ runtime 协调器（runtime_worker.py，唯一任务与 GPU 调度入口；runtime.py ModelManager + model_queues.py 每模型 FIFO + task_scheduler.py 文件进程调度）
     ├─ 文件进程（每任务一个；双 lane：certificate=其余 9 类（各类证书/身份证/护照/户口本/营业执照/学信表/银行卡），medical={MEDICAL_REPORT, TABLE, GENERIC, INTERVIEW_FORM}）：task_worker.py
     │   pipeline.py（两遍解码、主备模型尝试与缓存、证据保全的部分结果）· documents.py（解码、保守分区、原生证据）· extraction.py（字段/表格整理）
     │   文档域模块：doc_profiles.py（doc_type 权威元数据与 13 类型目录；跨进程共享，API 的 catalogue 端点与协调器的 lane 计算也导入它）· document_fields.py · medical_ledger.py · interview_form.py · generic_forms.py / generic_layout.py · photo_table_pipeline.py · table_recognition.py / table_format.py / table_export.py · bank_photocopy.py / bank_bins.py · image_admission.py / image_preprocessing.py（CPU 方向摆正 onnx）
     └─ 模型进程（仅 .venvs/glm-ocr 与 .venvs/paddleocr-vl）：model_worker.py 私有协议（load/recognize、GenerationGuard 软预算与重复检测）+ winjob.py Job Object 进程树监督
```

- 并发模型：生产固定 `dual_resident`——GLM 与 Paddle 各自 FIFO 队列、同模型同时最多一个推理请求、跨模型可重叠；启动加载/预热串行。`single_resident` 全串行逻辑仅存于内部路径（测试与离线串行基准），启动器已不接受该选项，旧单模型偏好自动归一为 dual。并发会话中故障模型本会话禁用，不自动重载。
- 模型路由：体检/表格/通用/面试表主用 Paddle（主备各一次）；证书类主用 GLM（glm×2 + paddle×1）；银行卡按 front/supplement/ambiguous_front 分区各一次，未检出分区的 whole 回退区域按证书类三连尝试。生成软预算分档：医疗与面试表 20 秒，通用、银行卡与拍照表格 40 秒（表格档在 `photo_table_pipeline.py` 单独定义），证书类无软预算。
- 预算：Task 领取后共享 180 秒（含模型队列等待与换模），双层 watchdog——协调器在 deadline+1s 定向停止该任务，API 进程 Business.watch 以首次观察时刻 +181s 兜底；停止失败置 SUPERVISION_FAILED 并关闭整个 runtime。
- 数据：SQLite 在 `.runtime/data/`（WAL、Alembic 迁移 `backend/migrations/`，当前 0001–0012）；敏感产物 AES-GCM 加密，部署密钥在 `.runtime/secrets/`（Windows DPAPI，跨用户复制不可恢复）；保留期管理员可配置（7/15/30 天或永不清除，初始 7 天）；schema0011 操作审计表升级后不可只回退旧代码（旧版按七列插入 audit 不兼容），回退须用备份先演练。
- 上传与安全防线：每批 100 文件、单文件 50MB、每批 500MB；银行卡与表格只收照片（PDF 拒收）；CVV/CVC/CID 在上传、解码、模型输出三处拒收；时间戳线上 UTC、展示固定 Asia/Shanghai。
- 前端：Vue3/Element Plus（`frontend/`，Node >= 22.12）。生产由后端同源静态托管 `frontend/dist/`（无 CORS；dev server 5173 代理到 8765）；`monitor.ts` 中央批次监视器 + `polling.ts` 串行可取消 ReadLoop；后端响应一律经手写严格解码器；工作台 12 卡片拖拽排序（`useDragReorder`，见 card-drag-reorder skill）与分步指引（`guide.ts` + OperationGuide，见 operation-guide skill）；`bankLengthReference.ts` 为生成文件勿手改。历史副本在 `output/frontend-retired-20261008-v1/`（不入库）。
- `scripts/` 以五类为主：DDE 笔记工具链（TS/tsx）、Excel 工作簿构建器（.mjs）、离线实验/probe（Python，按轮次组织、串行执行）、浏览器 probe（.cjs）、模型下载与诊断收集工具；另有少量生成与驱动脚本（`build_bank_length_reference.py` 生成前端 BIN 参考表、`export-assets.sh`、`run_benchmark_rerun.ps1` 等）；`board.html` 是 `build-board.ts` 生成的 DDE 决策看板单文件。

## 重要改动必须留笔记（DDE）

非平凡改动（行为、架构、跨文件契约、流程与工具链、测试策略、落盘/网络/配置格式）前，先 `npx tsx scripts/notes.ts query --scope <路径>` 检索 `.agents/notes/{proposed,implemented,rejected,archived}/`，按主题核对 proposed/implemented/rejected；写或更新笔记并随代码同批落地；机械性小改直接修改并验证。被放弃的方案先写其最强理由再解释为何不用。提交前（未提交时为交付前）跑 `npm run verify`，红了先修再交。完整规则、笔记格式与操作流见 [AGENTS.md](AGENTS.md) 与 [DDE Skill](.agents/skills/dde/SKILL.md)。

## 仓库边界

`models/`、`.venvs/`、`output/`（含前端历史副本与 `frontend/output/`）、`outputs/`、`.runtime/`、`tmp/`、`.cache/`、`node_modules/`、`frontend/dist/` 均在 `.gitignore`：本机运行态、权重与实验产物不随源码提交（DDE skill 本体 `.claude/skills/dde/` 也不入库，来源锁定在 `skills-lock.json`）。本机服务仅绑定 127.0.0.1，不对内网提供推理服务；根目录 `start(外网).cmd` 只是用浏览器打开远程部署实例（部署分支 codex/mac-docker-deploy），本机不因此启动或暴露任何服务，也不据此宣称已验收的远程/Mac 能力。
