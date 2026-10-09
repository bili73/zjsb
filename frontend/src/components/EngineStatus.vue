<script setup lang="ts">
import { computed } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { modelDescriptions, modelLabels, modeLabels, reasonDescriptions } from '../health.ts'
import type { ModelState } from '../health.ts'
import type { Engine } from '../engine.ts'
import { formatTime } from '../presentation.ts'

const props = defineProps<{ engine: Engine }>()

const state = computed(() => props.engine.state)
const health = computed(() => state.value.health)
const runtime = computed(() => health.value?.runtime)

const modelTagTypes: Record<ModelState, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  unloaded: 'info', loading: 'primary', warming: 'primary', ready: 'success', failed: 'danger', stopping: 'warning',
}
const runtimeTagTypes = { starting: 'primary', ready: 'success', degraded: 'warning', stopping: 'warning' } as const
const componentTag = (value: 'ok' | 'down') => (value === 'ok' ? 'success' : 'danger')

const models: { key: 'glm_ocr' | 'paddleocr_vl'; name: string; role: string }[] = [
  { key: 'glm_ocr', name: 'GLM-OCR', role: '报告与证件语义理解' },
  { key: 'paddleocr_vl', name: 'PaddleOCR-VL', role: '版面与文字识别' },
]
</script>

<template>
  <section class="engine-status">
    <el-card shadow="never" class="status-card">
      <div class="status-head">
        <el-tag :type="engine.summary.value.tone" size="large" effect="light">{{ engine.summary.value.label }}</el-tag>
        <span v-if="state.auto" class="conf">启动/停止过程中 · 每秒自动刷新</span>
        <span class="conf">上次检查 {{ formatTime(state.lastCheckedAt) }}</span>
        <div class="head-spacer" />
        <el-button type="primary" :icon="Refresh" :loading="state.refreshing" @click="engine.refresh()">立即刷新</el-button>
      </div>
    </el-card>

    <el-result
      v-if="state.connection === 'disconnected'"
      icon="warning"
      title="本地服务未连接"
      sub-title="请确认启动器仍在运行；网络恢复或窗口重新获得焦点时会自动重试。"
    />
    <el-result
      v-else-if="state.connection === 'invalid'"
      icon="error"
      title="健康检查响应无法解析"
      sub-title="服务可能正在升级或异常，请查看诊断信息或联系维护人员。"
    />

    <template v-else-if="health">
      <el-card shadow="never" class="status-card">
        <template #header>服务组件</template>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="数据库">
            <el-tag :type="componentTag(health.components.db)" effect="plain">{{ health.components.db === 'ok' ? '正常' : '不可用' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="处理进程">
            <el-tag :type="componentTag(health.components.worker)" effect="plain">{{ health.components.worker === 'ok' ? '正常' : '不可用' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="存储">
            <el-tag :type="componentTag(health.components.storage)" effect="plain">{{ health.components.storage === 'ok' ? '正常' : '不可用' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="整体状态">
            <el-tag :type="health.status === 'ok' ? 'success' : 'warning'" effect="plain">{{ health.status === 'ok' ? '正常' : '降级' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="排队任务">{{ health.queue_depth ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="服务版本">{{ health.version }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card v-if="runtime" shadow="never" class="status-card">
        <template #header>识别引擎</template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="运行状态">
            <el-tag :type="runtimeTagTypes[runtime.state]" effect="plain">
              {{ { starting: '启动中', ready: '就绪', degraded: '能力受限', stopping: '停止中' }[runtime.state] }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="驻留模式">
            {{ modeLabels[runtime.configured_mode] }}
            <el-tag
              v-if="runtime.effective_mode && runtime.effective_mode !== runtime.configured_mode"
              size="small"
              :type="runtime.effective_mode === 'ocr_unavailable' ? 'danger' : 'warning'"
              effect="plain"
            >实际：{{ modeLabels[runtime.effective_mode] }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <el-alert v-if="runtime.reason_code" class="reason-alert" type="warning" :closable="false" show-icon>
          {{ reasonDescriptions[runtime.reason_code] }}
        </el-alert>

        <div class="model-grid">
          <div v-for="model in models" :key="model.key" class="model-card">
            <div class="model-head">
              <span class="model-name">{{ model.name }}</span>
              <el-tag size="small" :type="modelTagTypes[runtime.models[model.key]]" effect="light">
                {{ modelLabels[runtime.models[model.key]] }}
              </el-tag>
            </div>
            <p class="model-role">{{ model.role }}</p>
            <p class="conf">{{ modelDescriptions[runtime.models[model.key]] }}</p>
          </div>
        </div>
      </el-card>

      <el-card v-else shadow="never" class="status-card">
        <template #header>识别引擎</template>
        <el-empty description="当前服务版本未提供引擎运行详情。" :image-size="80" />
      </el-card>
    </template>
  </section>
</template>

<style scoped>
.status-card { border-radius: 10px; margin-bottom: 16px; }
.status-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.head-spacer { flex: 1; }
.reason-alert { margin: 12px 0; }
.model-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.model-card { border: 1px solid var(--el-border-color-lighter); border-radius: 10px; padding: 14px 16px; }
.model-head { display: flex; align-items: center; justify-content: space-between; }
.model-name { font-weight: 600; }
.model-role { margin: 6px 0 4px; font-size: 13px; }
.model-card .conf { margin: 0; }
@media (max-width: 768px) { .model-grid { grid-template-columns: 1fr; } }
</style>
