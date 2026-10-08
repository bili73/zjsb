# OCR 设计、验证与业务实施计划

- 更新日期：2026-10-08
- 依据：SPEC v1.13、OpenAPI 1.11.0（公开DTO未变）、ARCHITECTURE.md
- 当前阶段：第二阶段最小业务链路已落地；真实业务验收结果单独记录，不能以代码、单测或旧离线成绩代替。
- 最新验收：[Windows并发与临时工作台](output/concurrent-pipeline-20261008-v1/REPORT.md)：9/9任务结束、无Task超时，11跨模型请求重叠、0同模型/启动重叠；三报告active94.101/110.905/127.935秒，Task排队与上传等待分开。证书37/39、血常规72/72仍为固定子集，结果NEED_REVIEW、医疗stats/confidence null。269后端CPU、31前端、build与12项合成浏览器检查通过。旧[v2串行](output/current-pipeline-acceptance-20261008-v2/REPORT.md)、[v1超时](output/current-pipeline-acceptance-20261008-v1/REPORT.md)、[第二阶段验收](output/phase2-acceptance-20260930/REPORT.md)保留，缓存条件未控制不能把耗时变化归因并发。
- 字段抽取诊断：[GLM 模板对比](output/schema-extraction-20260930-v2/REPORT.md)。复用现有模型改善字段召回但增加误填；尚未替换生产流程，不能按填充率自动放行。
- 当前部署：Windows/CUDA、本机loopback；默认双驻留成功后GLM/Paddle独立FIFO、跨模型并发，启动加载预热仍串行，备用单驻留串行。用户确认未来Mac Studio M3 Ultra / 96GB，访问方式待定，MLX/远程鉴权未实现。Chandra不进入链路。

## 1. 已有证据及其边界

离线自动布局 v1 完成固定九页对照，报告见 [自动布局实验](output/auto-layout-20260929-v1/REPORT.md)。冻结字段结果为 GLM 125/130、Paddle 122/130；共同七困难页为 115/118、112/118。两个简单对照合计由各 12/12 退化为各 10/12，cert-001 漏姓名和专业。每模型 91 区域均非空 EOS、无复读，也不能证明整页覆盖完整。保留重复单位区域、背景学校漏检和正常证件退化证据，不删除失败分母。

[两模型本机重测](output/two-model-retest-20260929-152421/REPORT.md)来自 32 GB 内存、RTX 3060 12 GB 机器，各 41 次正式测量及一次预热；它不能证明双驻留、16 GB 人资机器或 CPU-only 可用。第一阶段运行时另有合成输入下的启动、驻留复用与退出证据，入口见 [RUNTIME.md](RUNTIME.md)。

这些实验与当前生产准备代码分开：离线布局模型不是已接入业务流水线的组件，人工坐标不是通用自动能力，模型正常结束不等于字段、项目或全报告完整。

## 2. 当前已实现

| 部分 | 当前实现 | 明确限制 |
|---|---|---|
| 启动与模型 | `start.cmd` / `start.ps1`、Windows Job 监督、双/单驻留、health 状态页 | 无公开模型切换或关机 API；实际人资配置待验 |
| 鉴权 | 本机生成 operator Key，`access-key.cmd` 查看，API Header 验证角色 | 前端 Key 只内存；无用户管理平台 |
| 上传与持久化 | 1–20 文件/批、单文件 10 MB、合计 50 MB；SQLite + SQLAlchemy + Alembic | 只体检报告、毕业证、学位证；JPG/PNG/HEIC/PDF；不接银行卡 |
| 处理与证据 | 一文件一 Task；页与区域证据；可靠 PDF 文字优先、扫描/不可靠区域 OCR | PDF 质量判定和字段整理仍为保守启发式，需真实材料验证 |
| 输入分区 | 简单证书整页，长体检区域在水平白带切片，无安全切点则保留整区 | 未实装 PP 布局模型；不保证医疗表格语义边界与全量覆盖 |
| 状态与并发 | 双驻留后两类文件进程与两个模型FIFO；原子run/revision、定向停止、短事务stop fence | 单模型排队；共享显卡可能增大耗时，不承诺双倍吞吐；单驻留仍串行 |
| 预算与复用 | 领取后180秒含CPU启动/模型等待；医疗生成20秒；主备各一次；Task内EOS缓存；独立watchdog | 软停止不等于完成；硬停止模型本会话禁用，其他模型保留；未知退出全局fail-closed |
| 前端 | 旧临时界面已移出，独立重构中 | 当前通过 API 测试；旧验收不代表重构界面通过 |
| 结果保守性 | 当前成功处理均为 NEED_REVIEW；confidence null；医疗覆盖未确认时 stats null | 不宣称自动审核或临床判断，不以漏项推断正常 |
| 安全与留存 | 敏感业务字段/产物 AES-GCM，部署密钥由同 Windows 用户 DPAPI 保护；七天清理 | 查询状态/时间/ID 未作整库加密；跨用户迁移和备份恢复演练待做 |
| 诊断 | 早期启动、进程、HTTP 和界面安全错误记录；错误编号；离线诊断 ZIP | 不含材料正文/Key/原始异常，不自动截桌面；断电最后事件不保证写入 |

本机业务资料是临时处理数据，七天留存服务于处理与恢复，不作为长期档案。当前业务导出尚未实现，不能描述为“操作员已可导出归档”。清理只覆盖应用管理的资料，不触碰旧样本、基准和用户原始目录。

## 3. 代码入口与运行规则

- `backend/ocr_app/launcher.py`：单实例执行锁、业务准备、轻量 HTTP 和受监督 runtime；`api.py` / `routes.py`：health 与 `/api/v1` 鉴权业务入口。
- `business.py` / `task_store.py` / `db.py` / `storage.py`：输入准入、持久化、版本保护、恢复、加密与到期清理。
- `documents.py` / `pipeline.py` / `extraction.py`：PDF/图片解码、保守分区、证据留存与字段/项目整理；`runtime_worker.py` 是唯一任务和 GPU 调度入口。
- `client.py` / `runtime.py` / `model_queues.py` / `task_scheduler.py` / `task_worker.py`：双模型FIFO、隔离文件进程、定向停止；`model_worker.py` / `winjob.py`：模型协议和Windows退出监督。
- `frontend/`：旧目录已移出；本机恢复副本位于 `output/frontend-retired-20261008-v1/frontend`，不纳入 Git。重构可创建新目录，技术选择由重构实现决定。启动入口不再依赖前端产物。
- `diagnostics.py`、`collect-diagnostics.cmd` 与前端诊断模块：安全错误关联和离线收集；具体使用见 [RUNTIME.md](RUNTIME.md)。

会话启动及Task领取前排队单列；领取后的CPU启动、模型队列等待、解析和所有区域共享180秒。watchdog约181秒定向停止精确run，等待退出不持有DB写锁；失败确认才全局fail-closed。成功双模型并发中故障模型本会话禁用，健康模型保留，应用重启恢复故障能力。任何旧树未确认停止前不得复用模型进程。

## 4. 当前验收工作

版本核查、卡证专用模型调研及串行双模型字段实验见 [Paddle 版本对照](output/paddle16-upgrade-20260930/REPORT.md)。1.6 已安装为独立候选，默认仍保留 v1；融合未进入生产。医疗 OTSL 格式已接入，字段映射与语义抽取仍待改进。实验全键 JSON 校验会因缺少选填键丢弃整条候选，后续生产方案应逐字段保留有效值、补缺选填键为 null，缺必填/错型/冲突分别送复核；不能在旧实验中偷偷改变计分口径。

[体检全目录测试](output/medical-corpus-20260930-v2/REPORT.md)已完成4份文件、66页/张、两版各82次实际推理。旧基准血常规参考结果v1为72/72、1.6为66/72；新版自动区域超时更少，其他表格文字层一致率更高，两类指标不能合并成完整报告准确率。已按完整方案实施[字段映射修复](output/field-mapping-replay-20260930-v1/REPORT.md)：原生表体恢复72/72、零额外项目；按用户精确标题提取6/6/2独立检查治疗清单，数量校验与化验异常分开；修复证书候选边界、日期角色和来源冲突。当前原生恢复使用真实表头与序号，不增加模型调用。长照片、个人基本信息及全量项目仍需补参考标注。

2026-10-08的[v1真实复测](output/current-pipeline-acceptance-20261008-v1/REPORT.md)确认映射修复进入真实发布链路，但不代表全报告OCR完成。该次Paddle加载/预热55.735秒计入单驻留任务预算；第7页大区域4096tokens截断84秒后重试超时，第6页旧热点4.016秒正常结束。该历史复测未改变180秒、tokens、路由、配置或缓存。

[有界体检优化](.agents/notes/implemented/bug-fix/2026-10-08-bounded-medical-recognition.md)现已实现并完成[v2实测](output/current-pipeline-acceptance-20261008-v2/summary.json)：启动156.000秒单列，三份PDF均在原180秒Task预算内结束；医疗66次实推理、97次缓存命中，8次time_limit及1次repetition_stop均由GLM原图备用EOS结束。三报告154区域没有pending/incomplete；这只证明处理链结束，未充分标注的全报告、个人基础信息和临床完整性仍未验收。225项后端CPU测试、24项前端测试及typecheck/build通过。四证书固定39present、4absent、6uncertain不变；37/39正确、4项应为空均正确，runtime_required_missing共4。当前Windows/CUDA结果不能证明Mac/16GB人资机适用。

每轮自己的tasks.csv、fields.csv、attempts.csv和summary.json保留原始匿名测量；派生图表数据与报告分开，不混用启动、加载、实推理、逻辑缓存和子集准确率。v1失败历史及旧离线基准均不覆盖。

[独立队列决策](.agents/notes/implemented/architecture/2026-10-08-independent-model-queues.md)及[临时前端决策](.agents/notes/archived/feature/2026-10-08-temporary-recognition-workbench.md)曾落地，临时前端现已移出；API和队列保留。新增Task/run所有权隔离、short stop fence migration0002与双文件进程，保留180秒识别/181秒监督窗口。实际GPU未故意注入取消/OOM，CPU真实轻量Job验证定向退出；未知退出不擅自恢复。Mac提案仍未实施。

用户授权的素材目录已[匿名盘点](output/material-inventory-20261008-v1/summary.json)：15份、当前支持9份、5份与本轮不同字节的候选；不把文件hash不同当成病例/模板不同。原件只读、路径映射加密，新增候选尚未GPU测试/人工标注，不能补入本轮准确率分母。学历材料与银行卡尚未扩大准入。

本轮入口：[v2报告](output/current-pipeline-acceptance-20261008-v2/REPORT.md)、[绘图数据](output/current-pipeline-acceptance-20261008-v2/chart_data.csv)、[v1/v2对照](output/current-pipeline-acceptance-20261008-v2/comparison.csv)。对照说明变化条件，不将双驻留、软停止和缓存的组合效果归因为单一优化。

第二阶段验收必须使用本轮新目录留证据，并分别标记真实模型测试、真实 HTTP/浏览器测试、合成材料、模拟故障和静态检查；本文件不预填结果。

1. 真实上传及结果：至少覆盖可靠文字 PDF、扫描/混合 PDF、图片，保存路由、页面数、区域数、尝试和限制；可靠文字证据不产生多余 OCR。
2. 字段与医疗项目：按标签和结果列核对，箭头、小数、单位、参考区间及跨页归属不能用全文字符串命中代替；缺项仍留在同一参考分母。
3. 持久化及版本：上传失败不暴露半写任务；取消与完成竞争、旧 run 写回、重跑后旧结果失效、重启恢复及七天清理符合契约。
4. 安全诊断：401/403、服务断连、解析失败、超时能关联安全错误编号；包内不含 Key、原文、原始异常正文、材料路径或桌面截图。
5. 浏览器：operator 手工输入 Key，真实批次/任务/NEED_REVIEW 展示，取消等待、run/revision 刷新、离页停止轮询、断线退避；桌面和窄屏分别检查。
6. 回归：后端 CPU 测试、前端 tests/build、DDE verify；通过这些检查不替代以上真实行为验收。

## 5. 后续未实现范围

| 后续阶段 | 范围与验收要求 |
|---|---|
| 字段归属与候选 | 保留可靠 PDF 文字/表格结构；语义抽取只在经过来源核对、校验与复核后采用。全字段/必填短模板实验不代表生产抽取已经完成 |
| 体检识别层次 | 个人基础信息、检查类别/表格标题、具体指标及原始异常标记分别核对；不同套餐的项目清单动态变化，未出现项目不自动视为漏项 |
| 体检异常分级与备注 | 后续参考 `F:\dingding\体检异常分级管理工具包（结合先行入职体检参考标准）.xlsx`，先核对与版本化规则再做分级/导出备注；当前未读取或应用该表，不让模型自行制定入职判断规则 |
| 复核与业务输出 | 人工编辑字段/项目、接受允许确认的问题、revision 冲突、预览坐标、高亮、reveal 审计和版本绑定导出；不能把原始 OCR 当审核结果 |
| 更多材料类型 | 身份证、银行卡、户口本、营业执照、学信报告等逐类实现并验证；银行卡须先完成安全码入库前处理能力 |
| 完整覆盖与布局 | 真实文档覆盖判定、可靠表格行列归属、方向/裁剪变换、PP 布局是否接入及其失败成本；不由人工补框冒充自动成功 |
| 部署可靠性 | 一致性备份、DPAPI 密钥迁移/恢复策略、迁移失败恢复、断电和原生解码挂起验证；不靠删库升级 |
| 目标机器 | 在真实 HR 电脑验证内存/GPU能力、正常/异常退出、超时及恢复，记录硬件与测量条件，不推断 16 GB 或 CPU-only 可用 |

不提前建设通用插件平台、分布式队列或内网服务。微调、第三个通用大模型、Redis/Celery 与安装包不在本阶段范围；不为业务服务改装已验证的模型依赖。
