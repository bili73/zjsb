<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ApiFailure, BusinessApi } from '../api.ts'
import type { ManagedUser, User } from '../business.ts'
import { errorMessages } from '../diagnostics.ts'

const props = defineProps<{ api: BusinessApi }>()
const emit = defineEmits<{ unauthorized: [] }>()
const controller = new AbortController()
const users = ref<ManagedUser[]>([])
const loading = ref(false)
const creating = ref(false)
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
  if (creating.value) return
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
onMounted(refresh)
onBeforeUnmount(() => { controller.abort(); form.password = ''; form.confirmation = '' })
</script>

<template>
  <div class="accounts">
    <el-card shadow="never">
      <template #header><strong>创建账号</strong></template>
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
        <el-button type="primary" native-type="submit" :loading="creating" :disabled="loading">创建账号</el-button>
      </el-form>
    </el-card>
    <el-card shadow="never">
      <template #header><div class="list-title"><strong>已有账号</strong><el-button :loading="loading" :disabled="creating" @click="refresh">刷新列表</el-button></div></template>
      <el-table :data="users" v-loading="loading">
        <el-table-column prop="username" label="账号" min-width="160" />
        <el-table-column prop="display_name" label="姓名" min-width="160" />
        <el-table-column label="角色" width="120"><template #default="{ row }">{{ roles[row.role as User['role']] }}</template></el-table-column>
        <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.accounts { display: grid; gap: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 24px; }
.list-title { display: flex; align-items: center; justify-content: space-between; }
.el-alert { margin-bottom: 16px; }
@media (max-width: 640px) { .form-grid { grid-template-columns: 1fr; } }
</style>
