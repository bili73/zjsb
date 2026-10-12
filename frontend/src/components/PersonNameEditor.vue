<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { Batch } from '../business.ts'
import { docTypes } from '../business.ts'
import type { Monitor } from '../monitor.ts'
import { ApiFailure, isAbort } from '../api.ts'
import { errorMessages } from '../diagnostics.ts'
const props = defineProps<{ batch: Batch; monitor: Monitor; canWrite: boolean }>()
const emit = defineEmits<{ (e: 'unauthorized'): void }>()
const editing = ref(false), name = ref(''), busy = ref(false), message = ref('')
const suggestions = computed(() => props.batch.name_suggestions ?? [])
let controller: AbortController | undefined
onBeforeUnmount(() => controller?.abort())
function edit(value = props.batch.person_name ?? '') { name.value = value; editing.value = true; message.value = '' }
async function save() {
  if (!name.value.trim() || busy.value || !props.canWrite) return
  busy.value = true; message.value = ''; controller = new AbortController()
  try {
    await props.monitor.confirmPerson(props.batch, name.value.trim(), controller.signal)
    if (controller.signal.aborted) return
    editing.value = false; ElMessage.success('人员姓名已保存。')
  } catch (error) {
    if (isAbort(error)) return
    if (error instanceof ApiFailure) {
      message.value = error.card.http_status === 409 ? '材料包已更新，请刷新后重新核对姓名。' : errorMessages[error.card.code]
      if (error.card.http_status === 401) emit('unauthorized')
      if (error.card.http_status === 409) props.monitor.start()
    } else message.value = '姓名保存失败，请重试。'
  } finally { busy.value = false }
}
</script>
<template>
  <div class="person-name-editor">
    <div class="name-row"><strong>材料归属：{{ batch.person_name || '姓名待确认' }}</strong>
      <el-button v-if="canWrite && !editing" size="small" @click="edit()">{{ batch.person_name ? '修改姓名' : '填写 / 确认姓名' }}</el-button>
    </div>
    <div v-if="editing" class="name-row">
      <el-input v-model="name" aria-label="人员姓名" maxlength="80" :disabled="busy" placeholder="核对原件后填写姓名" />
      <el-button type="primary" size="small" :loading="busy" :disabled="!name.trim()" @click="save">保存姓名</el-button>
      <el-button size="small" :disabled="busy" @click="editing = false">取消</el-button>
    </div>
    <div v-for="candidate in suggestions" :key="candidate.name" class="candidate">
      <el-button v-if="canWrite" size="small" :disabled="busy" @click="edit(candidate.name)">使用建议：{{ candidate.name }}</el-button>
      <span v-else>建议：{{ candidate.name }}</span>
      <span class="source">{{ candidate.sources.map(s => `${docTypes[s.doc_type]} / ${s.file_name}`).join('；') }}</span>
    </div>
    <span class="source">{{ suggestions.length ? '姓名建议来自已保存的识别字段，不能证明材料属于同一人；请核对后保存。' : '尚无可用姓名；识别后会提供建议，也可手工填写。' }}</span>
    <el-alert v-for="warning in batch.warnings?.filter(w => w.code === 'PERSON_NAME_CONFLICT')" :key="warning.code" type="warning" :closable="false">{{ warning.message }}</el-alert>
    <el-alert v-if="message" type="warning" :closable="false">{{ message }}</el-alert>
  </div>
</template>
<style scoped>
.person-name-editor{padding:12px 16px;display:grid;gap:8px}.name-row,.candidate{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.name-row .el-input{max-width:280px}.source{font-size:12px;color:var(--el-text-color-secondary);overflow-wrap:anywhere}
</style>
