# 前端字段与当前 API 说明

## 识别任务公平排队

Task新增`queued_at:string|null`（本次入队ISO时间，迁移前旧任务为null）与`active_started_at:string|null`（本次领取开始时间，未领取为null）。前端兼容旧响应省略字段；只显示服务端已记录时间，不从创建时间猜测重跑入队时间。列表存在QUEUED任务时说明同通道按账号轮流、每次一份，当前材料完成后继续调度；进度悬浮展示入队/实际开始时间（UTC+8）。不同账号之间不承诺上传先后顺序或固定排队名次，同账号跨批次按本次入队顺序处理；不提供未经实测的ETA、不显示其他账号任务资料。拆分批次不能增加轮次，重跑进入本人队尾，账号轮转不增加模型并发。

## 服务器繁忙与排队

上传/分类/追加及Excel导出可能短暂等待服务端名额，当前排队上限15秒。503 SERVICE_BUSY表示队列或数据库繁忙，429 OPERATION_THROTTLED表示该账号已有过多同类操作，Retry-After给出建议重试秒数（当前2秒）。ApiFailure.retryAfterSeconds保留可信的整数秒；这不触发写请求自动重试。上传失败保留所选文件，保存失败保留当前草稿，导出失败保留模式与勾选。断网/HTTP超时仍可能已经提交，不得提示为“确定未提交”。导出返回409 RESULT_VERSION_CONFLICT或SETTINGS_VERSION_CONFLICT时，应刷新并核对当前版本/必填要求。

对应 SPEC v1.33、OpenAPI / 应用源码 1.26.0。本文描述代码接口，完整 schema 见 [openapi.yaml](openapi.yaml)，业务规则见 [SPEC.md](SPEC.md)。Element Plus 前端已接入；账号批次隔离、上传人署名和管理员姓名编辑已实现，各版本验收及实际服务切换见运行记录。

批次按上传账号的不可变ID隔离：管理员看全部，操作员/只读仅看自己的。列表先限制归属再计算total和分页，日期筛选不改变隔离；全部Task结果/原图/复核/取消/重跑/完整字段/导出接口独立校验，越权与不存在ID统一404，混合账号导出整次拒绝。批次删除仍仅管理员；材料目录及必填设置仍共享。账号切换清空任务、结果及预览，旧会话的迟到读取和写响应不得回填新会话。

Batch新增owner={user_id:string|null,username:string|null,display_name:string|null,account_exists:boolean}，列表与详情同源。account_exists=true时三个身份字段均非空；显示“上传人：姓名（账号）”。删除账号后保留原ID及删除前加密署名，显示“姓名（账号，已删除）”；无法恢复姓名的历史ID显示“历史账号（未关联）”，归属不明显示“未知上传人”，两者仅管理员可见。旧服务缺owner时前端兼容显示未知，不推测归属。修改姓名按下一次读取更新批次，管理员修改自己时即时更新顶部姓名。

管理员在展开的批次中可“删除批次”，需二次确认，待人工核对也可删除；未加载完整任务或包含排队/运行任务时禁用。DELETE /batches/{batch_id}提交{versions:[{task_id,run_id,expected_revision}]}，使用确认框打开时冻结的完整快照。成功200返回{batch_id,task_ids,cleanup_pending}，移除列表、选择和原图缓存，关闭对应详情，作废迟到读取并保留日期范围；409刷新核对后重新确认，不盲重试。cleanup_pending=true须明确提示记录已删除但文件待维护清理。操作员/只读不显示删除入口，后端仍独立校验管理员权限。

管理员登录后显示“账号管理”，调用`GET /api/v1/admin/users`查询账号公共信息，`POST /api/v1/admin/users`提交username/password/display_name及可选role（默认operator，可选viewer/admin），Cookie写请求沿用同源Origin及X-CSRF-Token。密码8至128字符且不能全空白，账号名大小写等价；201返回新账号公共信息，409 USERNAME_EXISTS表示重复且没有修改原账号。只有admin可使用，operator/viewer返回403；请求体最多8192字节。公共账号信息为user_id、username、display_name、role、enabled，不含密码摘要。

已有账号行提供“编辑姓名”“禁用／启用”“重置密码”“删除”；禁用/删除先确认，取消不请求后端。`PATCH /api/v1/admin/users/{user_id}`每次接受`{display_name:string}`或`{enabled:boolean}`其中一种，不能混传。姓名去首尾空白，需1至80个可打印字符；可改自己姓名，不改登录账号、角色、密码、启用状态、会话或归属。200返回公共账号；`DELETE`同一路径无请求体，成功204；`POST /api/v1/admin/users/{user_id}/password`只接受`{new_password:string}`，成功204。删除保留历史任务、结果与审计UUID，同名重建使用新UUID且不能继承历史批次；禁用、删除和重置均撤销目标全部登录，重置不会启用禁用账号，启用不会恢复旧登录。当前账号及最后一个启用的管理员不能禁用/删除；自己的密码按钮打开自助入口，管理员重置自己返回409 ACCOUNT_PROTECTED。目标不存在404，权限变化或会话撤销按401/403处理，操作成功刷新列表，不自动重放写请求。

所有角色从右上角姓名菜单“修改密码”进入；`POST /api/v1/auth/password`只接受`{current_password:string,new_password:string}`。原密码1至128字符，新密码与创建相同；前端还要求确认新密码一致。原密码不正确为422 CURRENT_PASSWORD_INCORRECT，保留登录并允许重输；成功204清除Cookie并撤销全部会话，前端回登录页。密码输入在提交结束、关闭和卸载时清空，不进入诊断。请求未结束时不允许关闭密码弹窗；CLI仅作为本地恢复工具。

体检按业务台账18列导出，不追加临时“人工录取意见”或分级列。应用不自动分级或决定录取；Word仅参考，具体遵循用户已确认的模板和规则。

## 当前可用入口

使用账号密码与同源Cookie会话。POST auth/login发送username/password，成功返回身份、权限和csrf_token并设置HttpOnly Cookie；GET auth/me刷新恢复身份；POST auth/logout撤销服务端会话。非GET/HEAD/OPTIONS请求附X-CSRF-Token，浏览器自动附同源Origin。csrf_token只留在内存，密码和Cookie不写URL、localStorage、sessionStorage或诊断。30天绝对过期后401返回登录，任务继续。无默认账号，需管理员本地配置；未配置返回AUTH_NOT_CONFIGURED，五分钟五次尝试后LOGIN_THROTTLED。当前服务仍只绑定loopback，创建任何账号后旧Key认证永久关闭。

| 请求 | 用途 |
|---|---|
| `GET /health` | 公开存活检查，仅返回 `{status:"ok"\|"degraded"}` |
| `GET /api/v1/health` | 登录后读取组件、模型状态与队列；无有效登录返回401 |
| `POST /api/v1/auth/login`、`POST /api/v1/auth/logout` | 账号密码登录／撤销会话 |
| `GET /api/v1/auth/me` | 当前身份、权限、Cookie会话csrf_token；刷新恢复 |
| `POST /api/v1/auth/password` | 所有角色凭原密码修改自己密码，成功后重新登录 |
| `GET/POST /api/v1/admin/users` | 管理员查询／创建账号 |
| `PATCH/DELETE /api/v1/admin/users/{user_id}` | 管理员编辑姓名／启用／禁用／删除账号，禁用/删除仍保护当前账号和最后管理员 |
| `POST /api/v1/admin/users/{user_id}/password` | 管理员重置其他账号密码 |
| `GET /api/v1/doc-types` | 13种材料目录（12种业务类型及TABLE）；返回数组，每项doc_type/label/fields |
| `POST /api/v1/batches` | multipart 上传，返回202及显式 task_ids；必须指定 doc_type_hint |
| `GET /api/v1/batches`、`GET /api/v1/batches/{id}` | 批次列表/详情 |
| `GET /api/v1/batches/{id}/tasks`、`GET /api/v1/tasks` | 批次任务/分页任务列表 |
| `GET /api/v1/tasks/{id}` | 任务状态、run_id、result_revision、进度/错误 |
| `GET /api/v1/tasks/{id}/result` | 当前已发布结果；无结果时409 INVALID_STATE |
| `POST /api/v1/tasks/{id}/cancel`、`POST /api/v1/tasks/{id}/rerun` | 提交当前 run_id 与 expected_revision，返回202；409冲突后重新查询，不能自动重试写操作 |

支持 `INTERVIEW_FORM / ID_CARD_FRONT / ID_CARD_BACK / DIPLOMA / DEGREE_CERT / MEDICAL_REPORT / BANK_CARD / BUSINESS_LICENSE / XUEXIN_DIPLOMA_TABLE / PASSPORT / HOUSEHOLD_REGISTER / GENERIC`，另有独立TABLE入口。支持JPG/JPEG、PNG、HEIC、未加密PDF（银行卡和TABLE只接收单张照片）；每批1–100文件，单文件50MB、总计500MB（MB=1024×1024字节），达到上限可上传。选择器、计数、超限提示与提交前校验共用 `uploadLimits`，后端仍独立校验；一文件一Task，同批重复内容沿用任务复用规则。

新增已实现入口如下；人员包追加已开放（见1.22.0节），拒绝/恢复/替换文件仍未开放。OpenAPI标记x-implemented:false的目标路径不能调用。

| 请求 | 用途 |
|---|---|
| `POST /api/v1/tasks/{id}/review` | operator补录/确认，携带run_id/expected_revision |
| `GET /api/v1/tasks/{id}/preview` | 鉴权同版本corrected完整PNG；无需理由 |
| `POST /api/v1/tasks/{id}/preview` | 旧调用兼容，同版本corrected PNG，body含page |
| `POST /api/v1/tasks/{id}/reveal` | 旧调用兼容；字段已完整返回，UI无需再揭示 |
| `POST /api/v1/export` | 批次全部或明确task_ids，整选门禁XLSX |
| `GET /api/v1/admin/required-fields` | admin读取各类型必填字段、uses_defaults及全局revision |
| `PUT /api/v1/admin/required-fields` | admin保存一种类型的required_fields与expected_revision；null恢复默认 |

## 共享必填字段设置

管理员进入“必填字段设置”，选择材料类型并勾选必填项，保存后对所有账号、当前和历史批次生效，服务重启后保留。下文各类型表格中的必填列描述默认规则；实际界面和导出使用服务端返回的当前设置。未自定义的类型保留原有条件必填；自定义集合完全替代该类型默认必填，恢复默认同时恢复条件规则。户口成员使用`members.key`，通用正文为`generic.full_text`，自动计算的只读字段不可设为必填。清空保存后空白业务字段不阻止导出，仍须有已保存的支持类型结果。

GET返回`{revision,items:[{doc_type,label,uses_defaults,fields}]}`，PUT发送`{doc_type,required_fields:string[]|null,expected_revision}`，响应为全部新设置。空数组与null含义不同；其他类型不受本次保存影响。相同设置保存不递增版本。写请求沿用管理员、同源Origin和CSRF校验，409 `SETTINGS_VERSION_CONFLICT`保留当前选择，重新读取并核对后再保存，不自动覆盖其他管理员的变更。

Batch、Task及TaskResult可选携带`required_fields_revision`，独立于`result_revision`；结果缓存身份包含该版本。TaskResult还返回当前值条件下的`required_field_keys`。保存设置会刷新当前页面目录与已加载的终态任务；其他会话在下一次读取、聚焦或刷新时取得设置，服务端每次补正及导出始终使用最新版本。打开中的表单遇到设置变化会保留草稿并提示重新读取。设置只投影必填元数据和缺失问题，不改写历史密文、人工值、OCR结果、审核状态或任务版本，不重新识别。

## 通用字段与任务状态

`TaskResult.fields` 是 Field 数组，按 `key` 查找，不依赖数组下标。医疗另有 `basic_info` 字典，键与个人/报告信息字段相同，值仍是 Field 对象，不是直接字符串。历史医疗响应可能缺新增可选键，缺键和 null 都应显示“未识别”。

| Field 属性 | 含义 / 显示规则 |
|---|---|
| key / label | 稳定英文键 / 中文名称 |
| value | 已整理值：string、number或null；返回完整值，直接显示返回值 |
| value_masked | 可选，兼容旧字段；当前不作为显示值，优先value |
| confidence / confidence_method | 当前null / unavailable；前端不再展示置信度，不能当0分，也不能自填固定分 |
| required / editable | 当前类型及材料条件的必填与可编辑标记，优先于静态表 |
| reviewed / value_origin / absence_reason | 人工确认、recognized/manual/derived、NOT_ON_DOCUMENT/NOT_APPLICABLE |
| derivation | 可选派生说明；银行卡offline_bin标明输入字段、匹配号段、库版本/日期/来源及哈希，不是OCR来源 |
| need_review | 后端是否要求核对；必填无标定值须确认，选填单纯缺置信度不阻塞 |
| review_issues | issue_id、code、message、can_accept；MISSING表示缺值，CONFLICT表示候选矛盾，CONFIDENCE_UNAVAILABLE表示未标定 |
| candidates | 可选候选，冲突字段value仍null；不自动选第一项 |
| source | 可选来源页、区域及框，见下文 |

“业务必填”不等于识别响应里 value 必须非null：缺失必填保留空值并给 MISSING，前端应突出显示。可选字段为空通常不形成必填缺失，但也不能编造值。任务、字段和医疗行的 review_issues 分层显示，不能只看任务级问题数组。

Task 状态为 `QUEUED / PREPROCESSING / OCR / EXTRACTING / VALIDATING / NEED_REVIEW / COMPLETED / FAILED / REJECTED / CANCELLED`。当前成功识别进入 NEED_REVIEW。运行中串行轮询，进入待核对或终态停止无必要轮询；过期请求不能覆盖新 run/revision。取消请求成功不代表运行任务已经停止，继续查询直到服务确认终态。失败/超时可能仍有已发布部分结果，显示限制和错误，不能当完整成功。

### 真实识别进度

`GET /api/v1/tasks/{task_id}`与`GET /api/v1/batches/{batch_id}/tasks`返回的Task新增可选`progress_detail`；沿用现有串行轮询，不新增接口或事件流。数据只属于返回的`task_id/run_id`，换run后清空旧计数；不要合并不同run的最大值。`result_revision`仍是结果/操作版本，进度更新不会递增它；轮询须接收同run同revision的新进度快照。旧服务没有此对象时只展示status，不用旧progress推算真实完成量。

```json
{"stage":"OCR","prepared_pages":8,"total_pages":8,"processed_regions":12,"recognized_regions":11,"incomplete_regions":1,"total_regions":30}
```

这是接口示例，不是实测结果；可显示“文字识别中 · 已处理12/30个区域，其中1个不完整”。字段含义：

| progress_detail字段 | 含义 |
|---|---|
| stage | 与Task.status相同，包含排队、运行、待核对和终态 |
| prepared_pages / total_pages | 已保存页面数／原文件总页数；total_pages为null表示历史原页数未知，不能拿当前前缀充当总页数 |
| processed_regions | recognized_regions + incomplete_regions；每个OCR区域最多计一次，重试和备用模型不增加分母；缓存复用也完成目标区域一次 |
| recognized_regions / incomplete_regions | 完成识别／结束处理但仍不完整；均不代表字段正确率或医疗覆盖已证实 |
| total_regions | 全部原页完成分区计划后才有值；null表示计划尚未完成或历史无证明，0表示已知不需要OCR；原生文字块不计入OCR区域 |

排队显示“排队等待”且无运行动画；准备阶段显示已准备页数；**只有OCR阶段且区域总数已知并大于0时**使用ElProgress显示区域完成比例并附实际数量。所有运行阶段均以Loading图标表示仍在工作；准备、字段整理、最终校验或未知分母不显示数字进度条，不按时间自行涨百分比。区域耗时不等，比例不能标为时间进度或预计剩余时长。`EXTRACTING`只在全部OCR区域处理后进入一次，`VALIDATING`在字段整理后进入；纯文字PDF跳过OCR并显示“无需图像识别”。已处理完所有OCR区域仍不代表整理/校验已结束。

前端允许旧服务不含progress_detail，但不会从旧progress猜计数。若对象存在，必须包含全部必需键，stage与Task.status一致，计数为非负整数、processed=recognized+incomplete且不超过已知total_regions，已准备页数不超过已知total_pages；畸形数据走现有INVALID_RESPONSE诊断，不夹到上限或默认填0。原文件页数未知的actual_source_page_count=null也能解析。

`NEED_REVIEW`表示机器处理结束、仍待人工核对；`FAILED/CANCELLED`保留最后持久化的处理量，不显示成功100%。不完整区域应保留提示。旧`progress`整数保留兼容并在OpenAPI标为deprecated：新运行准备阶段0、OCR取区域比例（最终发布前上限99）、正常机器发布100，失败/取消保留上次值；它不估算准备/生成/字段整理耗时，也不表示审核完成。历史密文和旧progress不重写，前端不要回退到其固定阶段百分比。

批次标题显示已加载任务中“X个任务缺必填”；任务表增加“必填信息”列，依据已保存的 `export_ready=false` 和 `export_blockers` 标红并列出字段名称，名称来自材料目录。户口成员显示序号与字段，通用正文显示“正文”。运行中的任务显示尚未检查，缺少结果或材料类型的任务显示暂无识别结果，未知历史标志不推断完整。每批可勾选“只看必填未填”，仅筛选任务表；完整批次和已勾选导出的范围不因此缩减，隐藏行的勾选按task_id保留。点击“补填”打开现有结果编辑器，补齐并保存后根据服务器新版本自动更新标记；未保存草稿不清除标记。

## 毕业证 DIPLOMA

输出11键，校长 principal、学习形式 study_mode 已从新结果及历史公开结果移除；不重写原始证据和加密历史。

| key | 名称 | 值类型 | 业务必填 |
|---|---|---|---|
| name | 姓名 | string/null | 是 |
| gender | 性别 | M、F或null | 否 |
| birth_date | 出生日期 | string/null | 否 |
| school_name | 学校名称 | string/null | 是 |
| major | 专业 | string/null | 是 |
| certificate_no | 证书编号 | string/null | 是 |
| education_level | 学历层次 | string/null | 是 |
| duration | 学制 | string/null | 否 |
| enroll_date | 入学日期 | string/null | 否 |
| graduate_date | 毕业日期 | string/null | 是 |
| issue_date | 发证日期 | string/null | 否 |

编号按完整字符串处理，保留前导零；历史掩码不能作为人工更正值提交。日期可能只有YYYY-MM，不能自动补1号。正文学习区间的前者是enroll_date、后者是graduate_date；落款只作为issue_date，不能填入毕业日期。旧证据里仍可能出现校长/学习形式文本，不应重新据此生成已移除的业务字段。

## 学位证 DEGREE_CERT

本轮保留学习形式，不随毕业证一起删除。

| key | 名称 | 值类型 | 业务必填 |
|---|---|---|---|
| name | 姓名 | string/null | 是 |
| gender | 性别 | M、F或null | 否 |
| birth_date | 出生日期 | string/null | 否 |
| school_name | 授予学校 | string/null | 是 |
| major | 专业 | string/null | 是 |
| study_mode | 学习形式 | string/null | 否 |
| certificate_no | 证书编号 | string/null | 是 |
| degree_category | 学位级别 | string/null | 是 |
| degree_name | 学位名称 | string/null | 否 |
| award_date | 学位授予日期 | string/null | 是 |

## 体检个人 / 报告信息 MEDICAL_REPORT

`fields[]` 与 `basic_info[key]` 提供同一组17个Field。姓名、性别、年龄、体检日期优先取自“一、个人信息”下可靠的标签/值表格。程序不固定页码；目录和跨章节表格不能作为答案。识别到该章节但缺可靠表格时留空待核对，不用其他页检查/采样日期猜补。

| key | 名称 | 值类型 | 业务必填 |
|---|---|---|---|
| name | 姓名 | string/null | 是 |
| gender | 性别 | M、F或null | 是 |
| age | 年龄 | integer/null | 否 |
| exam_date | 体检日期 | string/null | 是 |
| institution | 体检机构 | string/null | 否 |
| report_date | 报告日期 | string/null | 否 |
| height | 身高 | string/null，保留单位 | 否 |
| weight | 体重 | string/null，保留单位 | 否 |
| blood_pressure | 血压 | string/null，例如129/84 mmHg | 否 |
| blood_routine | 血常规 | string/null，报告结论或异常摘要 | 否 |
| urine_routine | 尿常规 | string/null，报告结论或异常摘要 | 否 |
| ecg | 心电图 | string/null，报告结论或异常摘要 | 否 |
| dr_imaging | DR影像 | string/null，报告结论或异常摘要 | 否 |
| abdominal_ultrasound | 腹部彩超 | string/null，报告结论或异常摘要 | 否 |
| liver_function | 肝功五项（生化检测） | string/null，异常指标及结果；所属明细有正常依据时为已识别明细未见异常，未知留空，人工优先 | 否 |
| exam_project_count | 体检项目数量 | integer/null，只读 | 否 |
| exam_projects | 体检项目 | string/null，以中文分号分隔的原名清单 | 否 |

按模板恢复机构/报告日期；婚姻、电话、工作单位退出主要字段，编号/套餐仍不提供。原文与历史密文保留，历史读取按17键投影，不批量写回；旧结果缺少新增值时可补录。仅name/gender/exam_date必填。身高/体重作为台账字段可修正，仍不计异常；血压来源矛盾不自动组合。六类摘要必须有临床标题/表格/明确原名证据，不把复查建议当已检；小结只作所属大项结论来源，不作独立检测项目。

六类均包含肝功，无需小结：所属有效明细全部有来源、有结果且按报告标记/本行参考范围正常，或UNKNOWN行有明确A级且无异常标记、无冲突时，derived汇总为“已识别明细未见异常”。A级不覆盖阳性或明确异常；sources指向参与明细，置信度null，检测行分类/统计/既有复核不变。异常优先列出具体指标、结果和诊断。缺明细、其他未知或冲突仍显示“未识别”。可靠闭合连续编号原生PDF项目表证明未列出且无实际检测证据时，value=null/absence_reason=NOT_ON_DOCUMENT，来源指向项目表，页面和医疗Excel显示“报告未载明”；未闭合、断页、OCR项目表或已列出但漏提取的检查不能推断缺省。HCG尿检不等于尿常规。人工值/缺省理由优先，历史读取和Excel使用同一投影，原保存密文不变。

institution无明确标签来源时，使用已观察报告第1页照片右侧个人信息末行的完整品牌/分店名；仅覆盖普潓/普惠年华已观察版式。保留原文字符和括号内分店，去掉随后独立数字代码，source仍含完整原文和坐标。无可靠位置、分店不完整、相互冲突或其他医院无标签时留空/待核对，由用户补录；字段仍选填，不改变导出门禁。不会重写历史人工值。

体检项目取正文“本次体检项目意义”表格的项目列，例如内科检查、眼科常规、心电图，章节编号/页码不固定；目录不算正文。保留名称、顺序，重印同名只展示一次，不归并到items或异常计数。source指向整表，sources可选数组保留每行项目单元格的原文/页码/bbox，可逐项定位；无法可靠解析则留空补录，置信度null。人工可更正文本清单，必填导出规则不增加新门槛。

exam_project_count恰是该清单的count；清单缺失为null，身高体重血压是一项，顿号不拆分项目名。人工以中文/英文分号或换行分项，去重计数；编辑器即时预览，保存后由服务器更新，直接修改数量或其缺省理由返回422。它与检测指标数、异常数量、清单声明数独立。派生Field可含value_origin=derived和derivation.method=medical_ledger/input_field；分组派生中conclusions保留原文及来源，人工填写/缺省理由优先。

当前已按用户确认取消内部业务号码/电话脱敏。fields、候选、source原文、generic及Excel完整显示；value_masked不使用。鉴权、加密历史和安全诊断仍保留。

## 体检检测项目 items

| 属性 | 含义 |
|---|---|
| item_id / name / alias / category | 行ID、项目名、缩写、类别；alias/category可能null |
| result_raw | 检测原文，必有字符串；空串表示该检测结果缺失并待核对，不等于正常 |
| risk_grade | 可选string/null，报告中的风险等级/等级原文 |
| diagnosis | 可选string/null，同一行或唯一对应清单中的异常诊断原文；不由模型另造医学结论 |
| diagnosis_sources | 可选来源数组，可能与检测结果在不同页；空值不能靠相似项目名补齐 |
| value_num / unit / reference_range / ref_low / ref_high | 数值及本行参考范围，不能解析时null；显示时保留result_raw |
| abnormal_flag / abnormal_basis | 后端异常判断及证据种类，见下表 |
| source | 检测行来源；不能拿诊断来源替代检测结果来源 |
| confidence / need_review / review_issues | 当前未标定、需核对；异常行诊断缺失也有独立MISSING |

非空等级不是 `A` 或 `/` 时增加异常依据 `report_grade`。`A`、`/` 不取消箭头、数值范围或明确异常诊断；无等级也不能推断正常。按后端结果显示，不在前端重算等级或异常。

| abnormal_flag | 处理 |
|---|---|
| HIGH / LOW / ABNORMAL | 已有报告异常依据，列入异常列表 |
| NORMAL | 当前行依据为正常，仍保留识别核对状态 |
| POSITIVE | 阳性；只有basis为report_marker/reference_comparison时列入确认异常，其他情况待核对 |
| UNKNOWN | 未判定，单列待核对，不能归正常 |

basis 为 `report_marker / report_grade / reference_comparison / unknown`。查询 `items_filter=all/abnormal/unknown` 只投影返回列表；上传的 abnormal_only=true 默认同时保留异常与未判定项。不能把筛选后的列表长度当整份报告总量。

## 报告检查治疗清单 report_summary

通过“您共有X项异常需进一步检查并治疗：”定位，不固定第6页；没有该标题时可给出无声明的总检结论。清单独立于检测表异常计数。

| 属性 | 含义 |
|---|---|
| scope | follow_up_required、overall_conclusion或unidentified |
| declared_count | 标题声明数，未确认null |
| findings | 已提取的报告清单条目 |
| count_check | match、mismatch或unverified；match只表示这张清单数对上，不证明全报告完整 |
| sources | 标题/边界及清单来源 |

finding 保留 `finding_id / reported_number / text / sources`；新增可选 `project_name / result_item_id / risk_grade / diagnosis / result_raw / result_sources / need_review / review_issues`。text是清单原文，sources是清单来源；result_sources独立指向唯一匹配的检测行。重复同名或分组项目无法唯一对应检测行时 result_raw=null，并给MISSING/CONFLICT，不让前端猜配。若检测行能唯一对应但诊断互相冲突，已对应的检测结果仍保留，诊断留空并保留冲突来源；结果对应与诊断一致性是两项检查。project_name来自明确清单项目列，result_item_id指向唯一对应检测行；人工修正/删除该检测行后同步结果及来源。历史finding可能只有原4项，须兼容。清单条目在表格逐行展示并附结果来源，未关联行标注“未关联检测结果”；清单条目数吻合不证明检测表提取完整。

医疗 `stats.total/normal/abnormal/unknown` 当前在全量覆盖未证明时为null；显示“未确认”。`abnormal_summary` 是已经确认异常的检测行，不等同于 report_summary.findings。limitations 应可见。

检测行可选nullable `abnormal_exclusion_reason`支持`HEIGHT_WEIGHT/SECTION_SUMMARY`。身高/体重原值、等级和来源保留，全部项目显示“不计异常”，异常/待判定筛选及完整检测统计排除它们。BMI照常判定，不补算缺值；客户端不能改派生原因。台账身高/体重列记录测量，但异常指标列排除这些测量行；原始行及独立报告声明/清单仍保留。

复核范围补充：排除原因还支持 `SECTION_SUMMARY`，用于历史结果的精确“小结”检测行。`HEIGHT_WEIGHT/SECTION_SUMMARY` 行均返回 `need_review=false`，原始 `review_issues` 保留作证据；前端问题清单、自动确认和检测项目编辑器必须跳过这些行，后端也不把它们作为复核阻断项。编辑器过滤后须按相同过滤顺序或 item_id 绑定原图来源，不能套用未过滤数组下标。BMI 等有效项目、报告结论和全页覆盖复核仍保留。排除规则与界面搜索无关；读取不自动改任务状态，保存后以服务器返回的新版本为准。

新识别排除独立栏目行“小结”（忽略空白和末尾冒号），不将其作为检测项目、异常项目或检测结果关联候选。原文和原图仍保留，名称中仅包含“小结”的其他项目不因此删除。独立总检清单及声明条数不受此过滤影响；历史已保存识别结果需要重新识别以应用新规则。

## 原图定位与人工操作

字段定位仅在体检报告开放，保留基础信息、检测行、诊断、总检清单及各项目来源。证件和户口本成员不显示字段定位/相关来源按钮，仍可连续浏览、放大整页原图并人工填写。体检选择同页不同字段或重复选择同一字段时，均重新滚动到当前来源框；等校正图片加载完成后才叠加坐标，来源不足则显示整页。此变更不增加位置检测模型或 API，不改识别字段、审核及导出规则。

source 可含 `page`（从1起）、`region_id`、`extraction_method=pdf_text/ocr`、`bbox=[x0,y0,x1,y1]`（0–1归一化）、`bbox_kind=region/block/row/cell`、`raw_text`。有值不保证有精确框；没有cell框时可退化为row/block。bbox对应后端处理页，未经对齐的用户原图不应直接叠框。

历史材料已有登录后校正页预览接口，优先用当前run/revision绑定的服务端原图。同批相同内容文件会被后端去重，上传[A,A,B]可能只返回两个task_id，不能按原始提交索引直接绑定本地后备原图。本地File字节SHA256与任务公开content_hash核对后，以task_id绑定Object URL；同哈希原件相同，不能按文件名猜配；退出和卸载释放URL，本地后备图刷新后可能丢失。点击缺失/待核对字段时展示可靠来源，来源不足则允许查看整页，不伪造定位。

复核与导出使用独立判定，置信度仍未标定。审核状态由后端重新校验决定，前端不能自改COMPLETED；导出只要求已保存结果必填有值。


## 新材料字段与规则

`GET /doc-types`返回FieldMeta数组（key/label/type/required/editable/required_when），界面据此建表单；结果Field.required给出当前条件。编号必须字符串，日期可能YYYY-MM，不补日期。界面不再提供缺省原因下拉，原件未载明的选填留空即可；接口仍接受明确的缺省枚举，必填不能标缺省。

| 类型 | 主要必填键 | 限制 |
|---|---|---|
| ID_CARD_FRONT | name/gender/ethnicity/birth_date/address/id_number | MOD11-2+日期/性别一致性，不证明真实性 |
| ID_CARD_BACK | issuing_authority/valid_to | valid_to可长期，valid_from选填 |
| BANK_CARD | card_number | 整图自动识别；失败单张旋转裁图重识别或补录；不收PDF；Luhn适用性未知不猜改号 |
| BUSINESS_LICENSE | unified_social_credit_code/company_name/company_type/legal_representative/registered_capital/established_date/business_scope/registered_address/registration_authority | 旧registration_no与个体/独资/合伙资本条件由结果元数据决定 |
| XUEXIN_DIPLOMA_TABLE | name/gender/birth_date/graduate_date/school_name/major/education_level/certificate_no/online_verification_code/report_language | 只备案表；OTHER_REPORT/UNKNOWN不允许审核放行；ASCII字母数字12/16验证码仅兼容检查，官方核验UNKNOWN |
| PASSPORT | passport_number/name/nationality/birth_date/expiry_date | TD3双行44字符MRZ检查；不猜两位年份世纪，冲突须更正 |
| HOUSEHOLD_REGISTER | household_type/householder/household_no/address | 集体户主可不必填；members逐成员fields和source_page，完整页核对 |
| GENERIC | 经核对的full_text | generic只显示原识别；reviewed_generic另存人工正文/KV |

字段完整清单以动态目录和OpenAPI为准。身份证/护照/户口本/营业执照当前缺实样，不能把规则单测当成识别精度。

## 人工补录与确认

“原件对照”工具栏提供摄像头“框选识别”，表单字段旁不放按钮。弹窗按当前task/run/result_revision读取corrected页，默认选择实际可见面积最大的页，多页可手动换页。框选多行文字，坐标按实际图片显示尺寸换算成0..1的xyxy。`POST /tasks/{task_id}/ocr-region`提交`{run_id,expected_revision,page,bbox}`，省略field_key；响应field_key为null，回显身份/选区及`text/confidence`。旧客户端传字段键时保留原字段校验及回显。CPU局部OCR只有一个在途请求，子进程预算10秒；429忙、504超时、422空文字、503不可用均保留草稿，由用户重新框选或手工填。

识别结果在同一弹窗的文本框中编辑，点“复制文字”后粘贴到需要的字段、医疗明细、成员或通用正文中。复制后保持查看窗口；浏览器不支持或拒绝复制时保留文字并选中，提示Ctrl+C/Mac ⌘C手工复制。此动作不自动填字段，也不改变现有草稿。切换账号、任务、版本、页码、失去权限或关闭弹窗时取消/忽略旧响应；迟到的复制结果不能关闭新弹窗。号码保留前导零，日期不补精度，数值须有效。局部OCR参考分数不覆盖业务字段置信度，不确认问题、不保存结果；粘贴后仍需“保存修正并重新校验”。保存后才参与导出。服务端返回前重新校验会话、权限、归属与版本。

结果卡片保留原始可编辑文字及其复制按钮，并按当前文字实时生成日期建议（前端临时状态，不改API响应）。例如2024年6月→2024-06，二〇二四年六月三十日→2024-06-30。建议按原文顺序列出独立只读输入框和“复制日期”按钮，同值去重。严格校验历法与已有精度；无效/残缺日期和两位年份不提供建议，不补日、不按证书角色自动选取。沿用证书日期兼容：年月日数字齐全、仅缺“日”时也提供YYYY-MM-DD建议（如2024年6月30）；年份中的O/o按既有规则解释为0，原文不修改。剪贴板不可用或被拒时选中被请求的建议值，原文及草稿保持。切换会话/任务/run/revision/页码、关闭或失去权限时清除建议并忽略旧复制完成。复制建议后仍需人工粘贴和保存。

Review body必须包含当前`run_id`、`expected_revision`；只提交变更字段。`fields`是key->完整值，`absence_reasons`是key->缺省枚举。号码直接显示；人工更正应对照原图输入完整值，仍拒绝把历史掩码作为号码写入。未改变值要确认时提交`accepted_issues:[{issue_id,reason?}]`（reason选填，可一键提交当前允许问题），只接受can_accept=true，MISSING/CONFLICT/INCOMPLETE_OUTPUT/MULTI_CANDIDATES必须补正。空提交或note不清问题。

医疗按item_id改items，added_items新增，removed_item_ids删除；后端重算异常/数值/范围。findings按finding_id更正文本/等级/诊断，以result_item_id关联实际检测项；原件无等级/诊断/结果时留空即可，不编造检测值（界面已不提供absence_reasons下拉，接口仍接受）。report_summary可补源页、作用域、标题、数量以及新增/删除清单，原识别声明另保留。新增ID由服务端分配。

户成员按index+revision编辑，新增/删除成员使用独立列表并保留源页；GENERIC提交`generic:{full_text,key_values:[{key,value,source_pair_id?}]}`生成reviewed_generic，不改原文证据。

FAILED或INCOMPLETE_OUTPUT需要coverage：全部实际源页和未完成区域逐项核对，修正引用本次具体字段/项目等；缺corrected页面证据则重跑，不能仅点完整。人工完成后`recognition_status/recognition_error`保留原执行，`completion_origin=human_review`，original run不改。

409版本冲突保留本地草稿，刷新新run/revision后人工重新判断；禁止自动重试旧修正。成功后刷新结果/版本/预览，confidence保持null，不能显示人工确认等于模型置信度100%。

## 来源预览与导出

缺失字段没有source时展示整页选择，不伪造bbox。GET corrected预览需要operator/admin鉴权、run_id、result_revision、page，直接完整PNG，不再额外要求理由。响应X-Preview-Stage/X-Result-Revision绑定版本；只有同版本corrected图可套来源框，原始本地图不能叠加该框。401需重新登录，409保留草稿刷新。

POST export要求operator/admin，选择`batch_id`或`task_ids`（二选一），`format=xlsx`；legacy masked参数兼容接受但不改变完整值输出；可传覆盖全部所选的versions:[{task_id,run_id,result_revision}]。全批次/勾选/单任务均由服务端检查未筛选结果。任一无保存结果或缺必填值返回409 EXPORT_BLOCKED与details.tasks[].blockers（field/code），整个下载停止，不静默跳过。无需号码揭示理由，正常鉴权和必填值/版本门禁仍有效。

导出检查已保存、未筛选结果的必填值及明确识别异议，不要求审核状态为COMPLETED。按当前profile和字段值解析条件必填；户口本须至少一名成员且每名成员的必填字段有值；GENERIC优先已保存的reviewed_generic（即使为空也不回退），没有人工版本才取识别generic.full_text。None、空串和纯空白为缺失，0与False是已填写；选填空值无需缺省理由。明确的编号位数异常、格式/校验位失败和识别冲突阻止导出，须核对或修正后点击保存；未标定置信度、未联网核验、规则未覆盖和通用覆盖提醒不单独阻止。NEED_REVIEW/FAILED等状态已有保存结果、必填齐全且明确异议已处理也可导出；没有保存结果则阻止。

Task和TaskResult可选返回export_ready:boolean及export_blockers:[{field:string,code:string}]，由同一后端presence检查在医疗筛选前计算。按钮依据已保存版本的export_ready，旧响应未提供时交由服务端判定；未保存编辑须先保存。导出不确认问题、不改recognition/review状态或revision，识别/审核元数据仍保留在应用及审计，不进入业务Excel列。

Excel证件格式保持每份一行、中文标签和最新保存值。体检导出单个“审核记录台账”，每份报告一行，固定18列：序号、姓名、性别、年龄、体检日期、体检机构、报告日期、身高、体重、血压、血常规、尿常规、心电图、DR影像、腹部彩超、肝功五项（生化检测）、体检项目数量、异常指标。异常单元格为原名+结果/单位+诊断，每项独立换行，排除正常、身高、体重、小结，保留BMI；关联结论不重复，未关联结果明确标注。缺值不默认正常，只有完整且无待判定/异常证据才填“无”。原大项清单在界面供计数核对，人员包的人员信息总表同时导出项目名称；18列体检台账本身不加列。户口/通用表保留；编号和公式样式字符串仍为安全文本，长值不静默截断；冻结、筛选、换行、模板蓝/橙表头及列宽已设置。

XLSX各类型一文档一行，医疗检测、清单、户成员、通用正文/KV分表；号码保存为文本、公式字符串不执行，长通用正文分块。导出按钮禁用仅是界面提示，服务器门禁始终有效。


## 批次名称、顺序与时间

批次name/display_name按任务实际材料类型显示，如银行卡、学位证、体检报告；历史通用上传批次也按类型投影，不改原存储。多类型历史批次显示混合材料及类型组合，空/未知类型明确待确定。相同类型的批次以创建时间区分。批次列表按创建时间降序，首次加载、翻页和轮询不能反转顺序，新上传的临时批次保持可见。页面创建时间、检查时间、诊断时间和导出文件日期统一固定UTC+8（Asia/Shanghai），不依赖浏览器所在时区；后端带时区的UTC时间戳和纯业务日期仍保持原值。


## 银行卡离线银行匹配

卡号可靠识别后，后端从本地BIN/IIN表填入bank_name、bin_code及明确覆盖的card_type。bin_code不可编辑，其余字段仍可人工核对/更正。自动值标记value_origin=derived，并附derivation数据来源，不生成伪OCR source；原件可通过卡号来源或整页查看。未知、长度不符、非支持的更具体前缀和冲突均不猜银行。修改卡号会重算旧自动值，人工银行信息不被静默覆盖，但不一致需确认。此表为2020-12-11社区快照，匹配不等于官方真实性校验；confidence保持null，不使用模型额外推理，也不向外网传卡号。

卡号格式不合法（归一化后含非数字或不在10–19位兼容范围）是不可一键确认的FORMAT问题，不能通过确认变成审核完成，且会阻止导出，须修正或使用独立的原件一致确认；银行号段未覆盖和Luhn适用性未知则保留UNKNOWN，允许对照原件人工核对。整图输入不要求上传阶段已读出卡号，后台识别失败进入人工处理。


## 2026-10-09 自动银行卡与批次日历

结果页卡号缺失/冲突/格式失败时显示单张裁剪恢复，可左右90°旋转、提交新任务；上传失败保留已生成裁图供重试，原任务和其他结果保留。仅无置信度/未知银行不要求裁剪。新上传后回到今天所在的所选日/周/月范围以展示新批次。

批次默认只显示今天，日/周/月显示所选日期所在范围，配套date/week/month选择器；固定UTC+8、周一至周日。GET /batches可选date_from/date_to（含首尾当地日期），过滤历史后分页；清空恢复全部日期。切换范围忽略迟到响应，隐藏任务继续监控。

liver_function优先自动填写有来源的异常指标名称、结果/单位和诊断；正常明细可汇总“已识别明细未见异常”，不依赖小结，未知不默认正常或五项齐全。历史派生字段读取/导出刷新，人工值/缺省理由保留。医疗字段明确未载明时展示“报告未载明”，不适用时展示“不适用”，真正缺值展示“未识别”。异常单元格逐项换行；非医疗表头EF760E，医疗蓝/橙不变。


页面单份、批次全部和勾选 Excel 下载统一命名为“识别类型_YYYYMMDD_HHmmss.xlsx”，时间取点击导出时的UTC+8时间，精确到秒。混合材料去重后以+连接类型，缺失/未知类型使用识别结果；命名目标在请求前固定，不随等待期间选择变化。示例：体检报告_20261009_151530.xlsx。工作表名称和内容不因文件命名改变；直接API下载仍使用既有Content-Disposition回退名称。

## 人员材料包（1.22.0）

POST /batches 可选 person_name（1–80字符），人工指定同一个人的材料；省略时保持普通类型批次。不得按OCR或同名自动合并。Batch 增加 person_name、package_revision、id_card_pairing、warnings、expires_at；Task.expires_at为本文件独立到期时间，Batch.expires_at为当前材料最早到期时间。

上传选择“按人员整理”后，无需预填姓名，一次选择混合材料，逐文件修改类型并确认均属同一人。普通按类型批量仍可用。POST /batches 和 POST /batches/{batch_id}/append 使用 multipart：files 与 doc_type_hint / file_types 二选一。file_types 是JSON数组字符串（最多4096字节），顺序对应每个files条目，不能按文件名绑定，长度不符或未知类型422；创建人员包时person_name可省略。追加必须传expected_revision，不能在追加中改person_name。abnormal_only只对包内体检任务生效。202返回batch_id及仅新建的task_ids（重复文件复用时可为空），界面打开对应包。409须刷新版本，不自动重试；断网须先查询确认结果。仅人员包可追加，包括待确认姓名的包；同包相同内容同类型复用，不同类型422；旧结果、人工修正和到期时间不变。

Batch新增is_person_package:boolean，独立于person_name。name_suggestions为{name,sources:[{task_id,doc_type,file_name}]}数组，从已保存的姓名/持卡人姓名字段推导；不从户主、法人或通用正文猜测。不同姓名保留并提示差异，不自动归属、合并或移动文件。PATCH /batches/{batch_id}/person接受{person_name,expected_revision}，仅包所属operator或admin可写，成功200返回Batch；与追加共享package_revision，冲突409。确认姓名加密保存，后续识别不覆盖。界面可使用建议、手工填写或修改；建议不是身份核验。

人员包Excel第一张为“人员信息总表”，一包一行：人员姓名、姓名状态在前，随后按材料类型列出本次所选材料的全部当前业务字段（包括选填及空值列），最后为类型及数量、份数和姓名候选（注明材料类型，不含文件名）。字段带类型前缀；同类多份材料用编号分组，每组完整保留业务字段，互不覆盖；所有工作表不附加来源文件列。跨包导出列取本次选择的字段并集，缺少该组的行留空；不读取未选中任务。体检包含全部17个profile字段及异常指标，尤其保留体检项目名称；户口成员编号展开，通用正文分段并保留重复键值。冻结前两列与表头，可横向滚动。后面继续保留分类明细和精确18列体检台账。未确认姓名显示“姓名待确认”，不新增导出门禁；仍要求已保存必填值齐全且无未处理的明确异议。文件名为人员材料包_北京时间.xlsx；普通批次格式和名称规则不变。超过Excel列数或单元格容量明确报错，不静默截断。

POST /classify multipart仅含一个files条目，需operator/admin及会话CSRF；不创建批次或任务、不保存原图，返回 `{doc_type: DocTypeEnum|null, basis: 'content'|'filename'|'unknown', reason: string, candidates: DocTypeEnum[]}`。内容分类优先，文件名提示明确标注；unknown或失败必须允许手动选择，所有建议均可改。客户端顺序分类，不覆盖手动选择；移除文件、切换模式或注销时丢弃过期响应。PDF只检查前两页，不自动拆分混合证件PDF；不据分类结果判断人员归属或显示伪造准确率。

id_card_pairing为unassigned/not_provided/missing_front/missing_back/both_present，只反映本包上传类型的存在性，失败或排队任务也计入；missing_back显示“国徽面未上传（可选，可仅识别人像面）”，无MISSING_ID_BACK告警。人像面独立识别/导出，不要求国徽面任务或字段；如另传国徽面，其独立任务仍应用本类型配置。both_present不保证同一人或真实性。提示不增加导出门槛。已完成批次的任务刷新失败仍保持待刷新标记，成功读取才清除，旧会话响应不能恢复缓存。

同账号只保留一个浏览器登录，新登录成功即撤销该账号旧会话；同一浏览器多标签共用，其他浏览器或配置文件也会替换。旧页面在下一次受保护请求收到401后回登录；接受的任务不中断。登录失败不撤销旧会话，轮询不延长30天绝对有效期。

接口授权边界：业务路由默认要求登录，再按角色和不可变批次归属校验；写入事务及预览/Excel/自动分类等耗时响应前复验会话。前端隐藏按钮不代替后端权限。401结束登录；403提示权限变化，不自动重放操作。退出和切换登录清除引擎详情并废弃旧健康请求，未登录只读取根路径status。

接口权限加固及验收见[授权边界记录](.agents/notes/implemented/bug-fix/2026-10-13-api-authorization-boundaries.md)。

## 照片表格 TABLE（1.23.0）

上传使用普通`doc_type_hint=TABLE`，只接收单张照片文件，每个文件独立任务；不支持PDF、人员包file_types/追加和必填字段设置。入口名“表格”。

`header_suggestion`可为0或null，新增可选`header_suggestion_source`（`model_tags`/`structure`/`data_rows`/null）说明判断依据。首次草稿仅对结构完整且来源已知的建议自动填入表头行数并高亮；没有可靠依据时手选，不固定建议1。初始`header_rows`仍为null，保存后写入`reviewed_tables`；已经保存的0、null和人工行数均优先。旧结果没有来源属性时不自动采用旧建议，避免旧的固定1被误当自动识别结果。不增加模型调用，不更改矩阵或原标题字体。

`TaskResult.tables`保存初始主体（0或1个，失败可能无主体）；`reviewed_tables`保存人工版本。结构为`table_id,title,header_rows,rows:string[][],merges:[{row,column,rowspan,colspan}],partial_acknowledged`。行列下标从0起；被合并覆盖的格必须为空。原始主体另有`source,title_candidates,header_suggestion,candidates,outside_text,quality_warnings,incomplete,confidence:null`。候选文字box为校正图片像素，source/candidates的bbox为归一化xyxy；候选不直接视为已确认内容。

审核接口提交`run_id,expected_revision,tables:[人工结构]`；禁止修改来源或混入fields/items等业务载荷。可保存未完成草稿，`export_ready/export_blockers`才是导出依据。没有人工版本时，页面与导出都按原有匹配顺序采用首个有效非空标题候选和带来源的完整表头建议，不强制首次保存；空白、超过200字或含控制字符的标题候选跳过，保留其他候选供切换。存在`reviewed_tables`时完全优先，包括空标题和null/0表头。表格标题选填，明确的表头行数和有效矩阵必需；0代表无表头，null尚未确认。原始不完整输出需要保存partial_acknowledged=true。所有空格仍可留空。导出不改变状态/版本，不生成虚假人工审核；未保存的修改阻止详情页导出。列表显示“可直接导出”或“导出待处理”，并区分表头、无表格、结构或完整性问题；标题留空不标红、不阻止导出。

详情编辑保持原始矩阵不可变；分页不裁掉导出行，插删按选中位置操作，非空删除确认、合并覆盖拒绝。保存冲突保留草稿。主体错误时复用裁剪入口创建新的TABLE批次；框选OCR只辅助复制文字。来源定位对TABLE可用。

导出单TABLE返回XLSX，多TABLE返回ZIP；读取Content-Disposition的UTF-8文件名并过滤非法文件名，回退为表格.xlsx/表格.zip。不和其他材料/人员包混合导出。下载名优先使用标题；无标题用原图片名去扩展名，原名不可用则用“表格_北京时间YYYYMMDD_HHMMSS”，ZIP同名加序号。照片表格有标题时标题单独第一行21号，矩阵从第二行开始；无标题直接从第一行开始，不插空白标题行，冻结/筛选/打印表头/合并范围同步上移。表头/数据12号；所有现有Excel同样改为12号，数据区域统一白色底色，旧结构及表头配色不变。

## 通用表单动态字段（1.24.0）

GENERIC主识别改为Paddle，复用CPU摆正与布局检测，失败/截断时在180秒总预算内最多回退一次GLM/区域。可靠PDF原生文本不调用模型。

`generic.key_values[]` 可附 `pair_id`、`source`、`basis`（label/aligned_label/table_cells/header_value）；重复key和空value保留。来源优先实际cell/block，否则明确标为region。`blocks[]`增加可选`raw_text/source`；`tables[]`保留rows/merges/source供只读对照。旧结果没有这些字段仍可打开。

人工draft通过source_pair_id引用原始pair，删除/排序/改名不串来源；新增字段及旧人工版本不按序号猜来源，后端拒绝伪造坐标或未知ID。详情允许GENERIC来源定位，原文和OCR标记以纯文本显示。保存版本始终优先，修改后必须保存才能导出；所有已保存键值、空值、重复值及正文沿用既有Excel导出，不改变人员包规则。


## 银行卡复印件（1.25.0）

入口与doc_type保持BANK_CARD。profile前四项为holder_name（姓名）、card_number（卡号）、bank_name（开户行）、branch_name（开户支行）。分支新增为可编辑选填，管理员配置仍优先；旧结果读取时补空字段、更新显示标签和顺序，不重写已保存人工值。bank_name复用旧key，不能将其当作具体网点。

Field.candidates可带reason和source，用于区分卡面与补充文字候选；Field.sources保留相同值的多处证据。银行卡来源按钮复用corrected页和归一化bbox，属于区域定位，不是逐字定位。选择候选仅修改前端草稿，必须保存；旧识别候选仍保留供追溯。卡号冲突时后端value为空，默认阻止导出；人工保存后按必填值及明确异议门禁执行；仅信息性的待审核提示不阻止。照片裁剪恢复入口与整页框选OCR仍可使用。

## 个人工作台布局

`GET /api/v1/auth/me/workbench` 返回 `{layout: string[] | null, revision: number, defaults: {layout: string[] | null, revision: number}}`；`PUT` 仅接受 `{layout, expected_revision}`。只使用当前命名账号会话和CSRF，不传user_id，管理员也只修改自己的布局。数组保存类型顺序偏好（兼容上一版最多13个键，不能重复或含未支持类型）；界面始终最多展示12张，多出的类型和未列出的类型自动收纳。个人layout=null继承defaults.layout，defaults.layout=null才回到系统目录；[]为全部收纳。新增类型在自定义布局中默认收纳。

读取成功后可编辑，拖拽和收纳先改草稿，点击“完成”才保存。网络失败保留草稿，409 WORKBENCH_VERSION_CONFLICT保留原版本并禁止自动重试；“重新读取”需确认放弃未保存调整，读失败仍保留原草稿。恢复默认先将草稿设为null，完成后保存。不导入旧浏览器共享键；切换账号取消请求并清空状态，迟到响应不能恢复上一账号布局。

管理员在自定义入口中另有“设为默认布局”，确认影响后调用`PUT /api/v1/admin/workbench-default`，正文`{layout, expected_revision}`使用defaults.revision。保存当前可见顺序；只更新defaults，不提交个人草稿，也不退出编辑。返回`{layout,revision}`。冲突码为WORKBENCH_DEFAULT_VERSION_CONFLICT。后端在同一写事务复验管理员身份；普通账号不能调用。已有个人数组（包括[]）不随公共默认改变，继承账号在重新进入页面/读取时更新。


## 面试登记表 INTERVIEW_FORM（1.26.0）

固定字段顺序为name（姓名，string）、gender（性别，M/F）、age（年龄，integer）、id_number（身份证号，string）、mobile_number（手机号，string），均可为null，默认全部必填。现有管理员必填配置、历史任务缺失标记、审核保存和人员包总表均适用。按保存后的必填值及明确异议判定导出；未标定置信度不阻止，明确编号位数/格式/校验失败和冲突需处理；身份证号和手机号按文本导出。

默认Paddle表格识别基本信息区域，缺失、格式疑点、冲突或不完整时，剩余任务预算内最多一次GLM普通OCR补读；单次生成软预算20秒。候选保留来源，冲突不覆盖，错栏身份证号和栏外姓名只能人工采用后保存。性别必须来自本栏文字或明确勾选；不由身份证号推导性别和年龄，不从紧急联系人取本人手机号。复用银行卡候选“查看来源／采用”交互，采用只修改草稿。未标定confidence保持null。

所有识别入口复用保守照片摆正；无可靠文字层的纯扫描PDF逐页摆正并缓存决定，两次解码像素和来源坐标一致。原生／混合文字页保持原路径，不自动透视矫正。既有自定义布局不重写，新类型默认收纳；识别目录当前有13种，但工作台最多展示12张，默认排列也受此限制。

## 编号位数提示

结果页和人工填写框共用`numberLengthHint`，分别基于已保存值和当前草稿显示提示。身份证号、统一社会信用代码按18位提示；银行卡复用现有离线BIN资料的对应长度，优先最长前缀，遇到未支持或冲突记录不猜位数，未命中时只显示当前位数和未知提示；10–19位仅为本系统兼容范围。银行卡的空格、分隔横线及全角数字只在计数副本中处理，绝不改写输入值。

毕业证和学信网证书编号以常见17/18位为参考，较短的早期或其他类型编号只作信息提示；学位编号参考16位并兼容历史T/Z前缀17位，旧式或特殊编号以原件为准。学信网在线验证码沿用12/16位兼容提示。银行卡资料可能过时，参考长度不等于官方核验；长度符合也不等于校验码或真伪通过。空值仍使用必填缺失提示。原始证据和人工值不变，历史任务无需重新识别即可显示。warning级位数异常同时进入后端导出门禁，info级未知/旧式编号不单独阻止导出。

前端银行卡参考文件由`scripts/build_bank_length_reference.py`从后端已固定哈希的资料生成并提交，前端构建不额外依赖Python。更新资料时重生成，并运行该脚本的`--check`和前端数据一致性测试。规则边界与来源见[编号提示决策](.agents/notes/implemented/feature/2026-10-14-number-length-review-hints.md)。


## 识别异议与导出（2026-10-14）

医疗清单未选结果关联、检测结果为空或项目诊断候选未选定时，相关异议的can_confirm=false；普通保存、其他属性修改及历史确认均不能跳过。人工选定或明确说明选填内容缺省后沿用现有保存流程。

必填缺失和明确识别异议分别提示：编号位数异常、明确的格式/校验失败、识别结果冲突会阻止单份、勾选、本批次全部及人员材料包导出；任一所选任务未处理则整次409 EXPORT_BLOCKED。置信度未标定、未联网核验、规则未覆盖只作信息提示。表格现有标题、表头、结构与完整性门禁不变。

Task.export_blockers增加DISPUTED，批次显示“有异议”的任务数、字段名并支持筛选；筛选不改变本批次全部的导出范围，两个筛选同时选中时显示缺必填或有异议的任务并集。TaskResult.export_disputes提供当前未解决异议的dispute_id/field/label/code/message/can_confirm。操作员核对当前内容后，点击下方“保存修正并重新校验”即可保存并完成异议核对，不另设确认按钮。网页通过review的confirm_export_disputes=true提交；服务端先应用修正和重校验，再确认保存后所有可确认的异议，整个流程沿用同一run_id和expected_revision事务。省略该标记的接口调用仍只修正，不自动确认；既有confirmed_disputes接口保持兼容。无需填写理由，服务端保存确认账号和时间；来源证据、原值和置信度不变。没有明确值的候选冲突须先选择/填写，必填缺失不能确认跳过。后续修改相关值/上下文时旧确认失效；经保存按钮再次核对后记录新确认。重新识别须重新核对。历史结果实时应用，无需重新跑模型。此确认表示操作员核对原件，不代表官方真伪核验。

## 文件保留设置

管理员专用GET/PUT /admin/retention：days为7/15/30/null（永不清除），初始7天；revision独立于任务结果版本。GET包含assessed_at与三个有限选项的eligible_count/active_count快照。PUT发送days、expected_revision、confirmed:true，保存前必须弹窗说明新旧文件统一按原上传日期计时、超期数量、删除范围及不可恢复；取消不请求。409 RETENTION_VERSION_CONFLICT保留选择，重新读取后再次确认，不自动重放。所有账号共用服务端设置，禁止本地覆盖。保存后刷新批次。

Task.expires_at和Batch.expires_at支持null，显示“永不自动清除”；有限时显示服务端日期（UTC+8），禁止前端按created_at+7天推算。批次日期为当前剩余文件最早到期时间。设置不会修改识别内容、人工修正、任务状态或结果版本。

## 操作审计（管理员）

新增管理员标签页“操作审计”，仅当前登录角色为admin且标签页激活时挂载；退出、切账号和离开页面会清空数据并终止读取。GET `/admin/audit/options` 提供操作者、操作与结果选项；GET `/admin/audit/events` 支持 `date_from/date_to/actor/event/outcome/batch_id/page/page_size`，返回 `items/total/page/page_size/next_cursor`；兼容旧 `cursor/limit` 模式，但不得混传，旧模式也返回筛选后全量 `total`。默认近7个北京时间自然日，每页50条，按时间和事件ID降序；更换筛选回到首页。`actor` 为不可变账号ID，显示使用事件当时的 `identity`，不得用当前账号姓名回填旧记录。

列表只提供账号登录/管理、上传/追加、导出、删除批次、手动重跑/取消和全局设置操作。后台先按同一规则过滤历史，再分页、生成筛选选项和导出；系统状态、原图/字段访问、框选识别、人员确认、保存修正及导出requested过程不在产品审计中出现。新上传/追加/删除/导出按一次提交合并记录，缺少request_id的旧单份记录不强行合并。匿名登录失败标为未验证身份，不冒充输入账号。

表格显示北京时间、操作者、中文操作说明、关联对象和结果；移除技术详情和修改前后抽屉。`description`包含材料数量及设置变化，`object_label`为加密快照解出的批次类型/时间或目标账号；旧记录关联批次已清理时回退编号，不编造名称。`outcome`沿用success/failure/requested/legacy契约，但新产品查询不返回requested；legacy仍表示未知。`export_generated`仅代表服务端生成文件，不代表浏览器已保存。

GET `/admin/audit/events/{event_id}` 保留兼容的摘要/context结构，但排除的记录返回404，`changes=[]`、`history_state=not_applicable`，不读取材料修正产物。原人工版本与访问历史按原规则保留，不因简化审计被删除。页面禁止提供审计修改/删除按钮。

GET `/admin/audit/export` 使用当前筛选条件导出全部匹配摘要，最多10000条，超限422要求缩小范围；列为时间、姓名、账号、操作、关联对象、结果。接口均须管理员权限，读取或生成后复验会话；前端隐藏入口不能替代后端鉴权。


任务批次、操作审计和账号管理统一使用数字分页（总数、每页20/50/100条、上一页、页码、下一页、跳转），批次/审计默认50条，账号默认20条。批次复用既有服务端分页，当前页ID与监控缓存分开；翻页不清除其他任务的进度、版本或待处理操作。账号保留全量读取和客户端分页，最后管理员判断仍基于全部账号。切日期/提交筛选/改每页数量回到首页；删除或数量减少导致页码越界时回到有效末页。失败保留已显示页，旧日期/页码/会话的迟到响应不能覆盖新页。审计总数与列表同一读取快照，实时新增可能改变后续页的位置；Excel仍按完整筛选导出，最多10000条。
