<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Component } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadUserFile } from 'element-plus'
import { CreditCard, Files, FirstAidKit, Medal, Notebook, OfficeBuilding, Postcard, Reading, Stamp, UploadFilled } from '@element-plus/icons-vue'
import { ApiFailure, isAbort } from '../api.ts'
import { docTypes, uploadLimits, validateUpload } from '../business.ts'
import type { BusinessApi } from '../api.ts'
import type { DocProfile, Task, UploadDocType } from '../business.ts'
import { errorMessages } from '../diagnostics.ts'
import type { Monitor } from '../monitor.ts'

const props = defineProps<{ monitor: Monitor; canWrite: boolean; api: BusinessApi | null; catalogue: DocProfile[] }>()
const emit = defineEmits<{
  (e: 'submitted'): void
  (e: 'preview', files: File[], tasks: Task[]): void
  (e: 'unauthorized'): void
}>()

const docType = ref<UploadDocType>('MEDICAL_REPORT')
const abnormalOnly = ref(false)
const fileList = ref<UploadUserFile[]>([])
const submitting = ref(false)
let submitController: AbortController | undefined

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

function onExceed() { ElMessage.warning(`一次最多提交 ${uploadLimits.maxFiles} 个文件。`) }

// 一个批次只携带一个 doc_type_hint：带着未提交的文件切换类型，会把两种
// 材料合成一批并按单一类型处理（正是实测中体检文件被按毕业证处理的根因），
// 因此切换前确认并清空未提交文件。
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
  const files = selectedFiles.value
  const problem = validateUpload(files)
  if (problem) { ElMessage.warning(problem); return }
  if (!props.canWrite) { ElMessage.warning('当前账号为只读角色，无法上传文件。'); return }
  if (!props.catalogue.some(p => p.doc_type === docType.value)) { ElMessage.warning('请等待材料目录加载。'); return }
  if (docType.value === 'BANK_CARD') {
    if (files.some(f => !/\.(?:jpe?g|png|heic)$/i.test(f.name))) { ElMessage.warning('银行卡请上传单张 JPG/PNG/HEIC 照片，不接收 PDF。'); return }
  }
  await uploadFiles(files)
}
async function uploadFiles(files: File[]) {
  const problem=validateUpload(files); if(problem){ElMessage.warning(problem);return}
  submitController = new AbortController()
  submitting.value = true
  try {
    const created = await props.monitor.submitUpload(files, docType.value, abnormalOnly.value, submitController.signal)
    if (props.api) { try { const tasks = await props.api.tasks(created.batch_id, submitController.signal); emit('preview', files, tasks) } catch { /* Accepted uploads must not be reported as failed when preview binding fails. */ } }
    emit('submitted')
    fileList.value = []
    ElMessage.success(`已提交 ${created.task_ids.length} 个识别任务，可切换证件类型继续上传。`)
  } catch (error) {
    if (isAbort(error)) { props.monitor.start(); ElMessage.info('已停止等待上传响应；服务端可能已接收，请先查看任务列表。') }
    else if (error instanceof ApiFailure) {
      if (error.card.http_status === 401) emit('unauthorized')
      else ElMessage.error(errorMessages[error.card.code])
    } else ElMessage.error(errorMessages.UNKNOWN_ERROR)
  } finally {
    submitting.value = false
    submitController = undefined
  }
}
</script>

<template>
  <section class="upload-panel">
    <el-alert type="info" :closable="false" show-icon class="upload-tip">
      一个批次只按一种证件类型处理；提交后即可切换类型继续上传，已有任务在后台持续执行、不会丢失。可选类型来自当前服务目录。
    </el-alert>

    <div class="type-cards">
      <button
        v-for="profile in catalogue"
        :key="profile.doc_type"
        type="button"
        class="type-card"
        :class="{ active: docType === profile.doc_type }"
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
      <el-upload
        v-model:file-list="fileList"
        drag
        multiple
        action="#"
        :auto-upload="false"
        accept=".pdf,.jpg,.jpeg,.png,.heic"
        :limit="uploadLimits.maxFiles"
        :on-exceed="onExceed"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">将 {{ docTypes[docType] }}文件拖到此处，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">支持 JPG / PNG / HEIC / PDF，单文件 ≤ {{ uploadLimits.maxFileMB }} MB，每批 1–{{ uploadLimits.maxFiles }} 个文件、总计 ≤ {{ uploadLimits.maxBatchMB }} MB。</div>
        </template>
      </el-upload>

      <el-alert v-if="invalidReason" type="warning" :closable="false" show-icon class="upload-invalid">{{ invalidReason }}</el-alert>

      <div v-if="docType === 'MEDICAL_REPORT'" class="upload-row">
        <el-switch v-model="abnormalOnly" active-text="仅整理异常与待判定项" />
        <span class="upload-hint">仅改变默认结果展示范围；复核和导出仍按完整结果检查，不承诺加速。</span>
      </div>

      <div class="upload-row">
        <span class="upload-hint" :class="{ 'at-limit': selectedFiles.length >= uploadLimits.maxFiles }">已选择 {{ selectedFiles.length }} / {{ uploadLimits.maxFiles }} 个文件</span>
        <div class="upload-actions">
          <el-button v-if="selectedFiles.length && !submitting" @click="clearFiles">一键清除</el-button>
          <el-button v-if="submitting" @click="cancelSubmit">取消上传</el-button>
          <el-button type="primary" :loading="submitting" :disabled="!canWrite || !catalogue.length" @click="submit">
            {{ submitting ? '正在上传…' : `开始识别（${selectedFiles.length || ''}）` }}
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
/* 文件列表自动编号：一眼看出当前是第几个、共多少个。 */
.upload-card :deep(.el-upload-list) { counter-reset: upload-index; }
.upload-card :deep(.el-upload-list__item) { counter-increment: upload-index; }
.upload-card :deep(.el-upload-list__item-name)::before {
  content: counter(upload-index) '. ';
  font-weight: 600;
  color: var(--el-color-primary);
}
</style>
