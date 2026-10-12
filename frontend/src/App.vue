<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef } from 'vue'
import { ElMessage } from 'element-plus'
import { Reading, SwitchButton, Tools, User as UserIcon } from '@element-plus/icons-vue'
import { ApiFailure, BusinessApi } from './api.ts'
import { resultKey } from './business.ts'
import type { DocProfile, ManagedUser, Task, User } from './business.ts'
import { createEngine } from './engine.ts'
import { createMonitor } from './monitor.ts'
import { LocalPreviewBatch } from './workbench.ts'
import logoUrl from './assets/joybos-logo.png'
import LoginGate from './components/LoginGate.vue'
import UploadPanel from './components/UploadPanel.vue'
import BatchBoard from './components/BatchBoard.vue'
import EngineStatus from './components/EngineStatus.vue'
import TaskResultDrawer from './components/TaskResultDrawer.vue'
import DiagnosticsPanel from './components/DiagnosticsPanel.vue'
import HelpDrawer from './components/HelpDrawer.vue'
import AccountManagement from './components/AccountManagement.vue'
import RequiredFieldSettings from './components/RequiredFieldSettings.vue'
import PasswordDialog from './components/PasswordDialog.vue'

const api = shallowRef<BusinessApi | null>(null)
const user = shallowRef<User | null>(null)
const restoring = ref(true)
const sessionController = new AbortController()
const catalogue = ref<DocProfile[]>([])
const catalogueError = ref('')
const engine = createEngine()
const engineSummary = engine.summary
const monitor = createMonitor(() => api.value, { onUnauthorized: () => handleUnauthorized() })
const previews = new LocalPreviewBatch()
const activeTab = ref('upload')
const uploadReset = ref(0)
const diagnosticsOpen = ref(false)
const helpOpen = ref(false)
const passwordOpen = ref(false)
const drawerInfo = reactive({ open: false, batchId: '', taskId: '' })

const canWrite = computed(() => user.value?.role === 'operator' || user.value?.role === 'admin')
const roleLabel = computed(() => ({ viewer: '只读', operator: '操作员', admin: '管理员' })[user.value?.role ?? 'viewer'])
// The drawer always renders the monitor's live copy so a rerun swaps in the
// new run_id/result_revision and the content refetches itself.
const liveTask = computed<Task | null>(() => {
  const entry = monitor.state.entries[drawerInfo.batchId]
  return entry?.tasks.find(task => task.task_id === drawerInfo.taskId) ?? null
})

async function handleAuthenticated(client: BusinessApi, verified: User) {
  api.value = client
  user.value = verified
  monitor.start()
  catalogueError.value = ''
  try {
    const items = await client.catalogue(new AbortController().signal)
    if (api.value === client) catalogue.value = items
  } catch(error) {
    if (api.value !== client) return
    if(error instanceof ApiFailure && error.card.http_status === 401){handleUnauthorized();return}
    catalogueError.value='材料目录读取失败，请重新验证连接后再上传。'
  }
}

function profileChanged(updated: ManagedUser) {
  if (user.value?.user_id === updated.user_id) user.value = { ...user.value, display_name: updated.display_name }
  monitor.start()
}

function endSession(message?: string) {
  // 多路 401（后台轮询与组件请求）可能同时汇聚；会话已结束时不再重复提示。
  if (!user.value && !api.value) return
  catalogue.value = []
  api.value = null
  user.value = null
  activeTab.value = 'upload'
  drawerInfo.open = false
  passwordOpen.value = false
  monitor.clear()
  previews.clear()
  if (message) ElMessage.warning(message)
}

function handleUnauthorized() { endSession('登录状态已失效，请重新登录。') }

function openResult(task: Task, batchId: string) {
  drawerInfo.batchId = batchId
  drawerInfo.taskId = task.task_id
  drawerInfo.open = true
}

function handleSubmitted() { uploadReset.value++; activeTab.value = 'batches' }
function batchDeleted(batchId: string, taskIds: string[]) {
  previews.remove(taskIds)
  if (drawerInfo.batchId === batchId) drawerInfo.open = false
}
async function onHeaderCommand(command: string | number | object) {
  if (command === 'password') { passwordOpen.value = true; return }
  if (command !== 'logout' || !api.value) return
  try { await api.value.logout(new AbortController().signal); endSession() }
  catch (error) {
    if (error instanceof ApiFailure && error.card.http_status === 401) endSession()
    else ElMessage.error('退出未完成，请检查连接后重试。')
  }
}
function passwordChanged() { endSession(); ElMessage.success('密码已更新，请使用新密码重新登录。') }
async function registerPreviews(files: readonly File[], tasks: readonly Task[]) { try { await previews.addMatched(files, tasks) } catch { /* A preview binding failure must never change accepted tasks. */ } }
function reviewed(task: Task) { const entry=monitor.entryOf(task.task_id); if(entry) entry.tasks=entry.tasks.map(t=>t.task_id===task.task_id?task:t); monitor.start() }
async function requiredFieldsSaved() {
  if (!api.value) return
  try { catalogue.value = await api.value.catalogue(new AbortController().signal) }
  catch (error) { if (error instanceof ApiFailure && error.card.http_status === 401) handleUnauthorized() }
  monitor.start()
}

const onVisibility = () => { monitor.onVisible(!document.hidden) }
onMounted(async () => {
  engine.install()
  void engine.refresh()
  document.addEventListener('visibilitychange', onVisibility)
  const client = new BusinessApi()
  try { await handleAuthenticated(client, await client.auth(sessionController.signal)) }
  catch { /* An expired/unavailable session returns to the login form. */ }
  finally { restoring.value = false }
})
onBeforeUnmount(() => {
  sessionController.abort()
  document.removeEventListener('visibilitychange', onVisibility)
  engine.dispose()
  monitor.dispose()
  previews.clear()
})
</script>

<template>
  <div v-if="restoring" class="restoring">
    <img class="restoring-logo" :src="logoUrl" alt="佳帮手" />
    <span class="rainbow-spinner" aria-hidden="true"></span>
    <span>正在恢复登录…</span>
  </div>
  <LoginGate v-else-if="!user" :engine="engine" @authenticated="handleAuthenticated" @diagnostics="diagnosticsOpen = true" />
  <div v-else class="app-shell">
    <header class="app-header">
      <div class="brand">
        <img class="brand-logo" :src="logoUrl" alt="佳帮手" />
        <div>
          <h1>HRSSC识别工作台</h1>
          <p>本地识别 · 数据不出本机</p>
        </div>
      </div>
      <div class="header-side">
        <el-tag class="engine-badge" :type="engineSummary.tone" effect="light" round title="查看引擎状态" @click="activeTab = 'engine'">
          {{ engineSummary.label }}
        </el-tag>
        <div class="header-actions">
          <el-button :icon="Reading" text class="header-text-btn" @click="helpOpen = true">使用说明</el-button>
          <el-button :icon="Tools" text class="header-text-btn" @click="diagnosticsOpen = true">诊断</el-button>
        </div>
        <el-divider direction="vertical" />
        <el-dropdown @command="onHeaderCommand">
          <span class="user-chip">
            <el-icon><UserIcon /></el-icon>
            {{ user.display_name }}
            <el-tag size="small" type="info" effect="plain">{{ roleLabel }}</el-tag>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="password">修改密码</el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <main class="app-main">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="上传识别" name="upload">
          <el-alert v-if="catalogueError" :closable="false" type="error">{{ catalogueError }}</el-alert>
          <UploadPanel :api="api" :catalogue="catalogue" :monitor="monitor" :can-write="canWrite" @submitted="handleSubmitted" @preview="registerPreviews" @unauthorized="handleUnauthorized" />
        </el-tab-pane>
        <el-tab-pane label="任务批次" name="batches">
          <BatchBoard :api="api" :monitor="monitor" :can-write="canWrite" :is-admin="user.role === 'admin'" :upload-reset="uploadReset" :catalogue="catalogue" @open-result="openResult" @batch-deleted="batchDeleted" @unauthorized="handleUnauthorized" />
        </el-tab-pane>
        <el-tab-pane label="引擎状态" name="engine">
          <EngineStatus :engine="engine" />
        </el-tab-pane>
        <el-tab-pane v-if="user.role === 'admin'" label="账号管理" name="accounts" lazy>
          <AccountManagement v-if="api" :api="api" :current-user="user" @change-password="passwordOpen = true" @unauthorized="handleUnauthorized" @profile-changed="profileChanged" />
        </el-tab-pane>
        <el-tab-pane v-if="user.role === 'admin'" label="必填字段设置" name="required" lazy>
          <RequiredFieldSettings v-if="api" :api="api" @saved="requiredFieldsSaved" @unauthorized="handleUnauthorized" />
        </el-tab-pane>
      </el-tabs>
    </main>

    <footer class="app-footer">登录会话由服务端 Cookie 保持（最长 12 小时），过期或退出后需重新登录；诊断信息不含密码与识别内容。</footer>

    <TaskResultDrawer v-model:open="drawerInfo.open" :task="liveTask" :api="api" :monitor="monitor" :previews="previews" :can-write="canWrite" :catalogue="catalogue" @reviewed="reviewed" @bank-retried="drawerInfo.open = false; handleSubmitted()" @preview="registerPreviews" @unauthorized="handleUnauthorized" />
    <PasswordDialog v-if="passwordOpen && api" :api="api" @close="passwordOpen = false" @saved="passwordChanged" @unauthorized="handleUnauthorized" />
  </div>
  <DiagnosticsPanel v-model:open="diagnosticsOpen" />
  <HelpDrawer v-model:open="helpOpen" />
</template>

<style scoped>
.restoring { min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: var(--el-text-color-secondary); font-size: 14px; }
.restoring-logo { height: 40px; width: auto; }
.user-chip { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; font-size: 14px; color: var(--el-text-color-primary); outline: none; }
.header-actions { display: inline-flex; align-items: center; gap: 4px; }
.header-text-btn { --el-button-text-color: var(--el-text-color-regular); font-weight: 500; }
.header-text-btn:hover { --el-button-text-color: var(--el-color-primary); --el-button-hover-text-color: var(--el-color-primary); }
</style>
