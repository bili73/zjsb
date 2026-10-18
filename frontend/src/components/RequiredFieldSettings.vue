<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiFailure, isAbort } from '../api.ts'
import type { BusinessApi } from '../api.ts'
import { selectedRequiredFields } from '../requiredFields.ts'
import type { RequiredFieldSettings } from '../requiredFields.ts'
import { errorMessages } from '../diagnostics.ts'

const props = defineProps<{ api: BusinessApi }>()
const emit = defineEmits<{ (e: 'saved'): void; (e: 'unauthorized'): void }>()
const settings = ref<RequiredFieldSettings | null>(null), kind = ref('DIPLOMA'), selected = ref<string[]>([])
const loading = ref(false), saving = ref(false), error = ref('')
const profile = computed(() => settings.value?.items.find(item => item.doc_type === kind.value))
const editable = computed(() => profile.value?.fields.filter(field => field.editable) ?? [])
const dirty = computed(() => JSON.stringify(selected.value.slice().sort()) !== JSON.stringify(profile.value ? selectedRequiredFields(profile.value).sort() : []))
let controller: AbortController | undefined
function resetSelection() { selected.value = profile.value ? selectedRequiredFields(profile.value) : [] }
function failed(value: unknown) {
  if (isAbort(value)) return
  if (value instanceof ApiFailure) {
    if (value.card.http_status === 401) emit('unauthorized')
    error.value = `${errorMessages[value.card.code]}（错误编号 ${value.card.error_id}）`
  } else error.value = '设置未确认，请重新读取后再试。'
}
async function discardChanges() {
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('当前选择尚未保存，是否放弃这些修改？', '未保存设置'); return true } catch { return false }
}
async function refresh() {
  if (!(await discardChanges())) return
  controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''
  try { settings.value = await props.api.requiredFields(controller.signal); resetSelection() }
  catch (value) { failed(value) } finally { loading.value = false }
}
async function changeType(value: string) { if (await discardChanges()) { kind.value = value; resetSelection(); error.value = '' } }
async function save(useDefaults = false) {
  if (!settings.value || saving.value) return
  if (useDefaults) { try { await ElMessageBox.confirm('恢复该材料类型的默认必填规则，并应用于所有批次？', '恢复默认') } catch { return } }
  controller?.abort(); controller = new AbortController(); saving.value = true; error.value = ''
  try {
    settings.value = await props.api.saveRequiredFields({ doc_type: kind.value, required_fields: useDefaults ? null : selected.value, expected_revision: settings.value.revision }, controller.signal)
    resetSelection(); emit('saved'); ElMessage.success('必填设置已保存，所有批次按新规则检查。')
  } catch (value) { failed(value) } finally { saving.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header><div class="settings-heading"><strong>必填字段设置</strong><el-tooltip content="放弃本地修改，从服务器重新加载" placement="top"><span><el-button :disabled="saving" @click="refresh">重新读取</el-button></span></el-tooltip></div></template>
    <el-alert type="info" :closable="false">必填设置按材料类型对所有批次生效（含已识别的历史任务），只影响核对标记和导出条件，不会修改识别内容。自定义：勾选的字段必填，未勾选的选填。恢复默认：回到系统内置的默认规则（含条件必填）。</el-alert>
    <el-alert v-if="error" type="error" :closable="false">{{ error }}</el-alert>
    <el-form label-position="top" @submit.prevent="save()">
      <el-form-item label="材料类型" data-guide="required-type"><el-select :model-value="kind" :disabled="saving || loading" aria-label="设置材料类型" @update:model-value="changeType"><el-option v-for="item in settings?.items ?? []" :key="item.doc_type" :label="item.label" :value="item.doc_type" /></el-select></el-form-item>
      <template v-if="profile">
        <p><el-tag :type="profile.uses_defaults ? 'info' : 'warning'">{{ profile.uses_defaults ? '使用默认规则' : '使用自定义规则' }}</el-tag> 已选 {{ selected.length }} 项必填</p>
        <el-checkbox-group v-model="selected" :disabled="saving" class="field-options" data-guide="required-fields"><el-checkbox v-for="field in profile.fields" :key="field.key" :value="field.key" :disabled="!field.editable">{{ field.label }}{{ field.editable ? '' : '（自动计算，不可设为必填）' }}</el-checkbox></el-checkbox-group>
        <el-alert v-if="!selected.length" type="warning" :closable="false">未选择任何必填项：保存后，该类型的空白业务字段不会阻止导出；仍需有已保存的识别结果。</el-alert>
        <div class="settings-actions">
          <el-tooltip content="勾选全部可编辑字段为必填" placement="top"><span><el-button :disabled="saving" @click="selected = editable.map(field => field.key)">全选可填写项</el-button></span></el-tooltip>
          <el-tooltip content="取消全部勾选；保存后该类型所有业务字段都为选填" placement="top"><span><el-button :disabled="saving" @click="selected = []">清空选择</el-button></span></el-tooltip>
          <el-button type="primary" data-guide="required-save" native-type="submit" :loading="saving">保存设置</el-button>
          <el-tooltip content="保存服务器内置的默认规则，覆盖当前自定义" placement="top"><span><el-button :disabled="saving" @click="save(true)">恢复默认</el-button></span></el-tooltip>
        </div>
      </template>
    </el-form>
  </el-card>
</template>

<style scoped>
.settings-heading, .settings-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.settings-heading { justify-content: space-between; }
.field-options { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 20px 0; }
.el-alert { margin-bottom: 16px; }
</style>
