<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { ApiFailure, BusinessApi } from '../api.ts'
import type { ManagedUser, User } from '../business.ts'
import { errorMessages } from '../diagnostics.ts'
import PasswordDialog from './PasswordDialog.vue'

const props = defineProps<{ api: BusinessApi; currentUser: User }>()
const emit = defineEmits<{ unauthorized: []; changePassword: []; profileChanged: [user: ManagedUser] }>()
const controller = new AbortController()
const users = ref<ManagedUser[]>([])
const loading = ref(false)
// Full-list account data also powers last-administrator protection across pages.
const page = ref(1), pageSize = ref(20)
const pagedUsers = computed(() => users.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
watch(users, () => {
  const last = Math.max(1, Math.ceil(users.value.length / pageSize.value))
  if (page.value > last) page.value = last
})
function resizePage(size: number) { pageSize.value = size; page.value = 1 }
const creating = ref(false)
const changing = ref('')
const passwordTarget = ref<ManagedUser | undefined>()
const editing = ref<ManagedUser | undefined>()
const editedName = ref('')
const savingName = ref(false)
const editError = ref('')
const busy = computed(() => loading.value || creating.value || !!changing.value || !!passwordTarget.value || !!editing.value)
const adminCount = computed(() => users.value.filter(user => user.enabled && user.role === 'admin').length)
const error = ref('')
const success = ref('')
// 任何操作（创建/禁用/删除/重置/改名）的反馈都落在面板顶部同一条位置，避免散在各区块。
const feedback = computed(() => error.value ? { type: 'error' as const, text: error.value } : success.value ? { type: 'success' as const, text: success.value } : null)
const form = reactive({ username: '', display_name: '', password: '', confirmation: '', role: 'operator' as User['role'] })
const roles = { operator: '操作员', viewer: '只读', admin: '管理员' }

function failed(failure: unknown) {
  if (controller.signal.aborted) return
  if (failure instanceof ApiFailure && failure.card.http_status === 401) emit('unauthorized')
  else error.value = failure instanceof ApiFailure ? errorMessages[failure.card.code] : '操作失败，请重试。'
}
async function refresh() {
  loading.value = true
  try { users.value = await props.api.users(controller.signal) } catch (failure) { failed(failure) }
  finally { loading.value = false }
}
async function create() {
  if (busy.value) return
  error.value = ''; success.value = ''
  if (!/^[A-Za-z0-9_.-]{1,64}$/.test(form.username) || !form.display_name.trim()) {
    error.value = '请填写有效账号和姓名；账号可使用字母、数字、下划线、点和短横线。'; return
  }
  if (form.password.length < 8 || form.password.length > 128 || !form.password.trim()) {
    error.value = '密码需8至128个字符。'; return
  }
  if (form.password !== form.confirmation) { error.value = '两次密码输入不一致。'; return }
  creating.value = true
  try {
    const user = await props.api.createUser({ username: form.username, display_name: form.display_name.trim(), password: form.password, role: form.role }, controller.signal)
    users.value = [...users.value, user].sort((a, b) => a.username.localeCompare(b.username))
    success.value = `账号 ${user.username} 已创建，可以登录。`
    form.username = ''; form.display_name = ''; form.role = 'operator'
  } catch (failure) { failed(failure) }
  finally { form.password = ''; form.confirmation = ''; creating.value = false }
}
function protectedAccount(user: ManagedUser) {
  return user.user_id === props.currentUser.user_id || (user.enabled && user.role === 'admin' && adminCount.value <= 1)
}
function password(user: ManagedUser) {
  if (user.user_id === props.currentUser.user_id) emit('changePassword')
  else passwordTarget.value = user
}
function passwordSaved() {
  const username = passwordTarget.value?.username
  passwordTarget.value = undefined
  error.value = ''; success.value = `账号 ${username} 的密码已重置，所有旧登录已失效。`
  void refresh()
}
async function change(user: ManagedUser, action: 'enabled' | 'delete') {
  if (busy.value) return
  changing.value = user.user_id
  error.value = ''; success.value = ''
  try {
    if (action === 'delete' || user.enabled) {
      try {
        await ElMessageBox.confirm(action === 'delete'
          ? `确定删除账号 ${user.username}？该账号将不能登录，历史任务和识别记录会保留。此操作不能撤销。`
          : `确定禁用账号 ${user.username}？该账号会立即退出，重新启用前不能登录。`,
          action === 'delete' ? '删除账号' : '禁用账号',
          { type: 'warning', confirmButtonText: action === 'delete' ? '确认删除' : '确认禁用', cancelButtonText: '取消' })
      } catch { return }
    }
    if (controller.signal.aborted) return
    if (action === 'delete') await props.api.deleteUser(user.user_id, controller.signal)
    else await props.api.updateUserEnabled(user.user_id, !user.enabled, controller.signal)
    emit('profileChanged', user)
    success.value = `账号 ${user.username} 已${action === 'delete' ? '删除，历史记录保留' : user.enabled ? '禁用' : '启用，请重新登录'}。`
    await refresh()
  } catch (failure) {
    failed(failure)
    if (failure instanceof ApiFailure && [404, 409].includes(failure.card.http_status ?? 0)) await refresh()
  } finally { changing.value = '' }
}
function editName(user: ManagedUser) {
  if (busy.value) return
  editing.value = user
  editedName.value = user.display_name
  editError.value = ''
}
async function saveName() {
  if (!editing.value || savingName.value) return
  const name = editedName.value.trim()
  if (!name || name.length > 80) { editError.value = '姓名需1至80个字符，不能全为空白。'; return }
  savingName.value = true
  editError.value = ''
  try {
    const updated = await props.api.updateUserName(editing.value.user_id, name, controller.signal)
    users.value = users.value.map(user => user.user_id === updated.user_id ? updated : user)
    emit('profileChanged', updated)
    editing.value = undefined
    error.value = ''; success.value = `账号 ${updated.username} 的姓名已更新。`
  } catch (failure) {
    if (!controller.signal.aborted) {
      if (failure instanceof ApiFailure && failure.card.http_status === 401) emit('unauthorized')
      else editError.value = failure instanceof ApiFailure ? errorMessages[failure.card.code] : '保存失败，请重试。'
    }
  } finally { savingName.value = false }
}
onMounted(refresh)
onBeforeUnmount(() => { controller.abort(); form.password = ''; form.confirmation = '' })
</script>

<template>
  <div class="accounts">
    <el-alert v-if="feedback" :title="feedback.text" :type="feedback.type" :closable="false" show-icon />
    <el-form class="create-bar" data-guide="account-create" @submit.prevent="create">
      <strong class="bar-title">创建账号</strong>
      <el-input v-model="form.username" maxlength="64" autocomplete="off" placeholder="登录账号" :disabled="creating" />
      <el-input v-model="form.display_name" maxlength="80" autocomplete="off" placeholder="姓名" :disabled="creating" />
      <el-input v-model="form.password" type="password" show-password maxlength="128" autocomplete="new-password" placeholder="密码（至少 8 位）" :disabled="creating" />
      <el-input v-model="form.confirmation" type="password" show-password maxlength="128" autocomplete="new-password" placeholder="确认密码" :disabled="creating" />
      <el-select v-model="form.role" :disabled="creating" aria-label="角色">
        <el-option v-for="(label, role) in roles" :key="role" :label="label" :value="role" />
      </el-select>
      <el-button type="primary" native-type="submit" :icon="Plus" :loading="creating" :disabled="busy && !creating">创建账号</el-button>
    </el-form>
    <section class="list-section">
      <div class="list-head" data-guide="account-list">
        <strong>已有账号</strong>
        <span class="count">{{ users.length }} 个</span>
        <el-button :loading="loading" :disabled="busy" @click="refresh">刷新列表</el-button>
      </div>
      <el-table :data="pagedUsers" v-loading="loading" stripe>
        <el-table-column label="账号" min-width="170"><template #default="{ row }">{{ row.username }} <el-tag v-if="row.user_id === currentUser.user_id" size="small" effect="plain">当前账号</el-tag></template></el-table-column>
        <el-table-column prop="display_name" label="姓名" min-width="150" />
        <el-table-column label="角色" width="110"><template #default="{ row }">{{ roles[row.role as User['role']] }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag size="small" effect="light" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '禁用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="370" fixed="right"><template #default="{ row }">
          <el-button link type="primary" :disabled="busy" @click="editName(row as ManagedUser)">编辑姓名</el-button>
          <el-button link :type="row.enabled ? 'warning' : 'success'" :disabled="busy || (row.enabled && protectedAccount(row as ManagedUser))" @click="change(row as ManagedUser, 'enabled')">{{ row.enabled ? '禁用' : '启用' }}</el-button>
          <el-button link type="primary" :disabled="busy" @click="password(row as ManagedUser)">{{ row.user_id === currentUser.user_id ? '修改密码' : '重置密码' }}</el-button>
          <el-button link type="danger" :disabled="busy || protectedAccount(row as ManagedUser)" @click="change(row as ManagedUser, 'delete')">删除</el-button>
        </template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="pageSize" @update:page-size="resizePage"
        :disabled="busy" :total="users.length" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next, jumper" background class="list-pager" />
      <p class="account-hint" data-guide="account-protection">当前登录账号和最后一个启用的管理员不能禁用或删除。删除账号会保留历史识别记录。</p>
    </section>
    <PasswordDialog v-if="passwordTarget" :api="api" :target="passwordTarget" @close="passwordTarget = undefined" @saved="passwordSaved" @unauthorized="emit('unauthorized')" />
    <el-dialog :model-value="!!editing" title="编辑账号姓名" width="420px" :close-on-click-modal="false" :close-on-press-escape="!savingName" :show-close="!savingName" @close="editing = undefined">
      <el-alert v-if="editError" :title="editError" type="error" :closable="false" />
      <el-form label-position="top" @submit.prevent="saveName">
        <el-form-item label="账号"><el-input :model-value="editing?.username" disabled /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="editedName" maxlength="80" :disabled="savingName" autocomplete="off" /></el-form-item>
        <p class="account-hint">修改姓名不会改变登录账号、密码和批次归属。</p>
        <el-button :disabled="savingName" @click="editing = undefined">取消</el-button>
        <el-button type="primary" native-type="submit" :loading="savingName">保存</el-button>
      </el-form>
    </el-dialog>
  </div>
</template>

<style scoped>
.accounts { display: grid; gap: 14px; }
/* 创建账号：单行工具条（窄屏自动换行），占位符代替常驻标签，与审计/批次工具栏同风格。 */
.create-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 14px; background: var(--el-fill-color-lighter); border-radius: 10px; }
.bar-title { font-size: 14px; margin-right: 4px; }
.create-bar .el-input { width: 185px; }
.create-bar .el-select { width: 130px; }
.list-head { display: flex; align-items: center; gap: 10px; }
.list-head strong { font-size: 15px; }
.list-head .count { font-size: 12px; color: var(--el-text-color-secondary); }
.list-head .el-button { margin-left: auto; }
.list-section { display: grid; gap: 10px; }
.list-pager { justify-content: flex-end; flex-wrap: wrap; row-gap: 8px; }
.account-hint { margin: 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; }
</style>
