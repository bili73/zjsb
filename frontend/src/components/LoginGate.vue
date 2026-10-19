<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiFailure, BusinessApi } from '../api.ts'
import { errorMessages } from '../diagnostics.ts'
import type { ErrorCode } from '../diagnostics.ts'
import logoUrl from '../assets/joybos-logo.png'
import type { Engine } from '../engine.ts'
import type { User } from '../business.ts'

// 登录表单专用文案：401 对未知账号与已停用账号返回同一错误（防枚举），文案保持中性；
// 403 是同源来源校验拒绝，刷新无效，需从允许的地址打开；限流与未配置账号沿用全局文案。
const loginMessages: Partial<Record<ErrorCode, string>> = {
  UNAUTHORIZED: '账号或密码不正确。',
  FORBIDDEN: '当前页面地址不被服务允许，请从允许的访问地址打开后再登录。',
}

const props = defineProps<{ engine: Engine }>()
const emit = defineEmits<{
  (e: 'authenticated', client: BusinessApi, user: User): void
  (e: 'diagnostics'): void
}>()

const username = ref('')
const password = ref('')
const verifying = ref(false)
const gateError = ref<string | null>(null)
const retryUntil = ref(0)
const clockNow = ref(Date.now())
const retrySeconds = computed(() => Math.max(0, Math.ceil((retryUntil.value - clockNow.value) / 1000)))
let retryTimer: ReturnType<typeof setInterval> | undefined
let controller: AbortController | undefined
onUnmounted(() => { controller?.abort(); clearInterval(retryTimer) })

function waitToRetry(seconds: number) {
  clearInterval(retryTimer)
  clockNow.value = Date.now()
  retryUntil.value = clockNow.value + seconds * 1000
  retryTimer = setInterval(() => {
    clockNow.value = Date.now()
    if (retrySeconds.value === 0) clearInterval(retryTimer)
  }, 1000)
}

async function verify() {
  if (verifying.value || retrySeconds.value > 0) return
  if (!username.value.trim() || !password.value) { gateError.value = '请输入账号和密码。'; return }
  controller?.abort()
  controller = new AbortController()
  verifying.value = true
  gateError.value = null
  const client = new BusinessApi()
  try {
    const user = await client.login(username.value.trim(), password.value, controller.signal)
    emit('authenticated', client, user)
  } catch (error) {
    if (error instanceof ApiFailure) {
      if (error.card.http_status === 429 && error.retryAfterSeconds) waitToRetry(error.retryAfterSeconds)
      const suffix = error.card.error_id ? `（错误编号 ${error.card.error_id}）` : ''
      gateError.value = `${loginMessages[error.card.code] ?? errorMessages[error.card.code]}${suffix}`
    } else {
      gateError.value = errorMessages.UNKNOWN_ERROR
    }
  } finally {
    password.value = ''
    verifying.value = false
  }
}

function retryConnection() {
  void props.engine.refresh()
  ElMessage.info('正在重新检测本地服务…')
}

// 中文输入法组词确认的 Enter 不得触发登录：composition 期间的 keydown 是 'Process'，
// 而 Safari 会在 compositionend 后补发 isComposing=true 的 Enter keydown，两种都要拦下。
function onEnterKey(event: Event | KeyboardEvent) {
  if (!(event instanceof KeyboardEvent)) return
  if (event.isComposing || event.keyCode === 229) return
  void verify()
}
</script>

<template>
  <div class="gate">
    <el-card class="gate-card" shadow="never">
      <div class="gate-logo"><img :src="logoUrl" alt="佳帮手" /></div>

      <el-alert v-if="engine.state.connection === 'disconnected'" class="gate-alert" type="warning" :closable="false" show-icon>
        无法连接本地服务，请确认启动器仍在运行。
        <el-button link type="primary" @click="retryConnection">重试</el-button>
      </el-alert>
      <el-alert v-else-if="engine.state.connection === 'invalid'" class="gate-alert" type="error" :closable="false" show-icon>
        服务健康检查返回了无法解析的内容，请查看诊断信息。
      </el-alert>

      <el-input v-model="username" placeholder="账号" size="large" autocomplete="username" maxlength="64" :disabled="verifying" @keydown.enter="onEnterKey" />
      <el-input
        v-model="password"
        type="password"
        show-password
        placeholder="密码"
        size="large"
        autocomplete="current-password"
        maxlength="128"
        :disabled="verifying"
        @keydown.enter="onEnterKey"
      />
      <div v-if="gateError" class="gate-error">{{ gateError }}</div>
      <div v-if="retrySeconds" class="gate-error" role="status">请在 {{ retrySeconds }} 秒后重试。</div>

      <el-button class="gate-submit" type="primary" size="large" :loading="verifying" :disabled="retrySeconds > 0" @click="verify">
        {{ verifying ? '验证中…' : '进入工作台' }}
      </el-button>

      <div class="gate-foot">
        <el-button link type="primary" size="small" @click="emit('diagnostics')">诊断信息</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.gate { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
.gate-card { width: min(420px, 100%); border-radius: 12px; }
.gate-logo { display: flex; justify-content: center; padding: 10px 0 24px; }
.gate-logo img { height: 52px; width: auto; }
.gate-alert { margin-bottom: 16px; }
.gate-error { margin-top: 10px; font-size: 12px; color: var(--el-color-danger); }
.gate-submit { width: 100%; margin-top: 16px; }
.el-input + .el-input { margin-top: 12px; }
.gate-foot { margin-top: 14px; display: flex; align-items: center; justify-content: flex-end; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
