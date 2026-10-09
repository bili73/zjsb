<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { CopyDocument, Download } from '@element-plus/icons-vue'
import { diagnosticCards, errorMessages } from '../diagnostics.ts'
import type { DiagnosticCard } from '../diagnostics.ts'
import { formatTime } from '../presentation.ts'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()

const originLabels = { http: '接口请求', task: '任务', vue: '界面', window: '窗口', promise: '异步' } as const
const operationLabels = {
  health: '健康检查', auth: '身份验证', account_list: '账号列表', account_create: '创建账号', batch_list: '批次列表', batch_tasks: '批次任务',
  upload: '上传', result: '结果读取', cancel: '取消', rerun: '重跑', interface: '界面', catalogue: '材料目录', review: '人工复核', preview: '受控预览', export: '导出',
} as const

async function copy(card: DiagnosticCard) {
  try {
    await navigator.clipboard.writeText(JSON.stringify(card, null, 2))
    ElMessage.success('诊断信息已复制。')
  } catch {
    ElMessage.error('复制失败，请改用下载按钮。')
  }
}

function download(card: DiagnosticCard) {
  const blob = new Blob([JSON.stringify(card, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `diagnostic-${card.error_id}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <el-drawer
    :model-value="open"
    title="诊断信息"
    size="440px"
    append-to-body
    @update:model-value="value => emit('update:open', value)"
  >
    <el-alert type="info" :closable="false" show-icon class="diag-note">
      诊断信息只包含错误码、编号与位置，不含密码等凭证、文件名、接口地址与识别内容。
    </el-alert>
    <el-empty v-if="diagnosticCards.length === 0" description="近期没有记录到诊断信息。" />
    <el-card v-for="card in diagnosticCards" :key="card.error_id" shadow="never" class="diag-card">
      <div class="diag-head">
        <el-tag size="small" type="danger" effect="plain">{{ card.code }}</el-tag>
        <span class="diag-time">{{ formatTime(card.occurred_at) }}</span>
      </div>
      <p class="diag-line">{{ errorMessages[card.code] }}</p>
      <el-descriptions :column="1" size="small" border class="diag-detail">
        <el-descriptions-item label="来源">{{ originLabels[card.origin] }} · {{ operationLabels[card.operation] }}</el-descriptions-item>
        <el-descriptions-item v-if="card.http_status !== null" label="HTTP 状态">{{ card.http_status }}</el-descriptions-item>
        <el-descriptions-item v-if="card.stage" label="任务阶段">{{ card.stage }}</el-descriptions-item>
        <el-descriptions-item label="错误编号">{{ card.error_id }}</el-descriptions-item>
        <el-descriptions-item v-if="card.request_id" label="请求编号">{{ card.request_id }}</el-descriptions-item>
        <el-descriptions-item v-if="card.exception_type" label="异常类型">{{ card.exception_type }}</el-descriptions-item>
        <el-descriptions-item label="前端版本">{{ card.app_version }}</el-descriptions-item>
      </el-descriptions>
      <div class="diag-actions">
        <el-button size="small" :icon="CopyDocument" @click="copy(card)">复制</el-button>
        <el-button size="small" :icon="Download" @click="download(card)">下载 JSON</el-button>
      </div>
    </el-card>
  </el-drawer>
</template>

<style scoped>
.diag-note { margin-bottom: 12px; }
.diag-card { border-radius: 10px; margin-bottom: 12px; }
.diag-head { display: flex; align-items: center; justify-content: space-between; }
.diag-time { font-size: 12px; color: var(--el-text-color-secondary); }
.diag-line { margin: 8px 0; font-size: 13px; }
.diag-detail { margin-bottom: 10px; }
.diag-actions { display: flex; gap: 8px; }
</style>
