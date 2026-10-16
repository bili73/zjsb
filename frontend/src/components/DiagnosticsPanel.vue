<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { copyText } from '../browserCapabilities.ts'
import { ElMessage } from 'element-plus'
import { CopyDocument, Download } from '@element-plus/icons-vue'
import { diagnosticCards, errorMessages } from '../diagnostics.ts'
import type { DiagnosticCard } from '../diagnostics.ts'
import { formatTime } from '../presentation.ts'
import type { BusinessApi } from '../api.ts'
import type { LogStatus } from '../serverDiagnostics.ts'
import ServerDiagnostics from './ServerDiagnostics.vue'

const props = defineProps<{ open: boolean; api?: BusinessApi | null; isAdmin?: boolean; status?: LogStatus | null; statusError?: string }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void; (e: 'unauthorized'): void; (e: 'refresh-status'): void }>()
let generation = 0
watch(() => [props.open, props.api], () => { generation++ }, { flush: 'sync' })
onBeforeUnmount(() => { generation++ })

const originLabels = { http: '接口请求', task: '任务', vue: '界面', window: '窗口', promise: '异步' } as const
const operationLabels = {
  diagnostics: '运行诊断',
  health: '健康检查', auth: '身份验证', account_list: '账号列表', account_create: '创建账号', account_update: '账号启用状态', account_delete: '删除账号', password_change: '修改密码', retention_read: '读取保留设置', retention_save: '保存保留设置', required_settings_read: '读取必填设置', required_settings_save: '保存必填设置', workbench_layout_read: '读取个人布局', workbench_layout_save: '保存个人布局', workbench_default_save: '保存默认布局', batch_list: '批次列表', batch_tasks: '批次任务',
  batch_delete: '删除批次', person_update: '确认人员姓名', upload: '上传', classify: '材料分类', region_ocr: '框选识别', result: '结果读取', cancel: '取消', rerun: '重跑', interface: '界面', catalogue: '材料目录', review: '人工复核', preview: '受控预览', export: '导出',
} as const

async function copy(card: DiagnosticCard) {
  const revision = generation
  const current = () => props.open && revision === generation && diagnosticCards.value.some(item => item.error_id === card.error_id)
  try {
    await copyText(JSON.stringify(card, null, 2), current)
    if (current()) ElMessage.success('诊断信息已复制。')
  } catch {
    if (current()) ElMessage.error('复制失败，请改用下载按钮。')
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
    :size="isAdmin ? 'min(1100px, 96vw)' : 'min(440px, 96vw)'"
    append-to-body
    @update:model-value="value => emit('update:open', value)"
  >
    <el-alert type="info" :closable="false" show-icon class="diag-note">
      诊断信息只包含错误码、编号与位置，不含密码等凭证、文件名、接口地址与识别内容。
    </el-alert>
    <ServerDiagnostics v-if="isAdmin && api" :api="api" :open="open" :status="status ?? null" :status-error="statusError ?? ''" @unauthorized="emit('unauthorized')" @refresh-status="emit('refresh-status')" />
    <h3>本页错误信息</h3>
    <p class="diag-local-note">以下最多保留本页20条。登录后的界面和连接异常会尝试上报；连接中断时请复制或下载后交给维护人员。刷新或退出后，本页列表会清空。</p>
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
        <el-descriptions-item label="服务版本">{{ card.app_version }}</el-descriptions-item>
        <el-descriptions-item v-if="card.frontend_build" label="前端构建">{{ card.frontend_build }}</el-descriptions-item>
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
.diag-local-note { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.7; }
.diag-card { border-radius: 10px; margin-bottom: 12px; }
.diag-head { display: flex; align-items: center; justify-content: space-between; }
.diag-time { font-size: 12px; color: var(--el-text-color-secondary); }
.diag-line { margin: 8px 0; font-size: 13px; }
.diag-detail { margin-bottom: 10px; }
.diag-actions { display: flex; gap: 8px; }
</style>
