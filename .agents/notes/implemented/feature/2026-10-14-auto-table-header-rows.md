# Agent Note: Populate table header drafts only from supported boundaries

Status: implemented
Scope: backend/ocr_app/table_recognition.py, backend/ocr_app/photo_table_pipeline.py, frontend/src/table-review.ts, frontend/src/components/TableReview.vue, tests/test_photo_table_recognition.py, tests/test_photo_table_workflow.py, frontend/tests/table-review.test.ts, openapi.yaml, SPEC.md, FRONTEND_FIELDS.md, frontend/public/help/index.html
Last-verified: 2026-10-14

## Problem

表格目前只有连续全 th 行能提供多行表头建议；其余输出固定建议1行，前端还需手动采用。用户已批准自动判断并填写行数，保留人工修改、不确定时手选、已保存设置优先。

## Decision

后续[免首次保存导出](../../implemented/simplification/2026-10-14-table-export-without-confirmation.md)让完整且有依据的建议直接参与导出，替代本篇“必须核对保存”的交互门禁；推断、保留原始值和人工优先约束继续有效。

复用已有结构输出，后处理不新增模型调用。显式表头标签优先；没有标签时结合顶部合并层级与后续连续数据的类型变化推断边界。没有边界证据的纯文本表、标题整行混入、合并跨边界和不完整结构保持未知。无表头仅对有连续1/2/3序号、多列明确为数据且各行包含文字的结构建议0；数字年份行和纯数字矩阵不能单凭数字认作无表头。

结果增加可选 header_suggestion_source（model_tags / structure / data_rows / null），header_suggestion 允许0或null；不伪造概率。初始 header_rows 保持null，首次打开编辑草稿时仅采用带已知来源的新建议，保存仍通过既有版本化审核。旧结果缺少来源不自动采用旧的固定1；已保存草稿包括0、null优先，不自动覆盖。界面提示判断依据、高亮选定行，保留手工调整。

## Decision audit

- [照片表格整体设计](../../implemented/feature/2026-10-13-photo-table-to-excel-replan.md)部分重叠：本篇替代其表头需手动采用的交互，保留原件、保存、导出与字体约束，两篇互链。
- [被撤回的表格实现](../../rejected/feature/2026-10-13-photo-table-to-excel.md)是上一轮撤回原因，保留，不重新启用。
- 主题检索未发现其他自动表头决定；医疗表格的固定项目映射与本次动态照片矩阵无关。

## Alternatives considered

- 继续固定建议1行并手动确认：交互明确、实现最少；却让常见表格反复操作且无法区分未知与有依据的单行表头。
- 仅靠显式th标记：语义清楚、误判较少；Paddle OTSL输出不含这些标记，无法覆盖当前样本，增加保守的结构判断。
- 追加大模型语义调用：对全为文字的复杂表头可能更有帮助；增加耗时与推理边界，本轮用已有输出，歧义交给人工。

## Verification

覆盖单行、两行和三行合并表头、明确无表头、全为文字的歧义、数字列名、标题混入、跨界合并、残缺结构；前端覆盖首次自动填写、人工修改及保存0/null/不同值、旧结果兼容。矩阵值与合并不变，保存后的导出颜色与行数一致，标题21号、表头/数据12号。

23项表格后端、18项文档契约、21项字段目录测试及161项前端测试通过，Vue类型检查和Vite构建通过。隔离8767合成材料的浏览器验证首次自动填写1、手动改0并保存、关闭重开仍为0；上传入口与批次类型显示“表格”。截图与测试数据仅在output/header-autofill-browser-20261014/。

四份历史真实OCR输出回放均建议1行、矩阵不变；不是重新推理或独立准确率测量，真实多行表头仍缺少样本。本轮发现当前四份源文件的哈希与原试验manifest不一致，仅使用原加密OCR记录，不改源文件，不沿用“当前源文件未变”的结论；记录于output/header-autofill-20261014/replay.json。

用户本轮同时要求入口名改为“表格”，前后端材料标签、上传提示及说明书同步；内部类型仍是TABLE，不迁移历史记录。

本机空闲备份后按原dual_resident方式重启，GLM/Paddle均加载预热成功、health为ok。11张业务表、266任务、2账号、2770份材料/密钥文件与备份一致；13个新构建静态文件与HTTP一致。首次55秒核验等待尚不足两个模型依次加载，随后重新核验成功，保留实际启动耗时；不记为任务OCR失败。记录在output/header-autofill-activation-20261014/verified.json，Mac未部署。

## Consequences

类型变化和合并关系只能形成保守建议，无法保证任意业务表格语义正确。选择少自动填而不是猜错，工作人员仍需核对保存。无数据库迁移，旧结果和人工记录不改写。
