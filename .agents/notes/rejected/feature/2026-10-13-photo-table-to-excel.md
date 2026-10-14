# Agent Note: Withdraw the uncommitted photo-table implementation

Status: rejected — User requested a rollback and a new plan before reimplementation
Scope: backend/ocr_app, frontend/src, tests, frontend/tests, openapi.yaml, SPEC.md, FRONTEND_FIELDS.md, RUNTIME.md
Last-verified: 2026-10-13

## Problem

上一轮把照片表格接入目录、OCR流程、编辑和Excel导出，并将所有导出字体改为21/12号。用户要求全部撤回、重新设计。该轮没有Git提交；回退目标为此前最新提交 `c4da709d599dd7361194d2c407b890ba55f199ff`（1.22.3），不是它的父提交。

## Proposal

被撤回的方案使用OpenCV候选框、Paddle结构识别和GLM备用，保留原始矩阵与人工矩阵；一张照片一个标题命名的XLSX，多张ZIP。其优点是复用了现有模型、版本校验和加密存储，较少引入依赖。

它完成过703项后端、158项前端测试及构建，但未执行四张样本的真实模型识别。这些是撤回版本的历史验证，不能作为新方案的验收。CPU网格预检第四张估计8列，而原件10列；第三张表框下方的手写补录也需要明确处理。仅功能测试和几何预检不足以支撑照片转表格的完成判断。

用户请求执行后，32个已跟踪文件恢复到基线，5个新增文件撤出活动源码；撤回内容、二进制diff及13个旧前端产物备份在 `output/rollback-table-20261013-182731/`，逐文件哈希核验完成。前端按基线独立重建，13个实际HTTP静态文件与重建文件一致，健康检查正常，未重启后端或修改业务数据库、原件和模型。

新版提案见[重新设计](../../implemented/feature/2026-10-13-photo-table-to-excel-replan.md)。本记录保留撤回理由，不声称任一表格功能当前已部署。

## Alternatives considered

- 继续修补现有代码能保留投入、快速推进，但用户明确选择回退重做；先恢复可核验基线再提交新的方案。
- 回到 `HEAD~1` 操作简短，但会额外撤掉已经提交的1.22.3安全修复，不符合撤回“刚刚改动”的范围；恢复当前HEAD并移走本轮新增文件。
- 直接清理工作区最省步骤，但不便找回旧思路和测量；先完整备份并核验，再定向恢复，不使用全目录强制清理。

## Consequences

现行产品仍以1.22.3为准，新的表格功能和21/12号字体需要按新提案重新实施。上一轮原始样本、测量和撤回快照保留；原件及既有业务数据不因代码回退而改变。
