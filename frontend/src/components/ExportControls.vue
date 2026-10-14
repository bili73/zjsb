<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { BusinessApi } from '../api.ts'
import { ApiFailure, isAbort } from '../api.ts'
import type { Batch, Task } from '../business.ts'
import { isPersonPackage } from '../business.ts'
import { downloadBlob, exportBlockReason, spreadsheetName } from '../review.ts'
import { errorMessages } from '../diagnostics.ts'
const props = defineProps<{ api: BusinessApi | null; tasks: Task[]; selected: Task[]; batchId: string; batch?: Batch; canWrite: boolean }>()
const emit=defineEmits<{(e:'unauthorized'):void}>()
const mode=ref<'batch'|'selection'>('batch'), busy=ref(false), message=ref('')
const targets=computed(()=>mode.value==='batch'?props.tasks:props.selected)
const blocked=computed(()=>props.canWrite ? exportBlockReason(targets.value) : '当前只读账号无 Excel 导出权限。')
let controller: AbortController | undefined
onBeforeUnmount(() => controller?.abort())
async function run(){
  if(!props.api || blocked.value || busy.value) return
  const filename = spreadsheetName(targets.value.map(task => task.doc_type), new Date(), !!props.batch && isPersonPackage(props.batch))
  busy.value=true;message.value='';controller=new AbortController()
  try{
    const blob=await props.api.export({...(mode.value==='batch'?{batch_id:props.batchId}:{task_ids:targets.value.map(t=>t.task_id)}),masked:false,versions:targets.value.map(t=>({task_id:t.task_id,run_id:t.run_id,result_revision:t.result_revision}))},controller.signal)
    if(controller.signal.aborted) return
    downloadBlob(blob, targets.value.every(t => t.doc_type === 'TABLE') ? blob.downloadName ?? (targets.value.length > 1 ? '表格.zip' : '表格.xlsx') : filename)
  }catch(error){if(isAbort(error)) return;if(error instanceof ApiFailure){message.value=`${errorMessages[error.card.code]}（错误编号 ${error.card.error_id}）`;if(error.card.http_status===401)emit('unauthorized')}else message.value='导出未完成，请重新检查任务状态。'}finally{busy.value=false}
}
</script>
<template><div class="export-controls"><el-radio-group v-model="mode"><el-radio value="batch">本批次全部</el-radio><el-radio value="selection">已勾选 {{ selected.length }} 项</el-radio></el-radio-group><el-button type="primary" :loading="busy" :disabled="!!blocked" @click="run">下载 Excel</el-button><span v-if="batch && isPersonPackage(batch)" class="conf">首张人员信息总表包含全部字段，附分类明细；姓名未确认不影响导出。</span><span v-if="blocked" class="conf">{{ blocked }}</span><el-alert v-if="message" type="warning" :closable="false">{{ message }}</el-alert></div></template>
<style scoped>.export-controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center;padding:12px 16px}.export-controls .el-input{max-width:360px}</style>
