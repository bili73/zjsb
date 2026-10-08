# 证件关键信息提取系统 — 业务契约（SPEC）

> 本文件定义业务行为与验收要求；`openapi.yaml` 定义接口结构，`ARCHITECTURE.md` 记录当前技术决策及理由。
> 实现前阅读三份文件及相关现有代码。业务和接口发生冲突时先指出具体冲突，不擅自选择；内部实现细节可自主决定并保持一致。
> 影响业务含义、公开接口、数据安全或部署成本的变更需确认并记录。用户已明确授权的修改直接执行，无需重复确认。

- 版本：**v1.13**
- 状态：**已确认的业务基线**（业务及接口变更须同步升版本并追加变更记录；内部实现调整记录在架构文档）
- 当前实现边界：Windows 本机工具，仅绑定loopback；用户计划后续迁移至 Mac Studio 集中服务，远程访问方式待定。迁移/联网尚未实现，不以当前代码宣称支持。
- 规模：每日约50个文件；首版按单机、少量操作人员设计，突发批量上传通过排队处理。文件数不等于页数或推理次数。

当前交付为第二阶段的受控试用切片：支持体检报告、毕业证和学位证的上传、持久任务、只读结果、取消/重跑及本地诊断；创建批次必须明确材料类型。下文完整业务清单仍为验收目标，不能据此宣称全部实现。复核编辑、业务导出、预览及完整值授权尚未开放；当前列表仅分页，重跑沿用原类型和选项。

诊断错误可附加`error_id`、`request_id`及`stage`，本地日志保留安全代码栈位置；诊断包默认不含材料、文件路径、密钥、数据库或截图。具体操作见[RUNTIME.md](RUNTIME.md)。本阶段不接收银行卡类型；误标为证书的图片仍不能保证入库前检测CVV，因此银行卡安全要求尚未验收，不用于银行卡正式业务。未经标定的置信度保持null，结果进入NEED_REVIEW；医疗完整覆盖未确认时统计为null。

---

## 1. 项目目标

由操作人员在网页端**手动上传**证件照片（多为手机拍摄），自动提取结构化关键信息，供人工复核后入库。

> **入口说明**：本项目**只有人工上传一个入口**，无邮件/API 自动接入。
> 操作人员**当场即可看到质量反馈并重传**，因此质量不合格的迭代成本极低——
> 这是本系统相对"异步收件"场景的核心优势，前端必须充分利用（见 11.1 即时质量反馈）。

支持证件类型：

| 类型码 | 名称 | 备注 |
|---|---|---|
| `ID_CARD_FRONT` | 身份证人像面 | 版式全国统一，规则为主 |
| `ID_CARD_BACK` | 身份证国徽面 | 版式全国统一，规则为主 |
| `DIPLOMA` | 毕业证 | 各校版式差异大，大模型为主 |
| `DEGREE_CERT` | 学位证 | 各校版式差异大，大模型为主 |
| `BANK_CARD` | 银行卡 | 卡号区域识别，按适用规则校验；纠错候选必须人工确认 |
| `MEDICAL_REPORT` | 体检报告 | 多页、字段最杂，支持异常指标开关 |
| `HOUSEHOLD_REGISTER` | 户口本 | 含扉页 + N 张常住人口登记卡 |
| `BUSINESS_LICENSE` | 营业执照 | **公开信息，不脱敏**；有严格校验位算法 |
| `XUEXIN_DIPLOMA_TABLE` | 教育部学历证书电子注册备案表 | 可靠 PDF 文字直接提取，图片或不可靠区域才 OCR；接受截图及扫描件；仅限备案表一种 |
| `GENERIC` | 通用识别 | 兜底，不做强结构化 |

---

## 2. 术语

| 术语 | 含义 |
|---|---|
| **Batch（批次）** | 一次提交的处理单元。网页端一次上传会话（可多选文件）= 一个 Batch |
| **Task（任务）** | 一个上传文件对应一个 Task，一个 Batch 含 1..N 个 Task；多页 PDF 不拆 Task |
| **Page / Region** | Task 内部的页面与识别区域；页码从 1 开始，区域必须能映射到完整预处理页面 |
| **Document** | 同一 Task 的单份业务材料；多页体检报告、户口本在文件级汇总。一文件混装无关证件时进入复核，提示分别上传，不静默拼接 |
| **Field** | 抽取字段及溯源、校验记录；仅经标定的字段正确概率称 confidence，无法提供时为 null |
| **Review** | 人工复核，对低置信/校验失败字段进行修正 |
| **run_id / result_revision** | run_id 标识一次处理运行；result_revision 是 Task 单调递增的结果/操作版本，用于拒绝过期写入 |

---

## 3. 部署边界与可靠性要求

### 3.1 首版边界

- 当前 Windows 测试版采用 SQLite、本地受控文件目录和独立 OCR 协调器；仅绑定loopback。用户已选未来 Mac Studio M3 Ultra / 96GB 集中部署，尚未完成后端迁移和远程访问。具体选型及可替换条件见 `ARCHITECTURE.md`。
- 不要求 PostgreSQL、Redis、Celery、容器或分布式部署；额外组件应解决当前已确认的问题，不能只以未来可能扩容为理由引入。
- 本机浏览器经本地API访问，不能直接打开数据库文件；loopback不替代鉴权与审计。数据目录使用本机磁盘，不使用共享盘或同步盘作为活动数据库目录。
- 上传接受后任务持久化；网页服务与模型推理解耦，不能只将工作留在内存队列或请求进程的后台回调中。

### 3.2 必须满足的行为

1. 接收文件和任务状态达到可恢复状态后才返回202；文件落盘与数据库提交之间的失败必须能回收或识别，不能产生永远排队但输入不存在的任务。
2. 任务领取、状态变化、结果及复核写入使用短事务。OCR执行、模型加载和文件转换不在数据库事务内进行。
3. 当前机器只允许一个模型协调器。加载、预热和单驻留换模串行；默认双驻留成功后，GLM、Paddle 各有一个 FIFO 队列，同一模型最多一个请求，两个就绪模型允许并发识别。证书与体检各一个受监督的文件处理进程；备用模型仍进入该模型队列，不能绕过排队。单驻留或启动降级时只处理一个文件；并发会话故障模型不自动重载，不卸载正在服务其他任务的健康模型。排队任务、已完成结果及复核记录不能因网页进程重启消失。
4. worker或机器重启后先确认旧推理进程已停止，再处理遗留任务：无取消请求的QUEUED继续排队，已请求取消的按5.1节确认取消；执行中的未完成run标记中断。首版不做无限自动重跑或假定可从token断点续推。
5. 备份与恢复覆盖数据库及关联文件，恢复后两者对应一致；备份、临时文件与历史记录同样受敏感数据访问及保留期限制。
6. 数据库或文件存储不可用时明确报错，不在未持久化的情况下返回成功；worker不可用由健康检查与界面提示，不伪造进度。

### 3.3 模型约束

GLM-OCR 与原版 PaddleOCR-VL-0.9B 保留各自经过实测的独立 Python 环境、模型 revision 和依赖锁。API运行环境独立选型，不将两个模型的 Transformers 依赖强行合并。既有运行记录见 `LOCAL_OCR.md`，生产接入仍需验收。

证件/银行卡默认GLM，体检默认Paddle，未知类型默认GLM通用识别。两个模型安装在本机；默认`dual_resident`：先启动轻量服务并显示界面，再自动依次加载、预热GLM和Paddle，无需上传文件触发，成功后同会话双模型驻留复用。API/UI进程不导入模型运行库。自动布局/方向处理与识别分阶段执行，布局引擎同样受资源和进程监督约束；人工定框测试不等于自动布局已实现。

备用`single_resident`模式启动时加载、预热默认GLM，需要Paddle时先确认旧模型整个进程树退出再加载；同模型连续任务复用。显式模式选择可在部署配置中保存；自动降级只改变当前会话的有效模式，不改写用户保存的配置。首次启动状态通过`/health.runtime`展示，不伪造百分比或预计完成时间。

启动阶段仅OOM/明确资源不足触发单驻留降级：保留健康模型，失败模型在另一模型树确认退出后最多单独加载一次，仍失败本会话禁用。成功进入双模型并发后，OOM、硬停止或进程失败的模型本会话直接禁用，健康模型继续服务，不自动卸载/重载它来恢复故障模型。依赖/权重错误不冒充资源不足，轮询不触发重试，区域重试仍消耗180秒Task预算。全部模型不可用明确`ocr_unavailable`；Mac、16GB人资机、未知GPU和CPU-only尚未实测。

真实本地launcher/supervisor拥有应用会话及所有模型进程树。正常退出停止领取任务，有界等待退出，必要时终止owned进程树；异常退出须由操作系统监督机制回收两个模型及其子进程，不只当前执行模型。关闭浏览器标签不等于退出应用；恢复按5.1节处理未提交run。Windows Job Object监督方案见ARCHITECTURE，属于待实现及故障验收要求。

体检区域使用原图主模型、原图备用模型各最多一次；不因截断重复同模型对比度/白边尝试。体检每次生成使用20秒软预算，正常回传time_limit及已有文本；time_limit、限长和复读均不算完整，主备仍不完整时保留结果及标记并继续后续区域。生成硬等待在加载完成后限定为实际软预算加10秒，受Task剩余预算约束；软停止不能抢占原生/GPU挂起，硬超时及失败监督仍中止任务。证书保留初次、输入修复、备用模型最多三次的现有策略。模型切换、重试和落盘仍计入180秒Task预算，未扩大总超时。GLM图像与schema抽取须独立验收；Paddle保留表格结构后映射，不增加第三个通用模型。

180秒结束后不再开始新OCR，队列到期即失败；监督器保留既有1秒收尾余量，让流水线有机会发布已提取的部分结果，181秒仍未退出则定向硬停止。此余量不是延长识别预算，也不保证挂起流程能发布部分结果。私有诊断RPC若自身等待超时仍全局关闭runtime，不用于普通业务的单任务超时演示。

## 4. 工程协作与契约边界

### 4.1 文档职责

| 文件 | 职责 | 变更方式 |
|---|---|---|
| `SPEC.md` | 业务含义、处理边界、复核规则和验收标准 | 业务变更经确认后更新 |
| `openapi.yaml` | 路径、请求/响应、字段类型与枚举 | 接口变更同步前后端及契约检查 |
| `ARCHITECTURE.md` | 默认技术选择、部署和维护方式、选择理由 | 内部决策可调整并记录；影响上述契约或部署成本时先确认 |
| 模型与应用依赖锁文件 | 实际验证的可复现版本 | 验证兼容性后更新，不把宽泛版本范围当锁文件 |

### 4.2 实现自由与一致性

- 函数拆分、组件组织、普通工具库选择及目录命名由实现者结合现有代码决定；不预先规定每个文件、类或服务接口。
- 已选择的方案在项目内保持一致。替换需说明当前问题、影响与验证结果，不能在不同模块随意混用多套同类框架。
- API字段维持snake_case；前端可直接使用生成类型，不强制统一转换camelCase。内部变量命名遵循项目约定。
- 时间为带时区的ISO 8601字符串，日期为YYYY-MM-DD。
- 客户端接口类型从OpenAPI生成，生成物不手改；生成工具、输出目录与是否需要mock按实现选取。
- 服务端请求/响应模型须与OpenAPI一致，可生成或编写并通过契约检查；校验码算法、状态转移和跨字段关系由业务校验器实现，不要求从schema自动生成领域逻辑。
- 默认前后端分别组织，模型适配与业务逻辑分离；目录树只是实现结果，不是业务验收项。多人或多代理协作时按本次任务划定编辑范围，不把固定目录权限写入长期契约。
- 需要确认的是会改变业务、接口、安全或部署成本的歧义；可逆的内部实现选择自主完成并记录，不因未指定工具库而暂停。

---

## 5. 核心领域模型

### 5.1 Task 状态机（前后端必须一致）

```
QUEUED → PREPROCESSING → [OCR，仅需识别的区域] → EXTRACTING → VALIDATING
                                                              ├→ COMPLETED
                                                              ├→ NEED_REVIEW
                                                              └→ FAILED
NEED_REVIEW / COMPLETED → 人工修正或确认 → 重新校验 → NEED_REVIEW / COMPLETED
NEED_REVIEW → 人工拒绝 → REJECTED
运行中的任务 → 取消请求 → worker确认停止 → CANCELLED
终态任务 → 显式重跑/恢复 → QUEUED（新run_id，旧运行保留）
```

**状态说明（前端展示必须区分）**

| 状态 | 是否终态 | 前端展示 | 用户可执行 |
|---|---|---|---|
| `QUEUED` | 否 | 排队中（灰） | 取消 |
| `PREPROCESSING` | 否 | 图像预处理中 | 取消 |
| `OCR` | 否 | 文字识别中 | 取消 |
| `EXTRACTING` | 否 | 信息抽取中 | 取消 |
| `VALIDATING` | 否 | 校验中 | 取消 |
| `NEED_REVIEW` | **否（阻塞）** | **待复核（橙）** | 进入复核页、标记不可用、重跑 |
| `COMPLETED` | 是 | 已完成（绿） | 查看、导出、更正复核、重跑 |
| `FAILED` | 是 | 失败（红） | 查看原因、重跑、删除 |
| `REJECTED` | 是 | 已拒绝（灰） | 恢复、删除 |
| `CANCELLED` | 是 | 已取消（灰） | 恢复、删除 |

> **红线**：`NEED_REVIEW` 不是完成态，是**阻塞态**。前端必须提供独立的复核入口（列表页直接可点进），
> 不能把 NEED_REVIEW 和 COMPLETED 混在一个"已处理"列表里，也不能只做只读展示页。

`COMPLETED` 可进入更正/人工在线核验，不表示内容已官方认证。Task 状态只描述本地处理与复核流程。

并发与审计约定：
- Task 创建时分配 `run_id`、`result_revision`；每次发布结果或接受取消/复核/重跑/替换/恢复/拒绝操作，在事务中递增 revision。
- 修改请求必须提交读取到的 `run_id` 和 `expected_revision`。不匹配返回 409 `RESULT_VERSION_CONFLICT`，前端重新读取，禁止盲目覆盖。
- worker 的结果与进度只允许写入当前 run，且不得覆盖已取消/已复核版本；旧运行完成后仅可保存自己的审计记录，不能发布到当前结果。完成与取消竞争以事务先后为准：完成先提交则取消返回409；取消先被接受则禁止发布COMPLETED。
- `/cancel` 仅接受 QUEUED/PREPROCESSING/OCR/EXTRACTING/VALIDATING。接受后置 `cancel_requested=true`，202只表示已请求；确认队列任务不会运行或worker已停止后才转CANCELLED。NEED_REVIEW通过reject处理。
- 重跑/恢复/替换产生新run_id，不删除旧运行、原识别和人工修正审计。替换文件后旧修正绝不自动套用；`reset_review=false` 只表示保留旧修正供对照，旧修正本就保留在审计中。
- 重试同一修改请求不得重复应用：相同旧revision第二次提交返回409，前端读取当前状态确认。新增医疗项目同样受事务和版本约束，不能因重试重复插入。
- `DELETE /tasks/{task_id}` 仅admin且仅终态可调用；批次删除仅允许所有Task终态。删除业务文件/结果但保留不含原始敏感值的审计事件。

恢复检查仅处理当前run，使用事务和版本保护。确认旧执行进程已停止后，原QUEUED有cancel_requested时转CANCELLED，否则保持排队；原PREPROCESSING/OCR/EXTRACTING/VALIDATING且未完成提交的任务，有cancel_requested时转CANCELLED，否则转FAILED并记WORKER_INTERRUPTED；NEED_REVIEW和终态结果保持不变。中断是运行记录的终止原因，不新增公开Task状态。显式重跑生成新run_id，历史保留；不承诺推理恰好执行一次，但只允许当前run发布有效结果。

### 5.2 Batch 状态

| 状态 | 含义 |
|---|---|
| `PROCESSING` | 任一Task处于运行状态或NEED_REVIEW |
| `COMPLETED` | 非空批次全部Task均COMPLETED |
| `PARTIAL` | 全部终态，至少一个COMPLETED且至少一个FAILED/REJECTED/CANCELLED |
| `CANCELLED` | 非空批次全部Task均CANCELLED |
| `FAILED` | 全部终态且无COMPLETED，并至少一个FAILED或REJECTED（包括与CANCELLED混合） |

新增 `cancelled_count`、`rejected_count`，计数口径互斥。批次初建尚在生成Task时为PROCESSING；删除最后一个Task时同步删除空批次，不留下无定义的空批次。NEED_REVIEW不算终态，但应在机器处理停止时即时更新完整性告警，不能等全批次完成才提示缺件。

### 5.3 Batch 级完整性告警（人工上传场景同样必需）

Batch 处理完成后，后端需做跨 Task 的完整性检查，产出 `warnings[]`：

| 告警码 | 触发条件 | 前端文案 |
|---|---|---|
| `MISSING_ID_BACK` | 存在 `ID_CARD_FRONT` 但无 `ID_CARD_BACK` | 缺少身份证国徽面 |
| `MISSING_ID_FRONT` | 存在 `ID_CARD_BACK` 但无 `ID_CARD_FRONT` | 缺少身份证人像面 |
| `MISSING_HOUSEHOLD_PAGE` | 户口本缺少扉页或疑似缺登记卡 | 户口本疑似缺页 |
| `MISSING_MEDICAL_PAGE` | 体检报告疑似缺页 | 体检报告疑似缺页 |
| `DUPLICATE_FILE` | 文件哈希重复 | 同批次提示已复用任务；跨批次提示存在重复但本批次仍独立处理 |
| `XUEXIN_DIPLOMA_EXPIRED` | 学信网报告 `valid_until` 早于今天 | 验证有效期已过，在线核验可能失败，建议延长后重新下载 |
| `XUEXIN_TRUNCATED` | 学信网截图疑似不完整（缺底部/边缘） | 疑似截图不完整，请提供完整截图或原始 PDF |
| `PDF_NO_TEXT_LAYER` | PDF页无可用文字层，已转区域OCR | 扫描页面已使用OCR，建议提供原始电子PDF |
| `PDF_TEXT_UNRELIABLE` | PDF页存在文字层但提取乱码/明显缺字或对齐异常 | 异常区域已转OCR，需核对识别结果 |

告警本身不阻塞 Batch 完成；字段缺失等独立复核问题仍可阻塞Task。告警在详情页顶部以黄色条展示，并提供**「补充上传」**按钮——
点击后直接追加文件到当前 Batch（见 `POST /batches/{batch_id}/append`），
上传完成即重新触发完整性检查。

---

## 6. 字段字典（前后端唯一依据）

所有字段元数据通过 `GET /api/v1/doc-types` 由后端下发，**前端不得硬编码**。
下面是必须实现的字段定义。

> **`XUEXIN_DIPLOMA_TABLE` 的说明**：仅支持《教育部学历证书电子注册备案表》一种，字段集固定（6.10.1），
> 无子类型分组。若收到的 PDF 是学籍在线验证报告、学位在线验证报告或学历/学位认证报告，
> 后端返回 `report_kind=OTHER_REPORT` 并置 `NEED_REVIEW`，前端展示"请提供学历证书电子注册备案表"的提示，
> **不渲染备案表字段模板**。

### 6.1 通用字段结构

每个抽取字段必须包含：

`TaskResult`、`Field`、`MedicalItem` 均须返回 `review_issues` 数组；无待处理问题时返回 `[]`，不得省略。任务级问题、字段级问题及项目级问题分别定位，前端合并展示。

```jsonc
{
  "key": "name",
  "label": "姓名",
  "value": "张三",
  "value_masked": null,          // 敏感字段才有
  "confidence": null,           // 尚无经过标定的字段正确概率，不能随意填0.97
  "confidence_method": "unavailable", // calibrated | unavailable
  "need_review": true,           // 后端计算；此例为必填字段且置信度不可用
  "review_reason": "CONFIDENCE_UNAVAILABLE",
  "review_issues": [{"issue_id": "00000000-0000-4000-8000-000000000001", "code": "CONFIDENCE_UNAVAILABLE", "message": "请对照原图确认", "can_accept": true}],
  "validation_checks": [],      // 分别记录格式、校验码、跨材料匹配和官方核验；不混成一个valid
  "source": {                    // 溯源，复核页对照用
    "page": 1,
    "region_id": "00000000-0000-4000-8000-000000000002",
    "extraction_method": "ocr", // pdf_text | ocr
    "bbox": [0.12, 0.34, 0.56, 0.41],   // 相对完整corrected页面，而非区域裁图
    "raw_text": "姓名 张三"
  }
}
```

`FieldSource` 由 TaskResult 的 run_id/result_revision 绑定；坐标为0..1且x0<x1、y0<y1。PDF文字坐标与裁剪区域坐标须映射到同一corrected页面；没有可靠定位时source/bbox允许缺失，不伪造精确字框。manual修改保留原识别溯源，并另记审计，不能把人工文字写成模型原文。

`FieldSource.bbox_kind` 可选，取 `region`（区域）、`block`（文本块）、`row`（表格行）、`cell`（单元格）；旧结果省略时粒度未声明。整表/整区域坐标不得伪称精确字段框。原生表格重建保留可靠行/单元格位置，无法确认的位置保持缺省。当前只读界面仅显示来源页码与粒度，不提供预览跳转或编辑。

`validation_checks` 每项包含 `kind`（FORMAT/CHECKSUM/CROSS_DOCUMENT/OFFICIAL）、`status`（PASS/FAIL/UNKNOWN/NOT_APPLICABLE）、`rule_id`、`message`。校验码通过不等于实际发行或权属真实。尚未联网/人工官方核验为UNKNOWN，不能因本地规则通过置OFFICIAL=PASS。编号一律按字符串保存，保留前导零；格式归一化保留原值，O/0等替换只能作为待确认候选。

### 6.2 `ID_CARD_FRONT` 身份证人像面

| key | label | 类型 | 必填 | 校验 |
|---|---|---|---|---|
| `name` | 姓名 | string | ✓ | — |
| `gender` | 性别 | enum `M`/`F` | ✓ | — |
| `ethnicity` | 民族 | string | ✓ | 保留原文，字典归一化有记录；不以是否带“族”后缀判错 |
| `birth_date` | 出生日期 | date | ✓ | 日期合法 |
| `address` | 住址 | string | ✓ | — |
| `id_number` | 公民身份号码 | string | ✓ | 18 位 + **ISO 7064 MOD 11-2 校验位** |

### 6.3 `ID_CARD_BACK` 身份证国徽面

| key | label | 类型 | 必填 | 校验 |
|---|---|---|---|---|
| `issuing_authority` | 签发机关 | string | ✓ | 保留原文，机关名称规则仅作辅助，兼容历史名称 |
| `valid_from` | 有效期限起 | date | ✗ | — |
| `valid_to` | 有效期限止 | date \| `"长期"` | ✓ | — |

### 6.4 `DIPLOMA` 毕业证

| key | label | 类型 | 必填 |
|---|---|---|---|
| `name` | 姓名 | string | ✓ |
| `gender` | 性别 | enum | ✗ |
| `birth_date` | 出生日期 | date | ✗ |
| `school_name` | 学校名称 | string | ✓ |
| `major` | 专业 | string | ✓ |
| `education_level` | 学历层次 | enum `专科`/`本科`/`研究生`/`其他` | ✓ |
| `study_mode` | 学习形式 | enum `全日制`/`业余`/`函授`/`网络教育`/`其他` | ✗ |
| `duration` | 学制 | string | ✗ |
| `enroll_date` | 入学日期 | date | ✗ |
| `graduate_date` | 毕业日期 | date | ✓ |
| `certificate_no` | 证书编号 | string | ✓ |
| `issue_date` | 发证日期 | date | ✗ |
| `principal` | 校长 | string | ✗ |

### 6.5 `DEGREE_CERT` 学位证

| key | label | 类型 | 必填 |
|---|---|---|---|
| `name` | 姓名 | string | ✓ |
| `gender` | 性别 | enum | ✗ |
| `birth_date` | 出生日期 | date | ✗ |
| `school_name` | 学校名称 | string | ✓ |
| `major` | 专业 | string | ✓ |
| `degree_category` | 学位级别 | enum `学士`/`硕士`/`博士` | ✓ |
| `degree_name` | 学位名称 | string（如"工学学士"） | ✗ |
| `study_mode` | 学习形式 | enum | ✗ |
| `certificate_no` | 学位证书编号 | string | ✓ |
| `award_date` | 学位授予日期 | date | ✓ |

### 6.6 `BANK_CARD` 银行卡

| key | label | 类型 | 必填 | 校验/脱敏 |
|---|---|---|---|---|
| `card_number` | 卡号 | string | ✓ | **Luhn + BIN + MII/长度**；默认脱敏 |
| `card_number_masked` | 卡号（掩码） | string | ✓ | `**** **** **** 1234` |
| `bin_code` | 发卡行识别码 | string | ✗ | 前 6 位（支持 8 位扩展） |
| `card_scheme` | 卡组织 | enum `VISA`/`MASTERCARD`/`UNIONPAY`/`AMEX`/`JCB`/`DINERS`/`OTHER` | ✗ |
| `bank_name` | 发卡行 | string | ✗ | 由 BIN 库反查，与卡面 OCR 交叉验证 |
| `card_type` | 卡种 | enum `DC`/`CC`/`SCC`/`DCC`/`PC` | ✗ |
| `valid_thru` | 有效期 | string `MM/YY` | ✗ | 月份 01-12 |
| `holder_name` | 持卡人姓名 | string | ✗ |

**银行卡校验与纠错建议（后端必须实现）**

1. 先定位卡号区域，再识别并保留原字符串。字符规范化仅包含有记录的全角数字、分组空格等显示变换，不自动把O/I/B替换为0/1/8。
2. BIN/IIN使用带版本、来源和更新时间的离线数据，支持6位与8位匹配，优先最长匹配。数据未覆盖记UNKNOWN + `BIN_UNKNOWN`，不能当成银行卡不存在；号段与长度按已确认的卡产品规则检查，不用固定首位表覆盖所有卡。
3. 确认属于适用Luhn的卡号时执行mod10；适用规则未知时记UNKNOWN并复核，不将其他银行账号误判为卡号。格式、校验码与银行名称一致性分别记录，全部通过也不证明卡号真实发行或持卡人身份。
4. 当前GLM/Paddle接入不保证逐字top-3、逐位置信度或字框。第一版候选只能来自有来源的局部重识别、另一模型输出或人工输入，不假造逐位概率，不枚举号码来凑校验码。
5. 候选经适用规则过滤后，**即使只有一个也必须人工确认**：置NEED_REVIEW，单候选原因`CORRECTION_PROPOSED`，多候选`MULTI_CANDIDATES`。未经人工选择不得覆盖原`card_number`，也不得通过下调置信度伪装成已完成纠错。
6. 人工选定候选后重新校验。若照片原文确实不满足已知规则，只能按可确认问题记录例外理由；缺号、模型冲突或来源不可辨的问题必须修正/重传，不能点击确认直接放行。

证书与跨材料编号匹配：毕业证、学位证、报告编号和在线验证码分别定义，不能混用字段。证书按颁发年代/类别适配已确认格式；未覆盖规则记UNKNOWN而非无效。跨材料先确认同一人及同一学历/学位记录，再比较完整编号、学校、层次和日期；姓名或脱敏末尾一致只表示部分一致。默认不做银行联网要素验证或自动学信网查询。

### 6.7 `HOUSEHOLD_REGISTER` 户口本

扉页字段：

| key | label | 类型 | 必填 |
|---|---|---|---|
| `household_type` | 户别 | enum `农业家庭户口`/`非农业家庭户口`/`居民家庭户口`/`其他` | ✓ |
| `householder` | 户主姓名 | string | ✓ |
| `household_no` | 户号 | string | ✓ |
| `address` | 住址 | string | ✓ |
| `issued_by` | 签发机关 | string | ✗ |
| `issued_date` | 签发日期 | date | ✗ |
| `registrar` | 承办人 | string | ✗ |

成员列表 `members[]`（每张常住人口登记卡一条）：

| key | label |
|---|---|
| `name` | 姓名 |
| `gender` | 性别 |
| `birth_date` | 出生日期 |
| `ethnicity` | 民族 |
| `birth_place` | 出生地 |
| `native_place` | 籍贯 |
| `id_number` | 公民身份号码（脱敏） |
| `relation_to_householder` | 与户主关系 |
| `education` | 文化程度 |
| `marital_status` | 婚姻状况 |
| `occupation` | 职业 |
| `workplace` | 服务处所 |
| `migration_address` | 迁入地址 |

### 6.8 `MEDICAL_REPORT` 体检报告 ⭐ 含异常指标开关

#### 6.8.1 `basic_info` 基础信息

| key | label | 类型 | 必填 |
|---|---|---|---|
| `name` | 姓名 | string | ✓ |
| `gender` | 性别 | enum | ✓ |
| `age` | 年龄 | int | ✗ |
| `report_no` | 体检编号 | string | ✗ |
| `institution` | 体检机构 | string | ✓ |
| `exam_date` | 体检日期 | date | ✓ |
| `report_date` | 报告日期 | date | ✗ |
| `package_name` | 套餐名称 | string | ✗ |

#### 6.8.2 `items[]` 体检项目

| key | label | 类型 | 说明 |
|---|---|---|---|
| `item_id` | 项目ID | uuid | 当前run内稳定；新增行由后端分配，重识别的新run不复用旧行修改 |
| `name` | 项目名称 | string | 如"白细胞计数" |
| `alias` | 英文缩写 | string | 如 `WBC` |
| `category` | 所属分类 | string | 如"血常规"、"肝功能"、"尿常规" |
| `result_raw` | 结果原文 | string | 原样保留，可能是"阴性"、"未见异常"、">5.0" |
| `value_num` | 数值结果 | number \| null | 仅精确标量可解析时填；`>5.0`等保留result_raw，不丢失比较符当成5.0 |
| `unit` | 单位 | string | 如 `10^9/L`、`mmol/L` |
| `reference_range` | 参考区间原文 | string | 如 `3.5-9.5` |
| `ref_low` | 参考下限 | float \| null | 从区间解析 |
| `ref_high` | 参考上限 | float \| null | 从区间解析 |
| `abnormal_flag` | 异常标记 | enum | 见下 |
| `reported_abnormal_marker` | 原始异常标记 | string \| null | 如↑、↓、H、L、阳性，原样保留 |
| `abnormal_basis` | 标记依据 | enum | report_marker / reference_comparison / unknown |
| `confidence` | 置信度 | number \| null | 仅已标定概率；不可用为null |
| `confidence_method` | 置信度来源 | enum | calibrated / unavailable |
| `need_review` / `review_issues` | 复核要求 | boolean / array | 缺失、无法判断或未经标定时给出原因；支持明确逐问题确认 |

`abnormal_flag` 枚举：

| 值 | 含义 | 是否计入异常 |
|---|---|---|
| `NORMAL` | 正常 | 否 |
| `HIGH` | 偏高 | **是** |
| `LOW` | 偏低 | **是** |
| `ABNORMAL` | 异常（非数值类，如"窦性心律不齐"） | **是** |
| `POSITIVE` | 检出阳性 | 仅报告明确标异常或适用项目规则确认异常时计入；其余归入待判定统计 |
| `UNKNOWN` | 无法判定 | 否，但计入 `stats.unknown` |

#### 6.8.3 异常视图开关（完整识别后过滤）

**第一级：默认返回视图**

创建 Task 时传入：

```jsonc
"extract_options": {
  "abnormal_only": false,     // true = 默认返回异常/待判定项；不跳过正常项目识别
  "include_normal_summary": true
}
```

| `abnormal_only` | 后端行为 | 适用场景 |
|---|---|---|
| `false`（默认） | 完整识别、整理全部项目，默认返回all | 完整档案 |
| `true` | 同样完整识别及落库，仅默认返回异常或待判定项目 | 聚焦查看；不承诺节省识别token或时间 |

**无论开关如何，后端始终返回：**
- `basic_info`
- `items`（当前视图的项目列表，无项目时为 `[]`）
- `stats`（已完整整理项目的统计；页面/区域缺失时计数null并标记结果受限，不能假装完整）
- `abnormal_summary`（异常项摘要列表，含关键项）

**第二级：查询时视图过滤（不重跑任务）**

```
GET /api/v1/tasks/{id}/result?items_filter=abnormal|all|unknown
```

- 显式`items_filter=all`始终返回已识别的全部项目，不因abnormal_only返回409。省略filter时由abnormal_only决定默认视图：false返回全部，true返回已确认异常与待判定项。
- `abnormal`返回已确认异常项；`unknown`返回UNKNOWN以及缺少解释依据的POSITIVE项。两者不能重叠计数。
- `items_filter` 只影响 `items[]` 返回内容，不影响 `stats`
- `include_normal_summary`仅控制 `normal_summary` 是否附正常项汇总文字，false时返回null；不改变完整项目、统计或异常摘要，不得暗示漏识别项目为正常。

#### 6.8.4 `stats` 与 `abnormal_summary`

```jsonc
"stats": {
  "total": 87,        // 完整整理时为已识别项目总数；页面/区域不完整时为null
  "normal": 75,
  "abnormal": 12,
  "unknown": 0,
  "categories": ["血常规", "尿常规", "肝功能", "心电图"]
},
"abnormal_summary": [
  {
    "item_id": "00000000-0000-4000-8000-000000000003",
    "name": "总胆固醇",
    "alias": "TC",
    "category": "血脂",
    "result_raw": "6.82",
    "unit": "mmol/L",
    "reference_range": "2.80-5.17",
    "abnormal_flag": "HIGH",
    "reported_abnormal_marker": "↑",
    "abnormal_basis": "report_marker",
    "deviation": "高于参考上限31.9%", // 可选算术说明，不表示临床严重程度
    "confidence": null,
    "confidence_method": "unavailable",
    "need_review": true,
    "review_issues": [{"issue_id": "00000000-0000-4000-8000-000000000004", "code": "CONFIDENCE_UNAVAILABLE", "message": "请对照报告确认该项目", "can_accept": true}]
  }
]
```

**v1.7 不定义通用 `severity`，不按20%/50%给临床轻重分级，也不把阳性直接判为严重。**

优先保留报告自身标记；数值比较只使用同一项目、相同单位、适用人群和明确边界的报告参考区间。报告标记与比较结果冲突则保留原文并要求复核，不覆盖原标记。范围缺失、不适用、非标量结果或界限有歧义时为UNKNOWN，不推断NORMAL。`abnormal_basis=unknown`不允许HIGH/LOW/ABNORMAL/NORMAL；POSITIVE可保留检出事实，但在缺少项目解释时计入unknown。确认为正常含义的阳性可标NORMAL，原阳性词仍保留在reported_abnormal_marker。

完整结果中 `total=normal+abnormal+unknown`；统计按item_id去重，跨页重印/续表只有在证据明确时合并，不能只凭项目名去重。不完整结果各统计计数为null，limitations说明覆盖范围；abnormal_summary仍列已确认异常，但不能解释为全报告异常总数。`deviation`仅在可比较精确数值且对应非零边界时计算，其他情形为null；不同项目不可据此排序临床风险。

#### 6.8.5 报告结论清单与声明数量

医疗结果新增可选 `report_summary`；兼容旧响应未返回该对象，新版抽取返回：

```json
{
  "scope": "unidentified",
  "declared_count": null,
  "findings": [],
  "count_check": "unverified",
  "sources": []
}
```

- `declared_count` 为报告显式声明的非负整数，未提供、冲突或无法可靠确定时为null；不得以提取条目数反填。
- `scope` 必填，取 `follow_up_required`、`overall_conclusion`、`unidentified`。优先定位“您共有 X项异常需进一步检查并治疗：”等有明确数量的清单标题，按实际页码、标题和章节边界绑定其下条目，scope为follow_up_required；不固定第6页。声明只与**同一标题作用域**的清单核对，不能与另一章全部总检结论、解释段、人体位置图或实验室异常数对账。未找到该标题时可提取总检结论列表且scope为overall_conclusion；无可靠列表则unidentified。后两者声明必须null且校验必须unverified。
- `findings` 为观察到的顶层条目，每条含同一run内稳定UUID `finding_id`、原编号 `reported_number`（字符串或null）、报告原文 `text` 及 `sources: FieldSource[]`。项目符号不是数字编号，复合条目不能按分号擅自拆成原子异常；续页解释不重复计数。无可靠摘要时返回空列表，不据此宣称零异常。
- `sources` 保存清单标题、数量声明与相关章节边界来源，条目自己的sources支持多页；原文按既有受控结果路径处理，诊断日志不记录该原文。
- `count_check` 取 `match`、`mismatch`、`unverified`。match必须同时具备明确声明、同一清单完整边界证据、无编号/候选冲突且条目数一致；只有数相等不能match。声明缺失或清单不完整时unverified；有可靠证据但不一致时mismatch并产生待核对问题。它不是全报告覆盖证明，不改变MedicalStats、置信度或复核状态。
- `abnormal_only`、`items_filter` 和 `include_normal_summary` 不过滤report_summary。前端独立展示“已提取N条”“报告声明未提供/声明N条”“数量待核对/数量不一致/数量一致”，与项目异常统计分开；未知不能显示为0。当前不开放该清单的编辑、自动诊断或医学分级。

### 6.9 `BUSINESS_LICENSE` 营业执照

> **脱敏例外**：营业执照属**公开信息**，`unified_social_credit_code` 等字段**不脱敏**，
> 这与身份证号/银行卡号的处理不同。后端不得对其应用掩码规则。

| key | label | 类型 | 必填 | 校验 |
|---|---|---|---|---|
| `unified_social_credit_code` | 统一社会信用代码 | string | ✓ | 18 位 + **GB 32100-2015 校验位** |
| `company_name` | 名称 | string | ✓ | — |
| `company_type` | 类型 | enum `有限责任公司`/`股份有限公司`/`个人独资企业`/`合伙企业`/`个体工商户`/`其他` | ✓ | — |
| `legal_representative` | 法定代表人 | string | ✓ | 个体工商户时为经营者姓名 |
| `registered_capital` | 注册资本 | string | ✓ | 原文保留，含币种，如 `1000万元人民币` |
| `established_date` | 成立日期 | date | ✓ | — |
| `business_term_start` | 营业期限起 | date | ✗ | — |
| `business_term_end` | 营业期限止 | date \| `"长期"` | ✗ | — |
| `business_scope` | 经营范围 | string（长文本） | ✓ | — |
| `registered_address` | 住所 | string | ✓ | — |
| `registration_authority` | 登记机关 | string | ✓ | 保留原文，不凭固定后缀排除有效历史名称 |
| `issue_date` | 核准日期 | date | ✗ | — |
| `registration_no` | 注册号 | string | ✗ | 仅旧版有 |
| `license_version` | 版式 | enum `NEW_2019`/`OLD` | ✗ | 影响版式定位策略 |

**统一社会信用代码校验（后端必须实现，GB 32100-2015）**

```python
CHARSET = "0123456789ABCDEFGHJKLMNPQRTUWXY"   # 31 字符，不含 I O S V Z
WI = [1,3,9,27,19,26,16,17,20,29,25,13,8,24,10,30,28]

def uscc_ok(code: str) -> bool:
    c = code.strip().upper()
    if len(c) != 18 or any(ch not in CHARSET for ch in c):
        return False
    s = sum(CHARSET.index(c[i]) * WI[i] for i in range(17))
    v = 31 - (s % 31)
    if v == 31:
        v = 0
    return CHARSET.index(c[17]) == v
```

- 校验失败 → `NEED_REVIEW` + `USCC_CHECKSUM_FAILED`
- 校验通过只更新CHECKSUM=PASS，不修改或虚构confidence，不证明实际登记有效
- **版式提示**：正本为**竖版**、副本为**横版**，2019 新版为横版。几何校正的 ROI 定位须区分竖/横版，
  否则经营范围长文本区域会定位错位

### 6.10 `XUEXIN_DIPLOMA_TABLE` 教育部学历证书电子注册备案表 ⭐ 处理路径与其他证件完全不同

> **本项目明确范围：学信网只处理《教育部学历证书电子注册备案表》一种。**
> 其他学信网报告（学籍在线验证报告、学位在线验证报告、学历/学位认证报告）**不在本版范围内**，
> 识别到时按 6.10.2 处理，**不要抽取其字段**。

> 所有PDF都先检查每页/区域文字层质量，备案表不例外。可靠文字直接提取；图片区域、缺字、乱码或位置明显失配的文字层允许回退OCR。不能把存在文字层等同于字段抽取正确，也不能把可靠文字重新OCR作为默认步骤。

#### 6.10.1 字段定义（全部必抽，无子类型分组）

| key | label | 类型 | 必填 | 备注 |
|---|---|---|---|---|
| `name` | 姓名 | string | ✓ | 英文版为拼音，如 `Zhang San` |
| `gender` | 性别 | enum `M`/`F` | ✓ | 英文版 `Male`/`Female` 需映射 |
| `birth_date` | 出生日期 | date | ✓ | 中文版形如 `1979年7月10日`，须解析为 `1979-07-10` |
| `enroll_date` | 入学日期 | date | ✗ | 中文版"入学时间" |
| `graduate_date` | 毕（结）业日期 | date | ✓ | 中文版"毕业时间" |
| `school_name` | 学校名称 / 毕业院校 | string | ✓ | |
| `school_location` | 院校所在地 | string | ✗ | |
| `major` | 专业名称 | string | ✓ | |
| `education_level` | 学历层次 | enum `专科`/`本科`/`硕士研究生`/`博士研究生`/`其他` | ✓ | |
| `education_category` | 学历类别 | enum `普通`/`成人`/`网络教育`/`开放教育`/`自学考试`/`其他` | ✗ | |
| `study_mode` | 学习形式 | enum `普通全日制`/`业余`/`函授`/`脱产`/`其他` | ✗ | |
| `duration` | 学制 | string | ✗ | 原文保留，如"四年"、"2年"；不要强制转数字 |
| `graduate_conclusion` | 毕（结）业结论 | enum `毕业`/`结业`/`肄业`/`其他` | ✗ | |
| `certificate_no` | 证书编号 | string | ✓ | 17 或 18 位数字（2001 年后学历电子注册号） |
| `principal` | 校（院）长姓名 | string | ✗ | |
| `online_verification_code` | 在线验证码 | string | ✓ | 原样保留，去空白后按兼容规则检查，见6.10.3 |
| `report_update_date` | 更新日期 | date | ✗ | |
| `valid_until` | 验证有效期至 | date | ✗ | 见 6.10.4 |
| `report_language` | 报告语种 | enum `zh`/`en` | ✓ | 见 6.10.5 |

补充抽取说明：

- **证书编号**：2001 年后的学历证书为一组 17 或 18 位数字，即学历电子注册号（也称学校编号、电子注册号）。
  2001 年前或少数不足 17 位的，按证书实际编号原样保留，**不要因长度不符就判错**，仅标记为待复核。
- **姓名**：中文版为汉字；英文翻译件为拼音。**不得反向音译**，原样保留。
- **`education_level` 归一化**：原文可能是"硕士研究生"、"硕士"、"研究生"等，统一映射到枚举值。

#### 6.10.2 种类校验：防止拿错报告

只支持备案表。若特征词判定命中了**其他**学信网报告：

| 命中的报告 | 处理 |
|---|---|
| 《教育部学籍在线验证报告》 | `report_kind=OTHER_REPORT`，任务置 `NEED_REVIEW`，提示"收到的是学籍在线验证报告，请提供学历证书电子注册备案表" |
| 《中国高等教育学位在线验证报告》 | 同上，提示需提供备案表（学历），本报告证明的是学位 |
| 《中国高等教育学历认证报告》 | 同上，提示备案表与书面认证报告是两种文件 |
| 《中国高等教育学位认证报告》 | 同上 |
| 无法判定 | `UNKNOWN`，`NEED_REVIEW` |

错误码：`UNSUPPORTED_DOC_TYPE`。
**禁止把其他报告硬塞进备案表的字段模板抽取。**

#### 6.10.3 在线验证码：兼容检查与真实性分离

官方验证页公布2019-03-15起新申请报告的验证码升级为16位，兼容旧12位。该信息不证明所有历史/当前版本都是纯数字；本版不使用 `isdigit()` 作为拒绝依据。

- 保存原始分组文本 `online_verification_code`，另存去空白后的 `online_verification_code_normalized`，保留前导零及原始大小写。
- 本地兼容候选规则为 `(?:[A-Za-z0-9]{12}|[A-Za-z0-9]{16})` 的完整匹配，ASCII限定；这是工程兼容规则，不声称等同于官方完整编码标准。
- `code_valid=true`仅表示通过该本地格式检查，不表示已在线核验。未匹配且没有适用官方版本规则时为null、FORMAT=UNKNOWN并要求复核，不能一律判为假报告；只有适用已确认规则确实失败时为false及XUEXIN_CODE_INVALID。
- 缺失验证码按必填缺失处理。疑似O/0或I/1混淆保留候选，不能自动替换以凑格式。
- 官方验证入口：https://www.chsi.com.cn/xlcx/bgcx.jsp 。规则需记录来源与版本；新增规则后追加兼容样本，不能静默覆盖旧版本。

#### 6.10.4 有效期告警

以报告实际 `valid_until` 为准，不根据固定180天推算。与Asia/Shanghai当天日期比较，早于今天为过期，等于今天不判过期；解析失败/缺失时 `is_expired=null` 并要求复核，不能返回false误示有效。

过期只触发XUEXIN_DIPLOMA_EXPIRED，不直接阻塞本地抽取完成，也不代表学历失效。在线有效状态以人工核验结果为准。

#### 6.10.5 中英文版

支持中文版与英文翻译件。英文姓名保留拼音，不反向音译；日期按原报告格式解析；枚举映射到字典标准值。缺乏足够证据时保留原文并复核，不把模糊的“研究生”强行判为硕士或博士。

#### 6.10.6 人工在线核验

本版不接入自动联网验证或学信网爬取。后端仅返回固定官方verify_url与验证码，操作员显式打开网页输入或使用学信网官方App/报告验证小程序核验；二维码本身和本地格式检查均不作为真实性证明。

| manual_verify_status | 含义 |
|---|---|
| NOT_CHECKED | 尚未核验，本地完成状态不得暗示官方核验通过 |
| VERIFIED_OK | 操作员记录已在官方渠道核验一致 |
| VERIFIED_MISMATCH | 内容不一致，任务必须NEED_REVIEW，不能用一般问题确认覆盖 |
| VERIFY_FAILED | 无法完成核验，记录原因；不能据此判定报告真实或虚假 |

复核接口支持在NEED_REVIEW或COMPLETED状态记录核验，均需当前run_id/expected_revision、操作者和时间。核验结论绑定当前文件哈希及run_id；换文件/重跑后新的结论默认NOT_CHECKED，旧核验仅留历史。

#### 6.10.7 输入与来源

一个文件对应一个Task，所有类型一致。XuexinInfo.source_kind可为：

| source_kind | 含义与处理 |
|---|---|
| pdf_text | PDF全部内容使用可靠文字层提取 |
| scanned_pdf | PDF为扫描页/图片页，区域OCR；不是屏幕翻拍 |
| mixed_pdf | PDF混合原生文字和OCR区域，两者按页合并，保留各区域来源 |
| screenshot | 电子截图；按实际质量决定是否增强、裁边和OCR |
| screen_photo | 有证据的屏幕翻拍；可按需处理摩尔纹/反光/透视 |
| photo | 纸张等非屏幕拍照 |
| unknown | 无法可靠确定采集形态，不强行归类 |

无文字层产生PDF_NO_TEXT_LAYER告警；文字层提取质量异常产生PDF_TEXT_UNRELIABLE告警。均是处理信息，不是HTTP422错误；不能因回退OCR而直接FAILED。每页Page.extraction_method记录pdf_text/ocr/mixed，尚未处理为pending；不依据来源类型给固定置信度。

#### 6.10.8 截图和翻拍处理

先检测实际问题，再选择轻度增强、方向/透视校正、摩尔纹处理或裁边。原始合规图与处理图分别留存，禁止以会抹去细小字符的强滤波作为无条件步骤；不承诺反光遮挡可以恢复。

完整性检查结合页边、页脚、必填字段分布与内容中断证据；疑似缺底部/裁边产生XUEXIN_TRUNCATED，缺字段仍按复核规则处理。无法判断报告种类为UNKNOWN，仅当有明确其他报告标题/特征时才判OTHER_REPORT。图片清晰不等于字段正确，也不因来源是截图统一压低分数。

### 6.11 `GENERIC` 通用识别

不做强结构化，返回：

| key | label | 说明 |
|---|---|---|
| `doc_subtype_guess` | 猜测证件类型 | string，如"工作证"、"结婚证" |
| `doc_subtype_confidence` | 猜测置信度 | number \| null，仅已标定概率 |
| `doc_subtype_confidence_method` | 猜测置信度来源 | calibrated / unavailable |
| `blocks[]` | 文本块 | `{ text, page, bbox, confidence, confidence_method }`；page从1起，bbox可缺失 |
| `key_values[]` | 键值猜测 | `{ key, value, confidence, confidence_method }`；confidence可为null |
| `full_text` | 全文 | string |

前端对 `GENERIC` 的展示：**文本块列表 + 可编辑键值对**，不套用任何固定证件模板。

---

## 7. 置信度与复核规则

`confidence` 的统一含义为经过代表性标注集校准的字段正确概率。只有存在版本化标定方法且适用于当前字段/输入时才返回0..1，`confidence_method=calibrated`；否则返回null与unavailable。当前实测未提供这种标定，因此默认null，不从文件类型、校验码通过或模型自述填0.95/0.99。

此约定同样适用于MedicalItem、TextBlock、候选、Generic键值及分类分数。分类的confidence不可用时允许null，不能要求实现者编造数字。模型token概率若采集只作为内部原始证据，不能直接冒充字段正确概率。

后端生成 `review_issues[]`，每项issue_id在当前结果版本内稳定，含code/message/can_accept；`review_reason`只作主原因摘要，完整原因以issues为准。触发条件：

- 必填字段缺失或值无法读取：MISSING，必须修正/重传，不能接受问题直接放行。
- 适用规则失败：VALIDATION_FAILED；格式规则未知需明确UNKNOWN，不混成FAIL。
- 必填字段confidence=null：CONFIDENCE_UNAVAILABLE；已标定但低于0.85：LOW_CONFIDENCE。
- 银行卡候选修正：CORRECTION_PROPOSED/MULTI_CANDIDATES；必须选择/输入清楚可核对的值。
- 模型/跨字段/人工官方核验结论冲突：CONFLICT，必须解决；不能把两种结果拼成一个。
- 页面/区域仍截断、复读或缺失：INCOMPLETE_OUTPUT。允许保留部分结果供复核，但不能自动完成。
- 医疗项目无法判断异常、报告标记与数值比较不一致、必需源信息缺失或置信度不可用，同样生成项目级问题。

可接受问题只限操作员已对照原件确认的低/无置信度、明确可说明的规则例外。后端设置can_accept；缺必填、未选定候选、冲突、输出不完整、VERIFIED_MISMATCH不得接受。前端不能自行改can_accept、置信度或校验结论。

Review提交 `fields`/`items` 修正或 `accepted_issues=[{issue_id,reason}]` 明确确认问题。空提交不会清除待复核状态；只写note不代表确认。提交后重新计算校验、issues、items统计、summary和Batch状态。仍有阻塞问题则NEED_REVIEW，全部解决才COMPLETED；人工确认不会把confidence从null伪造为1.0。旧issue_id或过期revision返回409并要求刷新。

一般可选字段无置信度不独立阻塞Task，但错误值/来源冲突不能静默通过。所有曾经需要确认的问题都须有字段/项目/任务级可定位记录；不能只改Task状态跳过审计。

---

## 8. 错误、告警与部分结果

同步HTTP错误用于上传格式/大小、鉴权、请求结构及操作冲突；创建/重跑已返回202后，识别失败通过轮询查询的Task.error、Field.validation_error和review_issues反馈，不能再向已结束的上传请求返回422。

| 代码 | 场景与行为 |
|---|---|
| FILE_TOO_LARGE / UNSUPPORTED_FORMAT | 上传同步413/415 |
| INVALID_REQUEST | 请求结构、字段类型、未知当前项目/问题ID或不允许的编辑，HTTP422；已知旧版本问题ID使用RESULT_VERSION_CONFLICT |
| IMAGE_UNREADABLE / DECODE_FAILED | 无法解码，任务FAILED；若在接收阶段发现可同步422 |
| NO_DOC_EDGE | 无法定位边缘，保留可用完整图处理；不能仅凭无边缘判识别失败。若内容不可定位则待复核 |
| LOW_QUALITY / OVEREXPOSED | 严重到无法使用时FAILED并提示重传；可读但可疑区域继续并要求复核 |
| UNSUPPORTED_DOC_TYPE | 其他学信网报告或不支持的混装材料进入NEED_REVIEW；不能套错模板 |
| LUHN_FAILED / ID_CHECKSUM_FAILED / USCC_CHECKSUM_FAILED | 已确认适用的校验码失败，NEED_REVIEW；不是官方真实性结论 |
| BIN_UNKNOWN | 离线BIN规则未覆盖，UNKNOWN并复核，不代表卡不存在 |
| XUEXIN_CODE_INVALID | 已确认版本的规则失败；未覆盖版本使用UNKNOWN复核 |
| MULTI_CANDIDATES / MODEL_CONFLICT | 候选不唯一或模型结果冲突，NEED_REVIEW |
| OCR_TOKEN_LIMIT / OCR_REPETITION | 区域达到上限/复读；执行有界恢复后仍失败则NEED_REVIEW并保留部分结果，完全无可用结果则FAILED |
| MISSING_REQUIRED_FIELD | 缺必填，NEED_REVIEW |
| EXTRACT_TIMEOUT | 运行预算耗尽，终止本次运行，FAILED并保留部分结果/已花耗时；请求层不等待180秒再返回504 |
| WORKER_INTERRUPTED | worker/机器退出造成运行中断，恢复检查后FAILED，保留可用部分结果与中断记录，用户可显式重跑；不伪造完整耗时 |
| TASK_NOT_REVIEWABLE / INVALID_STATE | 当前状态禁止该操作，HTTP409 |
| RESULT_VERSION_CONFLICT | run_id/revision过期或问题ID过期，HTTP409，刷新后再编辑 |
| FORBIDDEN_REVEAL | 未授权查看完整值/未脱敏预览或导出，HTTP403 |
| INTERNAL_ERROR | 同步服务故障HTTP500；异步故障写Task.error |

`PDF_NO_TEXT_LAYER`、`PDF_TEXT_UNRELIABLE`属于Warning.code，不属于HTTP错误；回退OCR不等于失败。v1.7移除RESULT_NOT_FULL，abnormal_only不再省略全量识别。

字段校验另支持 `INVALID_DATE` 等，具体枚举以OpenAPI为准。多个问题用review_issues完整表达，不能因Task.error只能放一个对象而丢失其他字段问题。

---

## 9. 脱敏与权限

身份证号默认保留前3后4，银行卡号默认仅保留后4；体检姓名在列表页仅显示姓和掩码。结构化体检数值不脱敏。营业执照业务字段默认不脱敏；若原文件混入其他人的身份证/银行卡，不能因doc_type是营业执照就绕过敏感区域处理。

脱敏覆盖全部输出路径：Field.value/value_masked、source.raw_text、候选值、Generic全文/键值、Task摘要、错误详情、复核回显、导出及预览图。编号字段在默认响应中的value只能是掩码或null，不能同时在其他属性返回原值。日志不记录完整身份证号、卡号、CVV或未脱敏的请求/响应体；审计diff使用字段名和掩码，并将确需保存的完整业务历史在受控加密存储中单独保留。

| 角色 | 权限 |
|---|---|
| viewer | 查看、掩码预览和掩码导出 |
| operator | viewer + 上传/追加、复核、候选选择、reveal、未脱敏预览/导出、重跑/取消/拒绝/恢复/替换 |
| admin | operator + 删除；系统配置与用户管理通过部署侧管理，首版无未定义的Settings页面/API |

- `X-API-Key`鉴权映射具体user_id/role，不能所有操作者共享身份却记录为个人审计。凭证由本地部署侧安全发放，不依赖内网网关，不在前端打包文件硬编码管理员密钥。
- `POST /tasks/{id}/reveal`只返回被请求的身份证号/卡号，要求operator及以上、非空reason并审计；掩码60秒是前端展示行为，不声称已发出的值可被服务端撤回。
- `GET /tasks/{id}/preview`默认masked=true。masked=false要求operator、非空reason并审计；raw/corrected/enhanced均受控。字段bbox只对corrected完整页有效，其他stage只展示图片不叠加该bbox。请求绑定run_id/result_revision；过期版本不能默默展示当前另一页。
- `/export?masked=false`是与reveal并列的**显式完整值访问入口**，同样要求operator、reason和审计；不是reveal的隐式绕过。下载按权限生成，不复用其他用户未脱敏缓存。
- 所有完整值及含完整敏感信息的存储产物由统一存储访问模块管理（模块及接口名称不限定），敏感字段/产物加密，密钥不存于业务表或日志；保留期结束清理文件、缓存、结果和含原值的历史。脱敏审计事件可保留，但不得用它绕过保留期保存原始号码。
- CVV/CVC/CVN2等安全码不属于提取字段。接收卡片图片时，在持久化原图、预览、OCR缓存前遮盖可定位的安全码区域；无法可靠遮盖的卡片输入拒绝保存并提示提交已遮盖图片。不把未清理的卡片背面当可长期保存原图。CVV不得出现在字段、候选、日志、缓存、审计或导出中。

---

## 10. 边界约定

| 项 | 值 |
|---|---|
| 单文件大小 | ≤10MB |
| 批次当前文件数 | ≤20；追加也受此限制 |
| 单次上传总大小 | ≤50MB；追加/替换同样校验 |
| 支持格式 | JPG/JPEG/PNG/HEIC/PDF；解码后核验实际格式，不信任扩展名；双图 HDR JPEG 仅在明确验证 Apple/ISO/Adobe 辅助亮度图时按一张主照片处理 |
| PDF分页规则 | 一文件一Task；Page/Region内部处理并文件级汇总，所有类型一致 |
| 保留期 | 默认7天；覆盖业务文件、结果及含原始信息的运行历史，不只清理列表记录 |
| 运行预算 | 单Task180秒活动墙钟预算，自worker开始处理到完成；含解码、布局、模型加载/切换、重试与落盘，不含队列等待 |
| 幂等 | 同Batch同文件哈希复用已有Task并告警，不新建重复Task；跨Batch允许重复并告警，但不声称已经去重 |

会话启动加载/预热在Task领取前执行，使用独立有界启动预算并单列耗时；期间接受的上传先持久化排队，不伪装为OCR执行。已领取Task触发的按需加载、切换及恢复仍计入上述180秒，不改成每区域180秒；启动失败不得使排队任务无限等待，应按实际路由能力明确处理失败原因。

批次哈希基于接收文件内容，保存安全处理产物的哈希另记。替换与旧输入、参数、模型版本分别关联；不能只按文件哈希复用不同参数下的结果。不同人的材料不可只凭同名自动合并；没有明确归属时仅给完整性疑点，不补写姓名或号码。

只提供网页人工上传入口，不新增邮件或面向外部的自动接入。Batch/Task不添加“接入来源”source或email_*属性；**Field.source等识别溯源字段必须保留**。

每次尝试记录模型revision、依赖版本、输入哈希、页/区域、prompt/参数、输出token、终止原因和GPU峰值。时间分为队列、加载、预处理/布局、识别、重试及Task端到端；预热单列，不把失败成本删掉。重启未完成记录为interrupted而不是虚构时长；睡眠覆盖的记录保留原值并排除有效速度统计。生产无参考答案时accuracy=null，不能用confidence代替准确率。

## 11. 业务流程

### 11.1 上传与质量反馈

客户端对可解码图片做格式/大小/重复、清晰度和亮度预检；PDF/HEIC在浏览器无法解码时跳过像素质量检查，不能把它们当损坏文件。清晰度/亮度阈值需样本标定，客户端提示是建议性的，可选择仍然上传；文件大小/类型硬限制始终由服务端执行。

上传与 worker 使用相同图片准入规则。部分手机照片名为 JPG/JPEG，解码器实际识别为 MPO：仅允许恰好两图、首图为 baseline primary JPEG、次图明确为受支持的 Apple HDR gain map、ISO 21496-1 版本0或Adobe版本1.0的亮度辅助图；Adobe分支还需核对主图目录中的Primary/GainMap JPEG配对及辅助图的SDR声明。两图均解码及核验像素上限，OCR只使用首图的SDR视图，原始接收字节、哈希和加密原件保持不变，不重建HDR亮度；MotionPhoto附带视频保留在原件中，不作为材料页识别。即使解码器把带MP索引的照片返回为单帧JPEG，也需重新验证其多图结构。未知多图MPO、动画PNG及多帧HEIC同步返回415 `UNSUPPORTED_FORMAT`，提示另存单图或转PDF；不得默默遗漏其他材料页。格式支持及上传成功不代表字段识别正确。

上传返回202 + batch_id/task_ids。首版轮询现有Batch/Task查询接口获取进度；建议运行期间约2秒刷新一次，离开页面停止，断线后退避，重连重新查询。无运行任务时停止Task自动轮询（NEED_REVIEW等待人工操作，不持续轮询），提交复核/追加/重跑后主动刷新并按状态恢复。启动尚未稳定时，即使没有Task仍轮询`/health.runtime`展示加载/预热，稳定后停止无必要轮询；runtime缺失不当作ready。除公开health外，所有查询和预览携带鉴权，不把API Key放入URL。SSE后置，不属于v1.9必需接口；未来引入时另行更新契约，继续遵守版本与脱敏规则。

失败文件就地重传调用 `POST /tasks/{task_id}/replace-file`，Batch/Task ID不变，产生新run_id；历史保留，当前字段重新识别，旧修正不能自动覆盖新照片。新识别的页数/类型可变化，前端应重新读取pages和字典。

### 11.2 双模型处理流水线

```
0. 接收文件 → 安全处理与合规持久化 → 一个文件一个Task
1. 解码并建立Page → PDF逐页/区域评估文字层质量
2a. 可靠文字层 → 直接提取文字和位置
2b. 图片或异常文字区域 → 方向/布局 → 原分辨率裁剪 → 识别
3. 按材料类型分流：证件/银行卡GLM，体检Paddle；GPU单任务
4. 字段/表格结构化 → 适用编号规则与跨字段校验
5. 体检不完整输出 → 有界软停止/原图备用模型；证书 → 既有输入修复/备用模型
6. 按页、区域归属合并；报告级统计；原始尝试保留
7. 无阻塞问题COMPLETED，否则NEED_REVIEW；不可恢复技术失败FAILED
```

表格优先保持完整行列，超长表分块时保留表头与行归属，不只按固定高度切断内容。表内重复检测框依据几何包含及来源归属去重，保留去重证据；不能按文字相同删除不同项目的单位或结果。布局须覆盖全部可读内容，保留未覆盖区域及失败标记；截图背景中的学校等文字不能仅因未检出框而静默丢弃。检测不确定或覆盖不足时执行有界整页/区域回退，仍失败则保留证据并要求复核，不声称完整。方向处理及裁剪坐标须映射回完整页面，PDF可靠文字优先不因采用布局而改变。两模型对同一区域出现冲突必须保留候选和来源，不能把“通过校验”当作自动选择依据。没有检测到证件四边不等于无法读图，可保留完整可读页进入布局；增强不应覆盖原图。

保留简单证件的整页识别路径，不将所有材料强制裁图。出现覆盖不足或漏字段提示时，先检查并补充整页/缺失输入，属于既有输入修复重试；之后才使用备用模型，不让两个模型重复处理同一份漏裁输入后误判证据一致。所有区域非空且正常EOS仅证明这些区域完成生成，不能证明整页覆盖完整。

同一Task内可复用明确EOS、非空且无错误的完全相同输入结果：键包含checkpoint revision、模型、任务/提示词、编码输入hash、预处理、tokens与生成预算。未知revision、截断、空输出、失败不缓存，不跨Task/重跑复用。每次命中绑定当前页面/区域/bbox，记录cache_hit与原推理关联；命中不复制推理时间或GPU峰值，不按图像相似、文字相同或文件名删除区域。

学信网先判报告种类，仅备案表抽取本字段模板；确认其他报告为OTHER_REPORT，证据不足为UNKNOWN，均进入复核。可靠PDF文字禁止不必要OCR，但质量不可靠时允许区域回退；不能按“只要有文字层就永久禁OCR”实现。

规则抽取可使用文本键值对齐和表格结构，不回到全文正则硬凑字段。模型结构化抽取的字段归属、缺失值和多证件情况须用实际样本验收；schema能解析不等于抽取正确。

### 11.3 人工复核

左侧显示当前run的corrected完整页，支持翻页及区域高亮；默认掩码，显式授权后查看完整敏感区域。右侧展示fields、items、members及完整review_issues。

- 银行卡候选只是建议；用户显式选择/输入后作为字段修正提交，服务端重新校验并记原值/来源。
- 体检更新按item_id，新增走added_items，删除走removed_item_ids；同名不同页项目不能相互覆盖。同一请求不能更新并删除同一ID，未知ID返回422，不忽略。
- 医疗新增项由后端分配item_id；前端不可提交confidence、统计、校验结论或severity。报告原文/标记可由用户对照更正，派生字段由后端重算。
- 户口本成员仍按当前run内索引定位，expected_revision防止旧索引误改；不跨run复用索引修正。
- 提交包含run_id/expected_revision、修正项以及明确接受的问题ID和非空原因。剩余问题决定最终状态，不是一提交就完成。
- 学信网OTHER_REPORT/UNKNOWN不能通过空复核变成COMPLETED；应重传正确材料或修正类型重跑。
- 提交成功刷新TaskResult、revision与预览；冲突时保留本地未提交输入，提示刷新，不自动覆盖后端新结果。

## 12. 前后端分工边界

| 职责 | 归属 |
|---|---|
| 状态机推进、置信度计算、`need_review` 判定 | **后端** |
| 阈值判断、校验规则（Luhn/身份证校验位/USCC/学信网验证码/日期逻辑） | **后端** |
| 脱敏与掩码生成 | **后端** |
| 原始异常标记保留、适用区间比较及可选 `deviation` 算术说明 | **后端**，不推断通用severity |
| PDF逐页/区域文字层质量、直接提取或OCR路由 | **后端** |
| 学信网验证码去空格与合法性判定、`is_expired` 计算 | **后端** |
| 状态渲染、阈值展示（只读后端结果） | 前端 |
| 用户文案翻译（错误码 → 中文提示） | 前端（文案表由 `GET /doc-types` 或 i18n 下发） |
| OpenAPI生成客户端类型、契约一致性检查 | 前后端各自接入；mock按需选一种 |

---

## 13. 给实现模型的硬约束

1. 满足本版SPEC和OpenAPI的业务与接口要求；内部技术决策按第4节及ARCHITECTURE.md执行。用户已授权的修改直接执行；历史记录不覆盖当前正文。
2. 影响业务含义、公开接口、数据安全或部署成本的歧义需确认；内部可逆选择自主完成。不假定未实现的逐字置信度、字框、联网查询或第三个大模型可用。
3. 仅网页上传入口，Batch/Task没有邮件接入来源字段；Field.source是合法且必要的识别证据。
4. API snake_case；前端不强制大小写转换。字典来自GET /doc-types，生成类型不得手改，服务端模型须通过契约检查。
5. 创建/重跑/恢复/替换为异步202；复核是短事务并返回重新校验后的状态，不启动无界同步模型推理。
6. 一文件一Task，PDF内部多页处理；相同run/revision中的页面、区域、字段证据必须一致。
7. 所有PDF优先使用可靠文字层，只有无文字层/异常或图片区域才OCR；不按文档类型限制直接提取。
8. 默认双模型驻留，加载和预热串行，成功后允许跨模型识别重叠、同模型 FIFO 排队；备用单驻留切换确认旧进程树退出。任务领取后的队列等待、文件进程启动和全部页面共同消耗180秒，20秒医疗软预算从实际生成开始。取消/硬超时先在短事务中隔离精确run，再于事务外停止该文件进程及它占有的模型请求，确认后才恢复状态；未知退出全局fail-closed。模型与布局依赖隔离、revision固定，重试有界，失败尝试保留并计时。
9. 截断、复读、缺页、混装材料或候选冲突不能自动COMPLETED；停止生成不等于完整输出。
10. 银行卡校验不负责猜号码；任何改号建议必须人工选择，未标定置信度为null。
11. 体检完整识别后过滤视图，保留原始结果/箭头/参考区间；不把POSITIVE一律视为严重，不实现无依据通用severity。
12. 复核必须检查run_id/revision，逐问题确认或修正后重新校验；缺必填、冲突、未选定候选、输出不完整和学信网核验不一致不能直接确认通过。
13. 所有默认输出路径脱敏，包括原文、候选、轮询响应和图像预览；显式完整预览/导出/reveal需权限、原因与审计。
14. CVV不抽取、不持久化、不返回；卡片安全码遮盖无法保证时拒绝保存并要求重传已遮盖图。
15. v1不做自动学信网核验；OTHER_REPORT不套备案表模板，证据不足为UNKNOWN；验证码格式通过不等于官方验证通过。
16. 自动指标的准确率必须基于人工参考集；生产未标注材料accuracy=null。模型自报置信度或格式检查不能充当准确率。

---

## 14. 验收标准

以下是实现验收用例，不是本轮文档修订已经通过的模型效果承诺。模型效果需记录固定样本、参考、模型版本及失败结果；当前参考未经人工双审的局限需保留。

### 文件、PDF与识别

- [ ] 上传一张身份证人像面，字段值与参考一致；无标定时confidence=null且必填进入复核，人工确认后完成。
- [ ] 身份证号码改错一位，触发适用校验失败；不得自动补成另一合法号码。
- [ ] 倾斜/反光银行卡保留原图证据，局部重识别后候选仍需人工选择；不能以唯一Luhn候选自动完成。
- [ ] BIN库未覆盖的卡号为UNKNOWN/待核对，不声称卡无效；6/8位BIN按适用版本匹配。
- [ ] 文本型体检PDF与备案表PDF均走可靠文字直接提取，日志证明对应区域未调用OCR。
- [ ] 扫描PDF走OCR并告警PDF_NO_TEXT_LAYER，source_kind=scanned_pdf，不误标screen_photo。
- [ ] 混合PDF原生文字与OCR区域合并、保留独立溯源，文件仍只有一个Task。
- [ ] PDF有乱码文字层，异常区域允许回退OCR并告警PDF_TEXT_UNRELIABLE；不能强制赋高分。
- [ ] 一个多页体检/户口本文件汇总为一个Task，pages从1连续编号，items/members归属正确。
- [ ] 一个文件含无关证件，进入待复核并提示分别上传，不默选一份、不把同名字段拼接。
- [ ] Paddle限长/复读触发有界区域恢复，仍失败保留原输出并标记未完整；同一模型并发不超过1，成功双驻留时跨模型最多2。
- [ ] 营业执照USCC按适用算法校验，CHECKSUM=PASS不等同真实登记且不擅自提高confidence。
- [ ] 通用识别返回可复核原文/键值，但敏感内容仍受统一脱敏策略约束。

### 医疗项目与复核

- [ ] abnormal_only=true仍完整识别及存储，显式items_filter=all无需重跑、无RESULT_NOT_FULL。
- [ ] 过滤只影响items，不改变同一完整结果的stats；不完整结果统计留null，不能把未输出计为正常。
- [ ] 同名同类别不同页项目有独立item_id；按ID修改/删除正确，不按名称误改其他行。
- [ ] 新增、删除、修正项目后重新计算统计；同ID同时更新和删除、未知ID返回422。
- [ ] `>5.0`保留比较符且value_num=null，不按精确5.0比较；缺单位/参考区间依据时不强判NORMAL。
- [ ] 阳性事实、报告异常标记和严重程度分开；响应不存在通用severity字段。
- [ ] 空复核提交不能清除待复核状态；明确接受允许确认的问题须有非空reason。
- [ ] 修正后仍缺必填或存在冲突，状态仍NEED_REVIEW；不能通过accepted_issues覆盖不可接受问题。
- [ ] 人工确认不把confidence改为1.0；审计区分原识别、修正和确认。

### 学信网

- [ ] 原始备案表PDF按字典提取全部适用字段，文本位置映射正确；截图/翻拍/扫描件按实际来源处理。
- [ ] 12/16位ASCII字母数字验证码通过本地兼容格式检查，保留分组/前导零；未覆盖格式标UNKNOWN待核对，不误作真实性失败。
- [ ] 学籍/学位/认证等其他报告为OTHER_REPORT，不抽取备案表字段；空复核不能变完成。
- [ ] 种类证据不足为UNKNOWN；纸张扫描无摩尔纹不能强制做屏幕去摩尔纹。
- [ ] 有效期缺失is_expired=null；实际过期触发告警，但不把学历判失效。
- [ ] manual_verify_status=VERIFIED_MISMATCH始终阻塞；换文件/重跑后默认NOT_CHECKED，旧核验保留历史。

### 状态、并发与权限

- [ ] 一次上传3个文件产生3个Task；每文件页数不改变Task数量；追加/替换同样执行容量限制。
- [ ] 客户端像素质量预检无法解码PDF/HEIC时跳过，不把正常文件误拒绝。
- [ ] replace-file保留Task/Batch ID但更新run_id；即使reset_review=false也不自动套用旧文件字段修正。
- [ ] 所有结果修改验证run_id/expected_revision；重复提交新增行不产生重复，过期写返回409。
- [ ] 旧worker的结果和进度不能覆盖新run、取消后的状态或人工复核版本。
- [ ] cancel接受后仅cancel_requested=true，确认停止后才CANCELLED；完成先提交时取消409。
- [ ] Batch全取消为CANCELLED；全失败/拒绝为FAILED；有完成与其他终态为PARTIAL；有NEED_REVIEW为PROCESSING。
- [ ] viewer无法获取未脱敏值、原文、候选、预览或导出；operator显式完整访问需要原因并记录审计。
- [ ] 预览与结果绑定同一run/revision；非corrected图片不得套用corrected bbox高亮。
- [ ] 未遮盖CVV不得进入持久化原图、OCR文本、缓存、日志或导出；无法处理时拒绝保存。
- [ ] 7天清理覆盖含敏感值历史与缓存；仅保留脱敏审计，不保留可恢复原值。
- [ ] 计时包括失败和重试，睡眠干扰单列；未标注生产数据不虚构准确率。

---

### 单机运行与维护

- [ ] 不安装PostgreSQL、Redis、Celery也能完成首版上传、排队、识别、复核及导出。
- [ ] 以约50个混合文件验证单机流程，记录页数、区域数、排队耗时和失败；不能用每日文件数宣称推理吞吐已达标。
- [ ] API重启后排队任务及复核记录仍存在；worker重启按5.1节处置中断，旧子进程未停止前不启动新推理。
- [ ] 重复启动worker不能绕过单实例模型所有权；跨模型并发受各自FIFO约束，上传与复核数据库事务可完成，不持有跨推理或进程停止等待的写锁。
- [ ] 文件保存或数据库提交失败不返回虚假202；重启能识别和清理未关联的临时产物。
- [ ] 执行数据库及文件备份恢复检查，恢复后记录和文件对应；过期敏感数据不会通过备份长期保留或重新上线。
- [ ] 前端只使用轮询即可完成全部首版流程，无需SSE服务；NEED_REVIEW时不空转持续轮询。
- [ ] /health检查db、worker、storage；worker可响应调度但模型尚未加载不算worker故障，worker退出应报告degraded；可选runtime单独展示启动、有效驻留模式及模型能力，不能用health.status=ok暗示全部模型ready。
- [ ] 界面先于加载显示，GLM与Paddle依次加载预热后默认双驻留，各自队列可重叠；启动、预热、任务排队、模型队列等待和识别峰值分别记录。
- [ ] 资源不足仅有界降为single_resident，依赖错误不误判OOM；轮询/新任务不触发自动重试循环，未验证硬件不显示保证可用。
- [ ] 正常退出、launcher异常退出、模型挂起和应用重启均核验两个owned模型进程树回收；旧树未退出前不得开始单驻留切换。
- [ ] 自动分区验证完整覆盖、表内重复框、旋转及截图背景文字，遗漏/失败进入审计及复核；自动布局单驻留基准不冒充双驻留验收。

## 15. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.10 | 2026-09-30 | 增加第二阶段实际能力边界和可选诊断关联字段error_id/request_id/stage；创建批次必选三种已实现材料类型；loopback示例端口统一8765。完整复核、导出及其余类型仍为后续目标，未降低CVV等完整业务验收要求。 |
| v1.0 | 2026-09-29 | 初版冻结 |
| v1.1 | 2026-09-29 | 新增 `BUSINESS_LICENSE` 营业执照类型（6.9 节）：14 个字段、GB 32100-2015 统一社会信用代码校验位算法、竖版/横版 ROI 区分、公开信息不脱敏例外；新增错误码 `USCC_CHECKSUM_FAILED`；原 6.9 `GENERIC` 顺延为 6.10 |
| v1.2 | 2026-09-29 | **移除邮件接入**：删除 `source` 字段与 `EMAIL` 枚举、删除 `email_from/email_subject/email_received_at`、删除 IMAP 模块与邮件轮询配置、删除"双入口统一"条款；新增 11.1 节**客户端即时质量预检**（清晰度/过曝/重复/格式/大小）与**单文件就地重传**机制；新增 `POST /batches/{id}/append` 与 `POST /tasks/{id}/replace-file`；完整性告警的按钮由"生成重拍邮件"改为「补充上传」 |
| v1.3 | 2026-09-29 | 新增 `XUEXIN_DIPLOMA_TABLE` 学信网报告（6.10 节）：6 种 `report_kind` 子类型、A–E 五组字段、**在线验证码 12/16 位双规格**（2019-03-15 升级）、有效期告警、**明确不做自动联网验证**（无官方 API，改人工核验 + `manual_verify_status`）；流水线新增 **A 路径（PDF 文本层，不 OCR）/ B 路径（拍照类）入口分流**；学信网 PDF **不按页拆分**；新增错误码 `XUEXIN_CODE_INVALID`、`PDF_NO_TEXT_LAYER` 与告警码 `XUEXIN_DIPLOMA_EXPIRED`；原 6.10 `GENERIC` 顺延为 6.11 |
| v1.4 | 2026-09-29 | **学信网范围收窄为《教育部学历证书电子注册备案表》一种**：删除 6 种 `report_kind` 子类型与 A–E 字段分组，改为 20 个固定字段（6.10.1）；学籍/学位在线验证报告、学历/学位认证报告一律 `OTHER_REPORT` 并 `NEED_REVIEW`，**禁止套用备案表模板抽字段**；新增 `report_language`（zh/en 中英文版差异与枚举映射）、证书编号 17/18 位兼容说明；A 路径新增 A3 种类校验步骤；补充"只用学信网小程序扫码"的防伪提示 |
| v1.5 | 2026-09-29 | **命名收窄**：doc_type 由 `XUEXIN_REPORT` 改为 **`XUEXIN_DIPLOMA_TABLE`**（原名过宽，易让模型误以为覆盖学信网全部报告）；告警码 `XUEXIN_REPORT_EXPIRED` → `XUEXIN_DIPLOMA_EXPIRED`；`XuexinReportKind` 更名为 **`XuexinKindCheck`**，枚举值改为 `DIPLOMA_TABLE` / `OTHER_REPORT` / `UNKNOWN`（避免与 doc_type 同名混淆，语义变为"这份 PDF 是不是备案表"）。**无功能变更，纯命名** |
| v1.6 | 2026-09-29 | **学信网接受 JPG 截图，不强制 PDF**：`source_kind` 由 `pdf_text`/`ocr_fallback` 两态细分为 **`pdf_text` / `screenshot`（电子截图，上限 0.92）/ `screen_photo`（翻拍屏幕，上限 0.85，须去摩尔纹、禁二值化）**；新增 6.10.8 截图与翻拍处理要点（摩尔纹判定、完整性检查、种类校验降级规则）；新增告警码 `XUEXIN_TRUNCATED` 与字段 `likely_truncated`；明确**不因"是截图"就整体压低置信度**（电子截图很清晰）；新增硬约束 15/16 |

| v1.7 | 2026-09-29 | 经用户授权修订：一文件一Task及Page/Region；全PDF可靠文字优先；双模型串行分流与有界重试；银行卡候选须人工确认、BIN未覆盖为UNKNOWN；置信度未标定为null；医疗全量识别后过滤、稳定item_id、取消通用severity；CANCELLED及Batch聚合；run_id/revision并发保护与复核重校验；原文/候选/预览/导出统一脱敏；学信网兼容校验与真实性分离；修正邮件与source歧义，更新验收。v1.7包含不兼容的字段与行为变化，前后端须同步重新生成类型。 |
| v1.8 | 2026-09-29 | 按每日约50文件、单机少量操作人员重写工程约束：业务/API/架构职责分离；默认SQLite、本地文件及独立串行worker，移除强制PG/Celery/Redis与固定目录/前端转换；新增ARCHITECTURE.md记录可调整选型；首版轮询并移除SSE接口；健康检查redis替换为worker，新增WORKER_INTERRUPTED与重启恢复验收。健康检查字段及接口范围有变化，客户端按1.8.0重新生成类型。 |
| v1.9 | 2026-09-29 | 用户改选本机默认dual_resident：界面先显示，GLM/Paddle串行启动加载预热后双驻留；资源不足有界降为single_resident，全部GPU工作共享执行通道；补充launcher退出监督、硬件未验证边界及自动布局覆盖/去重要求。health新增可选runtime展示启动与有效模式，未增模型管理接口；保留180秒整Task预算并独立记录会话启动开销。设计尚待运行时实现，自动布局测试仍是串行单驻留基准。 |

| v1.11 | 2026-09-30 | 新增独立report_summary及同标题清单数量校验；未显式声明为null、覆盖未证实为unverified，不与实验室异常计数对账；FieldSource新增可选bbox_kind，前端兼容旧结果并只读展示摘要及来源页码/粒度，保持医疗统计、复核和脱敏边界。 |

| v1.12 | 2026-10-08 | 用户授权优化体检超时：20秒软生成预算、主备最多各一次、仅Task内精确EOS复用、保留180秒硬监督与不完整来源；公开DTO/schema未改，OpenAPI保持1.11.0。记录未来Mac Studio集中部署及远程访问待选，当前Windows/CUDA与loopback边界仍有效。 |
| v1.13 | 2026-10-08 | 用户授权本次Windows测试版跨模型并发：成功双驻留后两类文件独立进程、GLM/Paddle各自FIFO；单模型排队、串行加载预热、定向停止与短事务run隔离。加入临时本地原图对照界面；公开DTO未变，OpenAPI仍1.11.0。Mac M3 Ultra/96GB确认，迁移仍待实现。 |
