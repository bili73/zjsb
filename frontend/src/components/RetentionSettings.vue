<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiFailure, isAbort } from '../api.ts'
import type { BusinessApi } from '../api.ts'
import { confirmRetentionSave, retentionLabel } from '../retention.ts'
import type { RetentionDays, RetentionSettings } from '../retention.ts'
import { errorMessages } from '../diagnostics.ts'
import { formatTime } from '../presentation.ts'

const props = defineProps<{ api: BusinessApi }>()
const emit = defineEmits<{ (e: 'saved'): void; (e: 'unauthorized'): void }>()
const settings = ref<RetentionSettings | null>(null), selected = ref<7 | 15 | 30 | 'never'>(7)
const loading = ref(false), saving = ref(false), error = ref('')
const controller = new AbortController()
function failed(value: unknown) {
  if (isAbort(value)) return
  if (value instanceof ApiFailure) {
    if (value.card.http_status === 401) emit('unauthorized')
    error.value = `${errorMessages[value.card.code]}（错误编号 ${value.card.error_id}）`
  } else error.value = '保存结果尚未确认，请重新读取设置。'
}
async function refresh() {
  loading.value = true; error.value = ''
  try { settings.value = await props.api.retention(controller.signal); selected.value = settings.value.days ?? 'never' }
  catch (value) { failed(value) } finally { loading.value = false }
}
async function save() {
  if (!settings.value || saving.value || loading.value) return
  saving.value = true; error.value = ''
  const days: RetentionDays = selected.value === 'never' ? null : selected.value
  try {
    const result = await confirmRetentionSave(settings.value, days,
      message => ElMessageBox.confirm(message, '确认文件保留设置', { type: 'warning', confirmButtonText: '确认保存', cancelButtonText: '取消' }),
      body => props.api.saveRetention(body, controller.signal))
    if (result) { settings.value = result; emit('saved'); ElMessage.success('文件保留设置已保存，对新旧文件统一生效。') }
  } catch (value) { failed(value) } finally { saving.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header><div class="retention-heading"><strong>文件保留设置</strong><el-button :disabled="saving || loading" @click="refresh">重新读取</el-button></div></template>
    <el-alert type="info" :closable="false">全平台统一生效，包含已有文件。每份文件从原上传时间计算；追加上传、重新识别和保存修改不会延长原有文件的期限。</el-alert>
    <el-alert v-if="error" type="error" :closable="false">{{ error }}</el-alert>
    <p v-if="settings">当前设置：<strong>{{ retentionLabel(settings.days) }}</strong>；影响数量统计于 {{ formatTime(settings.assessed_at) }}（UTC+8）。</p>
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="文件保留时长">
        <el-radio-group v-model="selected" :disabled="saving || loading || !settings">
          <el-radio :value="7">7天</el-radio><el-radio :value="15">15天</el-radio><el-radio :value="30">30天</el-radio><el-radio value="never">永不清除</el-radio>
        </el-radio-group>
      </el-form-item>
      <p>到期清理包含原件、识别结果和修改历史；正在处理的文件延后清理。永不清除时仍可手动删除。已清理的数据不能通过延长期限恢复。</p>
      <el-button type="primary" native-type="submit" :disabled="!settings || loading" :loading="saving">保存设置</el-button>
    </el-form>
  </el-card>
</template>

<style scoped>
.retention-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.el-alert { margin-bottom: 16px; }
</style>
