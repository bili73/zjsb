<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { Download, WarningFilled } from '@element-plus/icons-vue'
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
  }catch(error){if(isAbort(error)) return;if(error instanceof ApiFailure){message.value=errorMessages[error.card.code];if(error.retryAfterSeconds!==undefined)message.value+=`可在 ${error.retryAfterSeconds} 秒后重试。`;else message.value+=`（错误编号 ${error.card.error_id}）`;if(error.card.http_status===401)emit('unauthorized')}else message.value='导出未完成，请重新检查任务状态。'}finally{busy.value=false}
}
</script>
<template><div class="export-controls"><span class="export-actions" data-guide="batch-export"><el-radio-group v-model="mode"><el-radio value="batch">本批次全部</el-radio><el-radio value="selection">已勾选 {{ selected.length }} 项</el-radio></el-radio-group><!-- 导出被阻止时按钮置灰，阻断原因改为悬停提示：warning 底色＋感叹号（样式见 style.css .export-tip），与详情页导出、删除批次的「禁用＋悬停原因」模式一致。 --><el-tooltip placement="top" effect="light" popper-class="export-tip-popper" :disabled="!blocked"><template #content><span class="export-tip"><el-icon><WarningFilled /></el-icon>{{ blocked }}</span></template><span><el-button type="primary" plain :icon="Download" :loading="busy" :disabled="!!blocked" @click="run">{{ busy ? '正在准备…' : '下载 Excel' }}</el-button></span></el-tooltip></span><span v-if="busy" class="conf">服务器繁忙时会短暂排队，请勿重复导出。</span><span v-if="batch && isPersonPackage(batch)" class="conf">首张人员信息总表包含全部字段，附分类明细；姓名未确认不影响导出。</span><el-alert v-if="message" type="warning" :closable="false">{{ message }}</el-alert></div></template>
<style scoped>.export-controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.export-controls .el-input{max-width:360px}.export-actions{display:inline-flex;align-items:center;gap:12px;flex-wrap:wrap}</style>
