<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import type { Component } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadUserFile } from 'element-plus'
import { CreditCard, Files, FirstAidKit, Medal, Notebook, OfficeBuilding, Postcard, Reading, Stamp, UploadFilled, User } from '@element-plus/icons-vue'
import { ApiFailure, isAbort } from '../api.ts'
import { docTypes, sampleQualification, uploadLimits, validateUpload } from '../business.ts'
import type { BusinessApi } from '../api.ts'
import type { Batch, DocProfile, Task, UploadDocType } from '../business.ts'
import { errorMessages } from '../diagnostics.ts'
import type { Monitor } from '../monitor.ts'
import { createClassificationQueue } from '../packageUpload.ts'

const props = defineProps<{ monitor: Monitor; canWrite: boolean; api: BusinessApi | null; catalogue: DocProfile[]; targetBatch?: Batch }>()
const emit = defineEmits<{
  (e: 'submitted', batchId: string): void
  (e: 'preview', files: File[], tasks: Task[]): void
  (e: 'unauthorized'): void
}>()

const docType = ref<UploadDocType>('MEDICAL_REPORT')
const abnormalOnly = ref(false)
// 默认按类型批量（集中处理同一种材料）；按人员整理由操作员主动切换。
const personPackage = ref(false)
const mixed = computed(() => !!props.targetBatch || personPackage.value)
const fileList = ref<UploadUserFile[]>([])
const submitting = ref(false)
let submitController: AbortController | undefined
let uploadInFlight = false
let disposed = false
const rows = reactive<Record<number, { type: UploadDocType | ''; state: string; reason: string; preview: string }>>({})
const classifier = createClassificationQueue(
  (file, signal) => { if (!props.api) throw new Error('NOT_CONNECTED'); return props.api.classify(file, signal) },
  (uid, result, processing) => {
    const row = rows[uid]; if (!row) return
    row.state = processing ? '分类中' : result?.doc_type ? (result.basis === 'content' ? '内容分类' : '文件名提示') : '待选择'
    if (!processing) { row.type = result?.doc_type ?? ''; row.reason = result?.reason ?? '自动分类失败，请手动选择类型' }
  },
  error => { if (error instanceof ApiFailure && error.card.http_status === 401) emit('unauthorized') },
)
function releaseRow(uid: number) {
  classifier.remove(uid)
  if (rows[uid]?.preview) URL.revokeObjectURL(rows[uid]!.preview)
  delete rows[uid]
}
onBeforeUnmount(() => {
  disposed = true
  if (submitController) {
    // 组件被卸载（如追加弹窗被关闭）而上传仍在途时，catch 里的提示已被 disposed 拦下；
    // 在这里补一条「可能已被服务端接收」的警示并刷新，避免操作员误以为提交丢失。
    submitController.abort()
    if (uploadInFlight) {
      props.monitor.start()
      ElMessage.info('上传已停止：服务端可能已接收，请查看任务列表确认后再决定是否重试。')
    }
  }
  classifier.dispose()
  Object.keys(rows).forEach(uid => releaseRow(Number(uid)))
})

const typeMeta: Partial<Record<UploadDocType, { icon: Component; desc: string }>> = {
  MEDICAL_REPORT: { icon: FirstAidKit, desc: '检测项目与报告清单分开核对。' },
  DIPLOMA: { icon: Reading, desc: '毕业证字段与来源核对。' }, DEGREE_CERT: { icon: Medal, desc: '学位级别与授予信息。' },
  BANK_CARD: { icon: CreditCard, desc: '整张照片自动识别，未读出卡号再单独裁剪或补录。' },
  ID_CARD_FRONT: { icon: Postcard, desc: '身份证人像面。' }, ID_CARD_BACK: { icon: Postcard, desc: '身份证国徽面及有效期。' },
  PASSPORT: { icon: Stamp, desc: '护照 TD3 资料页和机读区。' }, HOUSEHOLD_REGISTER: { icon: Notebook, desc: '首页与成员页。' },
  BUSINESS_LICENSE: { icon: OfficeBuilding, desc: '按主体类型整理执照字段。' }, GENERIC: { icon: Files, desc: '通用全文与可编辑键值。' },
  XUEXIN_DIPLOMA_TABLE: { icon: Reading, desc: '仅学历证书电子注册备案表。' },
}
const selectedFiles = computed<File[]>(() => fileList.value.flatMap(item => (item.raw instanceof File ? [item.raw] : [])))
const invalidReason = computed(() => (selectedFiles.value.length ? validateUpload(selectedFiles.value) : null))
const entries = computed(() => fileList.value.filter(item => item.raw instanceof File && item.uid !== undefined))
const unknownCount = computed(() => mixed.value ? entries.value.filter(item => !rows[item.uid!]?.type).length : 0)
const hasMedical = computed(() => mixed.value ? entries.value.some(item => rows[item.uid!]?.type === 'MEDICAL_REPORT') : docType.value === 'MEDICAL_REPORT')
watch([() => fileList.value.map(item => item.uid).join(','), mixed, () => props.api, () => props.canWrite], () => {
  const current = new Set(mixed.value ? entries.value.map(item => item.uid!) : [])
  Object.keys(rows).map(Number).filter(uid => !current.has(uid)).forEach(releaseRow)
  if (!mixed.value) return
  for (const item of entries.value) {
    if (rows[item.uid!]) continue
    const file = item.raw!
    rows[item.uid!] = { type: '', state: '等待分类', reason: '', preview: /\.(?:jpe?g|png)$/i.test(file.name) ? URL.createObjectURL(file) : '' }
    if (props.canWrite && props.api && !validateUpload([file])) classifier.add(item.uid!, file)
    else { rows[item.uid!]!.state = '待选择'; rows[item.uid!]!.reason = '请核对文件并手动选择类型' }
  }
}, { flush: 'sync' })
function manualType(uid: number, type: UploadDocType | '') {
  classifier.remove(uid)
  const row = rows[uid]; if (row) Object.assign(row, { type, state: '手动选择', reason: '以你选择的类型提交' })
}
function retryClassify(item: UploadUserFile) {
  if (!item.raw || item.uid === undefined || validateUpload([item.raw])) return
  const row = rows[item.uid]; if (row) Object.assign(row, { type: '', state: '等待分类', reason: '' })
  classifier.add(item.uid, item.raw)
}
function removeFile(uid: number) { if (!submitting.value) fileList.value = fileList.value.filter(item => item.uid !== uid) }

const typeCounts = computed(() => {
  const counts = new Map<UploadDocType, number>()
  for (const item of entries.value) {
    const type = rows[item.uid!]?.type
    if (type) counts.set(type, (counts.get(type) ?? 0) + 1)
  }
  return [...counts.entries()]
})
function stateClass(state?: string) {
  if (state === '分类中' || state === '等待分类') return 'is-working'
  if (state === '待选择') return 'is-pending'
  return ''
}

function onExceed() { ElMessage.warning(`一次最多提交 ${uploadLimits.maxFiles} 个文件。`) }

// Preserve explicit single-type batch switching; mixed rows have their own type.
async function selectType(type: UploadDocType) {
  if (type === docType.value) return
  if (selectedFiles.value.length === 0) { docType.value = type; return }
  try {
    await ElMessageBox.confirm(
      `已选择 ${selectedFiles.value.length} 个文件，切换到「${docTypes[type]}」将清空这些未提交的文件。`,
      '切换证件类型',
      { type: 'warning', confirmButtonText: '切换并清空', cancelButtonText: '留在当前类型' },
    )
  } catch { return }
  docType.value = type
  fileList.value = []
}

function cancelSubmit() { submitController?.abort() }

// 未提交文件只是待选引用，一键清除可让操作员快速重新挑选；提交中禁止清除以免状态错乱。
function clearFiles() { if (!submitting.value) fileList.value = [] }

async function submit() {
  if (disposed || submitting.value || !props.api) return
  const client = props.api
  const monitor = props.monitor
  const files = [...selectedFiles.value]
  const useMixed = mixed.value
  const chosenType = docType.value
  const onlyAbnormal = abnormalOnly.value
  const target = props.targetBatch ? { ...props.targetBatch } : undefined
  const activeSession = () => !disposed && props.api === client && props.monitor === monitor
  const problem = validateUpload(files)
  if (problem) { ElMessage.warning(problem); return }
  if (!props.canWrite) { ElMessage.warning('当前账号为只读角色，无法上传文件。'); return }
  const types = useMixed ? entries.value.map(item => rows[item.uid!]?.type ?? '') : files.map(() => chosenType)
  if (types.some(type => !props.catalogue.some(p => p.doc_type === type))) { ElMessage.warning('请为每个文件选择材料类型；可以等待自动分类，也可以直接手动选择。'); return }
  if (files.some((file, index) => types[index] === 'BANK_CARD' && !/\.(?:jpe?g|png|heic)$/i.test(file.name))) {
    ElMessage.warning('银行卡请上传单张 JPG/PNG/HEIC 照片，不接收 PDF。'); return
  }
  const controller = new AbortController()
  submitController = controller
  submitting.value = true
  try {
    if (useMixed) {
      try {
        const summary = [...new Set(types)].map(type => `${docTypes[type as UploadDocType]} ${types.filter(value => value === type).length} 份`).join('、')
        await ElMessageBox.confirm(`确认这 ${files.length} 个文件均属于${target?.person_name ? `「${target.person_name}」` : '同一人'}？${summary}。识别后可确认或修改人员姓名；请核对自动分类与人员归属。`,
          target ? '确认追加归属' : '确认人员归属', { confirmButtonText: '已核对，提交', cancelButtonText: '取消', type: 'warning' })
      } catch { return }
    }
    // Confirmation may outlive the component/login or an external batch update.
    if (!activeSession() || controller.signal.aborted || !props.canWrite) return
    if (mixed.value !== useMixed || docType.value !== chosenType || abnormalOnly.value !== onlyAbnormal ||
      selectedFiles.value.length !== files.length || files.some((file, index) => selectedFiles.value[index] !== file) ||
      useMixed && entries.value.some((item, index) => rows[item.uid!]?.type !== types[index]) ||
      props.targetBatch?.batch_id !== target?.batch_id || props.targetBatch?.package_revision !== target?.package_revision) {
      ElMessage.warning('所选材料或材料包已更新，请重新核对后提交。'); return
    }
    uploadInFlight = true
    const created = await monitor.submitUpload(files, chosenType, onlyAbnormal, controller.signal,
      { targetBatch: target, fileTypes: useMixed ? types as UploadDocType[] : undefined })
    if (!activeSession() || controller.signal.aborted) return
    if (created.task_ids.length) {
      try {
        const tasks = await client.tasks(created.batch_id, controller.signal)
        if (activeSession() && !controller.signal.aborted) emit('preview', files, tasks.filter(t => created.task_ids.includes(t.task_id)))
      } catch { /* Accepted uploads must not be reported as failed when preview binding fails. */ }
    }
    if (!activeSession() || controller.signal.aborted) return
    emit('submitted', created.batch_id)
    fileList.value = []
    ElMessage.success(created.task_ids.length ? `已提交 ${created.task_ids.length} 个新识别任务。` : '相同文件已在材料包中，本次未重复创建任务。')
  } catch (error) {
    if (!activeSession()) return
    if (isAbort(error)) { monitor.start(); ElMessage.info('已停止等待上传响应；服务端可能已接收，请先查看任务列表。') }
    else if (error instanceof ApiFailure) {
      if (error.card.http_status === 401) emit('unauthorized')
      else if (['NETWORK_ERROR', 'REQUEST_TIMEOUT'].includes(error.card.code)) { monitor.start(); ElMessage.warning('上传结果未确认，请先刷新任务批次，确认是否已接收后再重试。') }
      else if (error.card.http_status === 409) { monitor.start(); ElMessage.warning('材料包已更新，请关闭追加窗口，刷新后重新确认。') }
      else ElMessage.error(errorMessages[error.card.code])
    } else ElMessage.error(errorMessages.UNKNOWN_ERROR)
  } finally {
    uploadInFlight = false
    submitting.value = false
    submitController = undefined
  }
}
</script>

<template>
  <section class="upload-panel">
    <el-alert v-if="targetBatch" type="info" :closable="false" show-icon class="upload-tip">
      正在向「{{ targetBatch.person_name || '姓名待确认' }}」的材料包追加。一次选齐要补充的材料，核对类型后统一提交。
    </el-alert>

    <div v-else class="mode-bar" role="group" aria-label="上传方式">
      <div class="mode-switch">
        <button type="button" class="mode-option" :class="{ active: personPackage }" :disabled="submitting" :aria-pressed="personPackage" @click="personPackage = true">
          <el-icon><User /></el-icon>按人员整理
        </button>
        <button type="button" class="mode-option" :class="{ active: !personPackage }" :disabled="submitting" :aria-pressed="!personPackage" @click="personPackage = false">
          <el-icon><Files /></el-icon>按类型批量
        </button>
      </div>
      <span class="mode-hint">{{ personPackage ? '选齐此人的各类材料，核对类型后整包提交；识别后再确认姓名。' : '选定一种材料类型，集中批量处理同一种材料。' }}</span>
    </div>
    <div v-if="!mixed" class="type-cards">
      <button
        v-for="profile in catalogue"
        :key="profile.doc_type"
        type="button"
        class="type-card"
        :class="{ active: docType === profile.doc_type }"
        :disabled="submitting"
        @click="selectType(profile.doc_type)"
      >
        <span class="type-head">
          <el-icon><component :is="typeMeta[profile.doc_type]?.icon ?? Files" /></el-icon>
          <span class="type-title">{{ profile.label }}</span>
        </span>
        <p class="type-desc">{{ typeMeta[profile.doc_type]?.desc }}</p>
      </button>
    </div>

    <el-card shadow="never" class="upload-card">
      <div v-if="mixed && !targetBatch" class="package-head">
        <span>无需先填写姓名，识别后会显示姓名建议；请只放入同一人的材料。</span>
      </div>
      <el-alert type="info" :closable="false" class="upload-tip">{{ mixed ? '自动分类只是建议，可以直接修改下方类型。每个文件应是一种材料；混合了不同证件的PDF请先拆分。部分类型尚缺真实样本验收，识别结果仍需对照原件核对。' : sampleQualification(docType) }}</el-alert>
      <el-upload
        v-model:file-list="fileList"
        drag
        multiple
        action="#"
        :auto-upload="false" :disabled="submitting"
        :show-file-list="!mixed"
        accept=".pdf,.jpg,.jpeg,.png,.heic"
        :limit="uploadLimits.maxFiles"
        :on-exceed="onExceed"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">{{ mixed ? '将此人的各种材料一起拖到此处，或' : `将${docTypes[docType]}文件拖到此处，或` }} <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">支持 JPG / PNG / HEIC / PDF，单文件 ≤ {{ uploadLimits.maxFileMB }} MB，每批 1–{{ uploadLimits.maxFiles }} 个文件、总计 ≤ {{ uploadLimits.maxBatchMB }} MB。</div>
        </template>
      </el-upload>

      <div v-if="mixed && entries.length" class="package-summary" aria-label="已选材料统计">
        <el-tag v-for="[type, count] in typeCounts" :key="type" size="small" effect="plain">{{ docTypes[type] }} × {{ count }}</el-tag>
        <el-tag v-if="unknownCount" size="small" type="warning" effect="plain">待选择类型 × {{ unknownCount }}</el-tag>
      </div>

      <div v-if="mixed && entries.length" class="material-list">
        <article v-for="(item, index) in entries" :key="item.uid" class="material-row">
          <img v-if="rows[item.uid!]?.preview" :src="rows[item.uid!]!.preview" alt="材料缩略图" class="material-thumb" />
          <el-icon v-else class="material-thumb material-thumb-icon"><Files /></el-icon>
          <div class="material-info">
            <strong class="material-name">{{ index + 1 }}. {{ item.name }}</strong>
            <small class="material-state" :class="stateClass(rows[item.uid!]?.state)">{{ rows[item.uid!]?.state }} · {{ rows[item.uid!]?.reason || '正在读取内容，仅用于建议材料类型' }}</small>
          </div>
          <el-select :model-value="rows[item.uid!]?.type || ''" :aria-label="`材料类型：${item.name}`" placeholder="待选择类型" :disabled="submitting" class="material-type" @update:model-value="type => manualType(item.uid!, type)">
            <el-option v-for="profile in catalogue" :key="profile.doc_type" :label="profile.label" :value="profile.doc_type" />
          </el-select>
          <div class="material-actions">
            <el-button text size="small" :disabled="submitting" @click="retryClassify(item)">重新分类</el-button>
            <el-button text size="small" type="danger" :disabled="submitting" @click="removeFile(item.uid!)">移除</el-button>
          </div>
        </article>
        <p v-if="unknownCount" class="upload-hint">还有 {{ unknownCount }} 份材料待选择类型，可直接手动选择，无需等待自动分类。</p>
      </div>

      <el-alert v-if="invalidReason" type="warning" :closable="false" show-icon class="upload-invalid">{{ invalidReason }}</el-alert>

      <div v-if="hasMedical" class="upload-row">
        <el-switch v-model="abnormalOnly" :disabled="submitting" active-text="仅整理异常与待判定项" />
        <span class="upload-hint">仅改变默认结果展示范围；复核和导出仍按完整结果检查，不承诺加速。</span>
      </div>

      <div class="upload-row upload-footer">
        <span class="upload-hint" :class="{ 'at-limit': selectedFiles.length >= uploadLimits.maxFiles }">已选择 {{ selectedFiles.length }} / {{ uploadLimits.maxFiles }} 个文件</span>
        <div class="upload-actions">
          <el-button v-if="selectedFiles.length && !submitting" @click="clearFiles">一键清除</el-button>
          <el-button v-if="submitting" @click="cancelSubmit">取消上传</el-button>
          <el-button type="primary" :loading="submitting" :disabled="!canWrite || !catalogue.length || !!unknownCount || !!invalidReason" @click="submit">
            {{ submitting ? '正在上传…' : `${mixed ? (targetBatch ? '统一追加' : '整包提交') : '开始识别'}（${selectedFiles.length || ''}）` }}
          </el-button>
        </div>
      </div>
      <div v-if="!canWrite" class="upload-hint readonly-hint">当前账号为只读角色，仅可查看任务与结果。</div>
    </el-card>
  </section>
</template>

<style scoped>
.upload-tip { margin-bottom: 16px; }
.upload-card { border-radius: 10px; }
.upload-invalid { margin-top: 12px; }
.upload-actions { display: flex; gap: 8px; }
.readonly-hint { margin-top: 8px; color: var(--el-color-warning); }
.type-head { display: inline-flex; align-items: center; gap: 6px; }
.at-limit { color: var(--el-color-warning); font-weight: 600; }
.material-list { margin-top: 4px; display: grid; gap: 10px; }
.material-row { display: grid; grid-template-columns: 56px minmax(0, 1fr) 210px auto; gap: 12px; align-items: center; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; background: #fff; transition: border-color .2s, box-shadow .2s; }
.material-row:hover { border-color: var(--el-color-primary-light-5); box-shadow: 0 2px 10px rgba(15, 157, 143, .08); }
.material-thumb { width: 56px; height: 56px; object-fit: contain; flex: none; background: var(--el-fill-color-light); border-radius: 8px; display: block; }
/* el-icon 分支需覆盖 .material-thumb 的 display:block，恢复居中弹性布局；声明顺序在后以胜出。 */
.material-thumb-icon { display: flex; align-items: center; justify-content: center; font-size: 24px; color: var(--el-text-color-secondary); }
.material-info { min-width: 0; }
.material-name { display: block; overflow-wrap: anywhere; }
.material-state { display: block; margin-top: 4px; color: var(--el-text-color-secondary); }
.material-state::before { content: ''; display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--el-text-color-placeholder); margin-right: 6px; vertical-align: 1px; }
.material-state.is-working::before { background: var(--el-color-primary); }
.material-state.is-pending::before { background: var(--el-color-warning); }
.material-type { width: 210px; }
.material-actions { display: flex; gap: 2px; justify-content: flex-end; }
/* 上传方式：紧凑分段开关，与下方大面积的证件类型卡片在视觉上区分层级。 */
.mode-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.mode-switch { display: inline-flex; background: var(--el-fill-color-light); border: 1px solid var(--el-border-color-lighter); border-radius: 999px; padding: 3px; }
.mode-option { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; padding: 7px 18px; border-radius: 999px; font: inherit; font-size: 14px; color: var(--el-text-color-regular); cursor: pointer; transition: color .2s, background .2s, box-shadow .2s; }
.mode-option:hover { color: var(--el-color-primary); }
.mode-option.active { background: #fff; color: var(--el-color-primary); font-weight: 600; box-shadow: 0 1px 4px rgba(16, 60, 54, .14); }
.mode-option:disabled { cursor: not-allowed; opacity: .6; }
.mode-option .el-icon { font-size: 15px; }
.mode-hint { color: var(--el-text-color-secondary); font-size: 13px; }
.package-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; padding: 12px 14px; background: var(--el-color-primary-light-9); border: 1px solid var(--el-color-primary-light-7); border-radius: 10px; }
.package-head label { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; white-space: nowrap; }
.package-head label .el-icon { color: var(--el-color-primary); }
.package-person-input { max-width: 320px; }
.package-summary { display: flex; flex-wrap: wrap; gap: 6px; margin: 14px 0 10px; }
.upload-footer { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--el-border-color-lighter); }
@media (max-width: 760px) {
  .material-row { grid-template-columns: 56px minmax(0, 1fr); }
  .material-type { grid-column: 2; width: 100%; }
  .material-actions { grid-column: 2; justify-content: flex-start; }
}
/* 文件列表自动编号：一眼看出当前是第几个、共多少个。 */
.upload-card :deep(.el-upload-list) { counter-reset: upload-index; }
.upload-card :deep(.el-upload-list__item) { counter-increment: upload-index; }
.upload-card :deep(.el-upload-list__item-name)::before {
  content: counter(upload-index) '. ';
  font-weight: 600;
  color: var(--el-color-primary);
}
</style>
