<h1 align="center">HRSSC 识别工作台</h1>

<p align="center">
  <strong>本地证件 / 材料 OCR 工作台</strong><br>
  上传 / 人员材料包追加 → 识别 → 人工核对 → 导出 Excel · 数据不出本机
</p>

<p align="center">
  <img src="https://img.shields.io/badge/app-1.26.0-0f9d8f?style=flat-square" alt="app 1.26.0">
  <img src="https://img.shields.io/badge/SPEC-v1.31-0c7e72?style=flat-square" alt="SPEC v1.31">
  <img src="https://img.shields.io/badge/platform-Windows%2010%2B-0078d4?style=flat-square" alt="Windows 10+">
  <img src="https://img.shields.io/badge/Python-3.12-3776ab?style=flat-square" alt="Python 3.12">
  <img src="https://img.shields.io/badge/Vue-3.5-35495e?style=flat-square" alt="Vue 3">
  <img src="https://img.shields.io/badge/Element--Plus-2.14-409eff?style=flat-square" alt="Element Plus">
</p>

---

## 项目简介

面向 HR 场景的**单机内部工具**：操作人员在网页上传证件照片、学历材料与体检报告，系统在本地完成 OCR 识别与结构化提取，经**人工核对补填**后导出为 Excel 台账。服务仅绑定 `127.0.0.1`，识别与存储全程不出本机。

- **11 类材料**：身份证（人像面/国徽面）、毕业证、学位证、银行卡、体检报告、户口本、营业执照、护照、学信网备案表、通用识别
- **表格**：单张照片自动摆正、建议主体/标题，有依据时自动填写单行或多行表头，无法判断时手选；对照原图编辑单元格、插删行列后保存。单份XLSX优先按标题命名，无标题用原图片名或“表格_时间”，多份ZIP；当前不支持PDF、人员包或跨照片续表拼接。复用现有模型，无新增模型。
- **双模型主备**：GLM-OCR（证件语义理解）+ PaddleOCR-VL（体检版面识别），各自独立进程与虚拟环境
- **人工复核优先**：识别成功一律进入「待人工核对」，置信度不造假、进度不造假、导出有门禁
- **安全内建**：账号密码 + Cookie 会话、AES-GCM 加密存储、7 天到期清理、脱敏诊断

## 支持的材料类型

| 材料 | DocTypeEnum | 材料 | DocTypeEnum |
|---|---|---|---|
| 身份证人像面 | `ID_CARD_FRONT` | 户口本 | `HOUSEHOLD_REGISTER` |
| 身份证国徽面 | `ID_CARD_BACK` | 营业执照 | `BUSINESS_LICENSE` |
| 毕业证 | `DIPLOMA` | 护照 | `PASSPORT` |
| 学位证 | `DEGREE_CERT` | 学信网备案表 | `XUEXIN_DIPLOMA_TABLE` |
| 银行卡 | `BANK_CARD` | 通用识别 | `GENERIC` |
| 体检报告 | `MEDICAL_REPORT` | 表格照片转Excel | `TABLE` |

> 识别路由：证件 / 银行卡 / 未知类型默认 GLM-OCR，体检报告默认 PaddleOCR-VL，互为备用。银行卡只收图片（不收 PDF），支持单卡及带手写补充的复印件，提取姓名、卡号、开户行、开户支行；卡号冲突需人工选择，离线 BIN 不推断具体支行。

通用识别面向表单、申请单和登记资料：可靠PDF文字直接提取，照片由现有Paddle识别，必要时回退GLM；按文字位置和表格结构整理动态键值。重复、空值和原文保留，可查看来源、人工补改后导出。复杂记录型表格仍建议使用“表格”入口。

## 端到端流程

```text
  上传材料（选定类型，1–100 个文件）
     │
     ▼
  解码建页 ── EXIF 纠正；证件、表格和通用识别照片另做保守自动摆正
     │        （体检报告与所有 PDF 保持原状；通用识别不做透视矫正）
     │        PDF 优先可靠文字层，图片区域走模型识别
     ▼
  识别提取 ── GLM-OCR / PaddleOCR-VL 主备路由
     │
     ▼
  结构化整理 ── 字段 / 表格 / 编号规则 / 跨字段校验
     │
     ▼
  待人工核对 ── 左侧原图对照 · 右侧结果修正 · 保存重新校验
     │
     ▼
  导出 Excel ── 必填信息齐全才放行（缺失则整次导出阻止并逐项提示）
```

任务状态机：`QUEUED → PREPROCESSING → OCR → EXTRACTING → VALIDATING → COMPLETED / NEED_REVIEW / FAILED`，人工拒绝为 `REJECTED`，运行中取消为 `CANCELLED`。

三条诚实红线：

1. **待人工核对 ≠ 识别失败**，也**不是审核完成态**——所有成功结果一律进入 NEED_REVIEW，由人工定夺；
2. **证件/体检是否可导出只看已保存结果的必填字段**，与审核状态相互独立，0 和 False 算已填写；照片表格完整且表头明确时可直接导出，标题选填，无需首次保存；人工修改后须保存，不完整输出还需明确确认，真实空白格可保留。所有Excel数据区域使用白色底色，表头保留原配色；
3. **进度条 = 已完成的物理 OCR 区域数**（`processed/total`），不代表剩余时间、准确率或整体完成度。

## 系统架构

API 与模型严格隔离的多进程设计（API 进程不导入 torch）：

```text
backend/launch.py → ocr_app/launcher.py（单实例执行锁 · 业务准备 · Windows 退出监督）
 ├─ API 进程（FastAPI，仅绑定 127.0.0.1，不导入 torch）
 │    auth.py · routes.py · business.py · task_store.py · db.py · storage.py · diagnostics.py
 └─ runtime 协调器（runtime_worker.py，唯一任务与 GPU 调度入口）
      ├─ 文件进程（双驻留：证书、体检各一）task_worker.py
      │    documents.py · pipeline.py · extraction.py
      └─ 模型进程（各自独立 venv，私有内存协议 + Job Object 进程树监督）model_worker.py
           ├─ GLM-OCR        .venvs/glm-ocr
           └─ PaddleOCR-VL   .venvs/paddleocr-vl
```

- **并发模型**：默认 `dual_resident`——两模型各自 FIFO 队列，同模型同时最多一个推理请求，跨模型可重叠；正式服务不再提供单模型切换，故障明确提示，健康模型保持驻留。会话内故障模型本会话禁用，不自动重载
- **预算**：每个模型加载/预热 120 秒（dual_resident 串行启动，两模型合计最长约 240 秒）；单任务共享 180 秒（含排队与换模），watchdog 约 181 秒定向停止；医疗报告生成 20 秒软预算、主备各一次
- **数据层**：SQLite（WAL、外键、FULL 同步）位于 `.runtime/data/`，Alembic 迁移随启动执行；敏感产物 AES-GCM 加密，密钥由 Windows DPAPI 用户级保护；任务自创建起 **7 天到期清理**（重跑不延期）
- **乐观并发**：`run_id` / `result_revision` 保护发布、取消、重跑与人工修正，旧执行不能覆盖新结果
- **进度可见**：任务进度以真实 OCR 区域检查点发布，区域计划未知时界面显示阶段文字而不是编造百分比

## 快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Windows | 10+ | 本机部署，仅回环地址 |
| Python | 3.12 | 应用与各模型环境（Windows 布局 venv） |
| Node.js | ≥ 22.12 | 前端构建（DDE 笔记工具链仅需 ≥ 18） |
| NVIDIA GPU | 验证环境 RTX 3060 12 GB | 模型推理需要 CUDA；其他 GPU / CPU-only 配置**未验证** |

模型权重不入库（`models/` 在 `.gitignore`），新机器需按 `LOCAL_OCR.md` 下载并核对 revision。

### 初始化与启动

```powershell
# 1. 应用虚拟环境（已存在则勿重建）
.venvs/glm-ocr/Scripts/python.exe -m venv .venvs/app
.venvs/app/Scripts/python.exe -m pip install -r requirements-app.lock.txt

# 2. 证件照自动摆正的固定版本方向模型（约 6.8MB，SHA256 核验；运行期只读本地）
.venvs/app/Scripts/python.exe scripts/download_image_upright_model.py

# 3. 前端依赖与构建（产物 frontend/dist/；未构建时根路径 503，业务 API 仍可用）
cd frontend
npm ci
npm run build
cd ..

# 4. 首次启用：本地创建管理员（密码终端隐藏输入两次，8–128 字符，无默认密码）
.venvs/app/Scripts/python.exe -X utf8 backend/manage_account.py HRSSC --display-name HRSSC --role admin

# 5. 启动（API + 模型串行加载预热；默认端口 8765、dual_resident，自动打开浏览器）
./start.ps1          # 或双击 start.cmd
# 变体：./start.ps1 -Mode dual_resident -Port 8766 -NoBrowser
```

浏览器访问 `http://127.0.0.1:8765/`，登录后即可使用。日常账号管理（创建 / 启用禁用 / 重置密码 / 删除）由管理员在网页端「账号管理」完成，`manage_account.py` 保留为恢复工具。

前端开发调试：在 `frontend/` 目录运行 `npm run dev`（dev server `127.0.0.1:5173`，`/api` 与 `/health` 代理到 `127.0.0.1:8765`）。

## 常用命令速查

| 用途 | 命令 | 位置 |
|---|---|---|
| 启动应用 | `./start.ps1`（或双击 `start.cmd`） | 仓库根目录 |
| 后端测试（CPU-only，无需 GPU/权重） | `.venvs/app/Scripts/python.exe -m unittest discover -s tests -v` | 仓库根目录 |
| 单个后端测试模块 | `.venvs/app/Scripts/python.exe -m unittest tests.test_task_store` | 仓库根目录 |
| 前端测试 | `npm test` | `frontend/` |
| 前端类型检查 / 构建 | `npm run typecheck` / `npm run build` | `frontend/` |
| DDE 笔记校验（提交前门禁） | `npm run verify` | 仓库根目录 |
| 检索某路径的 DDE 笔记 | `npx tsx scripts/notes.ts query --scope <路径>` | 仓库根目录 |
| 查看本机 operator API Key（过渡） | `access-key.cmd` | 仓库根目录 |
| 导出安全诊断 ZIP | `collect-diagnostics.cmd` | 仓库根目录 |
| 离线 OCR 冒烟 / 基准 | 各模型 venv 逐个**串行**运行 `scripts/run_ocr_smoke_test.py`，见 `LOCAL_OCR.md` | 仓库根目录 |

> 创建任何网页账号后，旧 API Key 认证即关闭；`access-key.cmd` 仅在无账号时供本机 CLI 过渡。

## 安全与数据边界

- **网络**：服务仅绑定 `127.0.0.1`，不开放 Windows 网络边界；登录校验同源 Origin，403 拒绝跨源
- **会话**：Argon2id 密码哈希；HttpOnly / SameSite=Strict Cookie 绝对有效 30 天；CSRF Token 仅存页面内存、随不安全请求以 `X-CSRF-Token` 发送；同客户端 5 分钟内最多 5 次登录尝试
- **账号**：viewer / operator / admin 三级角色；批次按上传账号隔离（管理员可见全部，其余只见自己的），越权与不存在 ID 统一 404；当前登录账号与最后一个启用的管理员不可禁用/删除
- **存储**：敏感产物 AES-GCM 加密；部署密钥 DPAPI 用户级保护，跨用户/电脑复制不可恢复（不把复制数据目录当作已验证迁移）
- **留存**：业务文件、结果与含原始信息的运行历史保留 7 天到期清理；批次列表标注「到期清理」日期，需长期保存请及时导出
- **诊断**：错误卡片只含错误码、编号与位置，绝不含密码、文件名、接口地址与识别内容；页面页脚明示
- **导出**：XLSX 字符串始终按文本单元格写入，不执行公式；完整号码导出后由公司制度保管

## 测试与质量

- 后端：unittest，**CPU-only、无需 GPU 与权重**（约 600 个用例，以仓库当前为准）
- 前端：`node:test` + TypeScript 直跑（16 个测试文件，覆盖解析器、轮询、日历、裁剪、导出等）
- 契约：`openapi.yaml` + `SPEC.md` 前后端共同约束，前端对所有响应做严格 decoder 校验，坏数据拒绝渲染
- 门禁：非平凡改动须随代码落地 DDE 决策笔记，提交前 `npm run verify` 通过

## 目录结构

```text
├─ backend/            # 启动入口 + ocr_app 应用包 + Alembic 迁移 + manage_account.py
│  └─ ocr_app/         # api / auth / routes / business / task_store / db / storage /
│                      # pipeline / documents / extraction / diagnostics / winjob …
├─ frontend/           # Vue 3 + TS + Vite + Element Plus 工作台
│  ├─ src/             # api.ts · monitor.ts · business.ts · engine.ts · workbench.ts · 组件
│  ├─ tests/           # node:test 套件
│  └─ public/help/     # 静态使用说明（工作台「使用说明」抽屉内嵌此页）
├─ tests/              # 后端 unittest（CPU-only）
├─ scripts/            # DDE 笔记工具链（tsx）+ 离线 OCR 冒烟/回放/探针（Python，串行运行）
├─ .agents/notes/      # DDE 决策笔记：proposed / implemented / rejected / archived
├─ models/             # 模型权重（gitignore，不入库）
├─ .venvs/             # app / glm-ocr / paddleocr-vl 等多套 Python 环境（另含 chandra、
│                      # paddleocr-vl-1.6、image-upright 离线对照环境；gitignore）
├─ .runtime/           # SQLite 数据、加密密钥、诊断日志（gitignore，运行态）
├─ SPEC.md             # 业务契约与验收基线（v1.31）
├─ openapi.yaml        # 接口契约（/api/v1，版本 1.26.0）
├─ ARCHITECTURE.md     # 技术决策与实现边界
├─ RUNTIME.md          # 启动/运行方式与各轮验收记录
├─ LOCAL_OCR.md        # 模型环境与离线测试方法
├─ FRONTEND_FIELDS.md  # 前端字段口径
└─ IMPLEMENTATION_PLAN.md  # 实现状态与代码入口清单
```

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2 + Alembic · PyMuPDF · openpyxl · onnxruntime |
| 模型 | GLM-OCR · PaddleOCR-VL-0.9B（生产）；Chandra OCR 2（仅离线对照）· PP-LCNet 方向模型（CPU，自动摆正） |
| 前端 | Vue 3.5 · TypeScript 5.9 · Vite 8 · Element Plus 2.14（全量引入，组合式 API） |
| 存储 | SQLite（WAL）· AES-GCM 加密文件 · DPAPI 密钥 |

不引入 PostgreSQL / Redis / Celery / Docker / 消息中间件；进度刷新为约 2 秒 GET 轮询，无 SSE/WebSocket。

## 能力边界（未验证，不作承诺）

按仓库验收纪律，以下内容**未经测试验收，请勿当作已有能力**：

- 16 GB 人资电脑、未知 GPU、CPU-only 配置——未验证；模型推理无 CPU 回退
- Mac / Mac Studio 集中部署、外网 / TLS / 远程访问入口——未接入
- 整份体检报告的全量识别准确率、持续日吞吐——未验收（历史实测仅为固定子集）
- 透视矫正、纸张弯曲校正、通用 CVV 检测——不处理 / 不承诺
- 任务追加 / 拒绝 / 恢复 / 替换等生命周期接口——未开放
- 标定的置信度数值——一律返回「未标定」，不生成假分数；故障模型不自动重载

## 参与开发

本仓库采用 DDE（Document-Driven Engineering）工作流：非平凡改动前先检索 `.agents/notes/`（`npx tsx scripts/notes.ts query --scope <路径>`），决策笔记与代码同批落地，提交前 `npm run verify` 通过。详见 [AGENTS.md](AGENTS.md) 与 [CLAUDE.md](CLAUDE.md)；决策全景可打开根目录 `board.html`（工程决策看板）。

## 许可说明

内部项目，未附开源许可证。`scripts/DDE-LICENSE.txt`（DDE 笔记工具链）与 `backend/ocr_app/data/bank_bins/LICENSE`（银行卡 BIN 数据）各自附带其许可。

选择“按人员整理”后，一次选齐此人的各种材料，无需先填写姓名；核对逐份分类后整包提交，识别后在批次使用姓名建议或手工确认。建议带来源文件，多姓名需核对，不自动合并；已确认姓名不会被识别覆盖。分类看内容，文件名作后备，全部建议可手动改；未知类型需选择。“按类型批量”保留。从“任务批次 → 补充上传”也可一次补交多种材料，姓名待确认也支持追加。人员包Excel第一张为人员信息总表，一包一行包含所选材料类型的全部字段（含选填与空值），同类多份材料编号分组并各自保留来源；体检项目名称和异常指标也进入总表，后面继续附分类明细，体检18列台账不变；仍仅要求已保存必填值齐全。身份证国徽面可选，人像面可独立识别和导出；两面齐全仅表示文件存在，仍需人工确认属于同一人；普通及历史类型批次保持原样。追加不延长旧材料期限，批次展示剩余材料最近到期时间。操作步骤见网页使用说明第10节。
