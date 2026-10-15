// Guide anchors are scoped to one page/batch. Never use business actions to reveal a target.
export type GuideContext = 'upload' | 'batches' | 'batch' | 'package' | 'review' | 'medical' | 'table' | 'generic' | 'engine' | 'accounts' | 'required' | 'retention'
export interface GuideStep { anchor: string; title: string; text: string; write?: boolean; optional?: boolean }
const step = (anchor: string, title: string, text: string, extra: Partial<GuideStep> = {}): GuideStep => ({ anchor, title, text, ...extra })
const source = step('source-tools', '对照原件，必要时再识别一小块', '这里可以跳到指定页、查看大图，或点“框选识别文字”裁出局部。识别后可复制原文或日期建议，再粘贴到修正框；不会自动覆盖已有字段。')
const fields = step('result-fields', '先核对已识别字段', '对照原件看姓名、号码和日期。红色缺失项要补齐；位数不符、校验失败或候选冲突需要人工核对。置信度提示不等于识别正确。')
const save = step('review-save', '修正后保存', '在“人工核对与修正”填写或修改，再点击“保存修正并重新校验”。保存会提交当前修正及核对结果；请先核对原件。只打开或关闭指引不会保存。', { write: true })
const exportDetail = step('detail-export', '最后导出 Excel', '必填字段齐全、明确异议已处理，且没有未保存的修正时可以导出。按钮不可用时悬停可查看原因；“待核对”状态本身不一定阻止导出。', { write: true })
const filter = step('batch-filter', '先找需要处理的文件', '用“只看必填未填”和“只看有异议”快速找出问题任务。表格显示“导出待处理”。筛选仅影响列表，不改变“本批次全部”的导出范围。')
const tasks = step('batch-tasks', '打开结果核对', '点击文件行或“查看／补填／核对”进入详情。识别进度反映实际处理阶段；失败时保留错误编号，交给维护人员。重跑前请阅读覆盖提示，先保留人工修正。')
const exportBatch = step('batch-export', '选定范围再导出', '可选“本批次全部”或勾选文件导出。所选范围中有一份不满足导出条件，就整次停止。人员材料包第一张总表汇集所选材料的全部字段，同类多份分别保留。', { write: true })
const guides: Record<GuideContext, GuideStep[]> = {
  upload: [
    step('upload-mode', '先选择整理方式', '同一种材料集中处理，选“按类型批量”；同一个人的多种材料，选“按人员整理”。人员包不必先填姓名，识别后再核对建议；不要把不同人的材料混在一个包里。'),
    step('upload-types', '选择合适的入口', '已有证件用对应入口。拍照的行列表格要还原成 Excel，用“表格”；申请单、登记资料要提取正文和键值，用“通用识别”。', { optional: true }),
    step('upload-layout', '把常用入口放在前面', '“自定义入口”可调整位置和收纳；工作台最多 12 张卡片，其余在“更多类型／收纳箱”。个人布局独立保存，管理员还可设置默认布局。', { optional: true }),
    step('upload-files', '选取原始文件', '支持 JPG、PNG、HEIC、PDF；单个不超过 50 MB，一批最多 100 个、总计不超过 500 MB。银行卡和表格入口使用图片。先检查清晰度与材料是否完整。'),
    step('upload-classification', '核对自动分类', '人员材料包里的分类只是建议。检查每个文件的材料类型，无法确定的请手动选择；混有多种证件的 PDF 请先拆开。', { optional: true }),
    step('upload-submit', '核对后开始识别', '确认数量和材料类型后再提交。自动转正会辅助处理歪斜图片；上传后到“任务批次”查看进度。指引不会替你上传。', { write: true }),
  ],
  batches: [
    step('batch-calendar', '按时间查找', '按日、周或月分组，再选择日期；时间均为北京时间。点“全部日期”清除筛选。每个批次标注上传账号，管理员能看到全部，普通账号只能看到自己的。'),
    step('batch-refresh', '需要时读取最新结果', '进行中的任务自动刷新；空闲时可点击“刷新”，较早记录用“加载更早的批次”。刷新页面不会替你重跑识别。'),
    step('batch-list', '展开要处理的批次', '批次标题提示缺必填或有异议的任务数。展开一个批次后，点“本批次指引”查看筛选、补充上传和导出说明。没有记录时先上传或调整日期。'),
  ],
  batch: [filter, tasks, exportBatch],
  package: [
    step('package-name', '识别后再确认姓名', '姓名是识别结果给出的建议。核对包内材料是否属于同一人，再保存人员姓名；姓名一致也不能证明所有材料归属正确。'),
    step('package-pairing', '检查身份证配套', '配套提示只表示人像面和国徽面材料是否存在。仅有人像面也可使用；国徽面不强制要求，仍需按当前必填配置核对。'),
    step('package-append', '后续材料追加到原包', '点“补充上传”，选齐此人的新增材料，核对分类后统一提交。不要重复建立人员包。追加不会延长原有文件的保留期限。', { write: true }),
    filter, tasks, exportBatch,
  ],
  review: [source, fields, step('review-fields', '补填和修正', '这里填写未识别的必填字段，或修正识别值。号码保留原始识别结果，系统不会自动增删数字；有多个候选时请对照原件决定。', { write: true }), save, exportDetail],
  medical: [source,
    step('result-fields', '检查台账基本信息与大项目', '先核对个人信息、六类检查结果和体检大项目。“已识别明细未见异常”仅指已识别的明细，不能证明整组已完整识别；缺少来源不能当作正常。'),
    step('medical-items', '异常明细与大项目是两种数量', '“本次体检项目意义”中的大项目数用于台账；检测明细异常数另行统计，排除身高、体重及小结，保留 BMI。筛选只改变展示，不改变复核分母。'),
    step('medical-summary', '报告声明清单单独复核', '“您共有 x 项异常需进一步检查并治疗”等清单按标题查找，不固定第六页。声明数量与已识别清单比较；数量相等也不代表全报告无遗漏。分级、录取决定由人工判断。'), save, exportDetail],
  table: [source,
    step('table-title', '标题可修改，也可留空', '优先采用最匹配的标题候选。没有标题也能导出：文件名依次使用标题、原图片名、表格加北京时间；空标题不会生成空白标题行。'),
    step('table-headers', '确认表头占几行', '系统会尝试识别多行表头；不可靠时请手动设置，没有表头填 0。导出的标题为微软雅黑 21 号，表头和数据均为 12 号，表头橙色、数据白色。'),
    step('table-grid', '对照原图检查单元格', '检查错字、行列和合并关系，必要时增删行列。表外文字也需检查是否属于表格；不完整的结果须核对并明确确认后再导出。'),
    step('table-save', '有修改才需要保存', '完整且没有修改的表格可直接导出，无需先点保存。改过标题、表头或单元格后，请保存修正；保存失败时保留草稿，先处理错误。', { write: true }), exportDetail],
  generic: [source,
    step('generic-result', '先看正文与键值', '通用识别适合表单、申请单、登记资料。系统提取主体正文和自适应键值；空白栏可以保留为空，不能凭空补出答案。'),
    step('generic-edit', '按原件调整键和值', '可补全文字，修改、增加或删除键值。要保留行列表格结构，请使用“表格”入口。局部模糊时可先在左侧框选识别，再复制到这里。', { write: true }), save, exportDetail],
  engine: [
    step('engine-status', '先看服务状态', '刚启动时模型需要加载和预热。等待就绪后再提交；“能力受限”与“不可用”需要查看下方原因。'),
    step('engine-components', '区分服务与模型问题', '这里分别显示数据库、处理进程、存储和排队情况。网络断开时先确认服务连接，不要反复重跑同一份材料。'),
    step('engine-models', '向维护人员提供状态', '记录模型状态和报错。右上角“诊断”可提供错误信息，帮助维护人员定位；指引不会重启模型。'),
  ],
  accounts: [
    step('account-create', '为每个人创建独立账号', '填写账号、姓名和密码，选择操作员、只读或管理员。不同操作员的任务和个人布局独立；管理员可以查看全部任务。'),
    step('account-list', '管理已有账号', '可编辑姓名、启用／禁用、删除账号或重置密码。姓名修改不改变登录账号或任务归属，删除账号仍保留历史识别记录。'),
    step('account-protection', '留意账号保护规则', '当前登录账号和最后一个启用的管理员不能禁用或删除。自己的密码从右上角账号菜单修改；同账号新登录会使旧登录失效。'),
  ],
  required: [
    step('required-type', '先选材料类型', '必填字段按材料类型统一配置，所有账号共享。不同材料分别设置。'),
    step('required-fields', '只勾选业务确实需要的字段', '已选字段缺失会阻止导出；未勾选字段仍会识别和导出。不要为了绕过识别问题随意取消必要字段。'),
    step('required-save', '保存后新旧任务都生效', '修改后当前和历史任务的缺失提示、导出校验同步更新，不必重新识别。保存前确认对已有工作是否有影响。'),
  ],
  retention: [
    step('retention-current', '先看当前保留期限', '文件从原上传时间计算期限；追加上传、重跑、保存修正都不会延长原件期限。'),
    step('retention-options', '选择平台统一期限', '可选 7 天、15 天、30 天或永不清除，同时影响新旧文件。到期清理包含原件、识别结果和修改历史。'),
    step('retention-save', '阅读影响提醒再确认', '保存时会提示影响范围，缩短期限可能让旧文件立即到期。已经清理的数据不能恢复；永不清除仍允许人工删除。'),
  ],
}
export function guideSteps(context: GuideContext, canWrite: boolean, isAdmin: boolean): GuideStep[] {
  if (['accounts', 'required', 'retention'].includes(context) && !isAdmin) return []
  const result = guides[context].filter(item => !item.write || canWrite)
  if (!canWrite) {
    if (context === 'review') result.push(step('review-fields', '当前为只读查看', '可对照原件查看字段和核对提示。需要补填、保存或导出时，请联系有操作权限的账号处理。'))
    if (context === 'generic') result.push(step('generic-edit', '查看正文与键值内容', '当前账号只能查看；需要修改正文、键值或导出时，请联系有操作权限的账号处理。'))
    if (context === 'batch') result.push(step('batch-export', '当前账号不能导出', '可以查阅本人的识别结果；下载 Excel 需要操作员或管理员处理。'))
    return result.map(item => item.anchor === 'source-tools'
      ? step('source-tools', '对照原件查看', '这里可以浏览原件、跳到指定页或查看大图。“框选识别文字”需要操作权限，只读账号不能提交二次识别。') : item)
  }
  return result
}
export function detailGuideContext(docType?: string): GuideContext {
  if (docType === 'MEDICAL_REPORT') return 'medical'
  if (docType === 'TABLE') return 'table'
  if (docType === 'GENERIC') return 'generic'
  return 'review'
}
export function findGuideTarget(root: ParentNode, scope: string, anchor: string): HTMLElement | undefined {
  // Identifiers are app-owned, not file names, recognised text or selector expressions.
  if (![scope, anchor].every(value => /^[a-zA-Z0-9_-]+$/.test(value))) return
  const visible = (el: HTMLElement) => el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden'
  const scopes = Array.from(root.querySelectorAll<HTMLElement>(`[data-guide-scope="${scope}"]`)).filter(visible)
  if (scopes.length !== 1) return
  const targets = Array.from(scopes[0]!.querySelectorAll<HTMLElement>(`[data-guide="${anchor}"]`)).filter(visible)
  return targets.length === 1 ? targets[0] : undefined
}
