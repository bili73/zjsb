<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import { ApiFailure, BusinessApi } from '../api.ts'
import type { ManagedUser, User } from '../business.ts'
import { errorMessages } from '../diagnostics.ts'
import PasswordDialog from './PasswordDialog.vue'

const props = defineProps<{ api: BusinessApi; currentUser: User }>()
const emit = defineEmits<{ unauthorized: []; changePassword: []; profileChanged: [user: ManagedUser] }>()
const controller = new AbortController()
const users = ref<ManagedUser[]>([])
const loading = ref(false)
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
    <el-card shadow="never">
      <template #header><strong data-guide="account-create">创建账号</strong></template>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-alert v-if="success" :title="success" type="success" :closable="false" />
      <el-form label-position="top" @submit.prevent="create">
        <div class="form-grid">
          <el-form-item label="账号"><el-input v-model="form.username" maxlength="64" autocomplete="off" :disabled="creating" /></el-form-item>
          <el-form-item label="姓名"><el-input v-model="form.display_name" maxlength="80" autocomplete="off" :disabled="creating" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password maxlength="128" autocomplete="new-password" :disabled="creating" /></el-form-item>
          <el-form-item label="确认密码"><el-input v-model="form.confirmation" type="password" show-password maxlength="128" autocomplete="new-password" :disabled="creating" /></el-form-item>
          <el-form-item label="角色"><el-select v-model="form.role" :disabled="creating"><el-option v-for="(label, role) in roles" :key="role" :label="label" :value="role" /></el-select></el-form-item>
        </div>
        <el-button type="primary" native-type="submit" :loading="creating" :disabled="busy && !creating">创建账号</el-button>
      </el-form>
    </el-card>
    <el-card shadow="never">
      <template #header><div class="list-title" data-guide="account-list"><strong>已有账号</strong><el-button :loading="loading" :disabled="busy" @click="refresh">刷新列表</el-button></div></template>
      <el-table :data="users" v-loading="loading">
        <el-table-column label="账号" min-width="160"><template #default="{ row }">{{ row.username }} <el-tag v-if="row.user_id === currentUser.user_id" size="small">当前账号</el-tag></template></el-table-column>
        <el-table-column prop="display_name" label="姓名" min-width="160" />
        <el-table-column label="角色" width="120"><template #default="{ row }">{{ roles[row.role as User['role']] }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '禁用' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="370" fixed="right"><template #default="{ row }">
          <el-button link type="primary" :disabled="busy" @click="editName(row as ManagedUser)">编辑姓名</el-button>
          <el-button link :type="row.enabled ? 'warning' : 'success'" :disabled="busy || (row.enabled && protectedAccount(row as ManagedUser))" @click="change(row as ManagedUser, 'enabled')">{{ row.enabled ? '禁用' : '启用' }}</el-button>
          <el-button link type="primary" :disabled="busy" @click="password(row as ManagedUser)">{{ row.user_id === currentUser.user_id ? '修改密码' : '重置密码' }}</el-button>
          <el-button link type="danger" :disabled="busy || protectedAccount(row as ManagedUser)" @click="change(row as ManagedUser, 'delete')">删除</el-button>
        </template></el-table-column>
      </el-table>
      <p class="account-hint" data-guide="account-protection">当前登录账号和最后一个启用的管理员不能禁用或删除。删除账号会保留历史识别记录。</p>
    </el-card>
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
.accounts { display: grid; gap: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; }
.list-title { display: flex; align-items: center; justify-content: space-between; }
.el-alert { margin-bottom: 16px; }
.account-hint { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.7; }
@media (max-width: 640px) { .form-grid { grid-template-columns: 1fr; } }
</style>
