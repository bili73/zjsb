<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiFailure, isAbort } from '../api.ts'
import type { BusinessApi } from '../api.ts'
import type { Task } from '../business.ts'
import type { Monitor } from '../monitor.ts'
import { errorMessages } from '../diagnostics.ts'
import BankCropDialog from './BankCropDialog.vue'

const props = defineProps<{ task: Task; api: BusinessApi; monitor: Monitor; disabled: boolean }>()
const emit = defineEmits<{ (e: 'submitted'): void; (e: 'preview', files: File[], tasks: Task[]): void; (e: 'unauthorized'): void }>()
const open = ref(false), busy = ref(false), source = ref<File[]>([]), crop = ref<File | null>(null), error = ref('')
let controller: AbortController | undefined
onBeforeUnmount(() => controller?.abort())

function showError(caught: unknown, uploading: boolean) {
  if (isAbort(caught)) return
  if (caught instanceof ApiFailure && caught.card.http_status === 401) { emit('unauthorized'); return }
  const message = caught instanceof ApiFailure ? errorMessages[caught.card.code] : '请求未完成'
  error.value = uploading ? `${message}。裁图已保留，请先查看任务列表确认是否已接收，再重试上传。` : `${message}，可重试读取原图或在下方手工填写卡号。`
}
async function startCrop() {
  if (busy.value || props.disabled) return
  busy.value = true; error.value = ''; controller = new AbortController()
  try {
    const page = await props.api.preview(props.task, 1, controller.signal)
    if (controller.signal.aborted) return
    if (!page.corrected) throw new Error('STALE_PREVIEW')
    source.value = [new File([page.blob], props.task.file_name || '银行卡.png', { type: page.blob.type })]
    open.value = true
  } catch (caught) { showError(caught, false) }
  finally { busy.value = false }
}
async function uploadCrop() {
  const file = crop.value
  if (!file || busy.value || props.disabled) return
  busy.value = true; error.value = ''; controller = new AbortController()
  try {
    const created = await props.monitor.submitUpload([file], 'BANK_CARD', false, controller.signal)
    if (controller.signal.aborted) return
    try { emit('preview', [file], await props.api.tasks(created.batch_id, controller.signal)) }
    catch { /* Accepted upload remains successful even if local preview binding fails. */ }
    crop.value = null
    ElMessage.success('这张裁图已提交识别，原任务和其他卡片已保留。')
    emit('submitted')
  } catch (caught) { showError(caught, true) }
  finally { busy.value = false }
}
function confirmed(files: File[]) { open.value = false; crop.value = files[0] ?? null; void uploadCrop() }
</script>
<template>
  <el-alert class="bank-recovery" type="warning" :closable="false" show-icon>
    <p>这张图片的卡号未可靠读出。可只裁剪这张重新识别，或在下方手工填写；其他卡片不受影响。</p>
    <el-button :disabled="disabled || busy" :loading="busy" @click="startCrop">裁剪这张重新识别</el-button>
    <el-button v-if="crop" type="primary" :disabled="disabled || busy" @click="uploadCrop">重试上传已保存裁图</el-button>
    <p v-if="disabled">请先保存下方的字段修正。</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </el-alert>
  <BankCropDialog :open="open" :files="source" @done="confirmed" @cancel="open = false" />
</template>
<style scoped>.bank-recovery{margin-bottom:12px}.bank-recovery p{margin:6px 0}</style>
