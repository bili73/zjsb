<script setup lang="ts">
import { onBeforeUnmount, reactive, ref } from 'vue'
import { ApiFailure, BusinessApi } from '../api.ts'
import type { ManagedUser } from '../business.ts'
import { errorMessages } from '../diagnostics.ts'

const props = defineProps<{ api: BusinessApi; target?: ManagedUser }>()
const emit = defineEmits<{ close: []; saved: []; unauthorized: [] }>()
const controller = new AbortController()
const saving = ref(false)
const error = ref('')
const form = reactive({ current: '', password: '', confirmation: '' })
function clear() { form.current = ''; form.password = ''; form.confirmation = '' }
async function save() {
  if (saving.value) return
  error.value = ''
  if (!props.target && !form.current) { error.value = '请输入原密码。'; return }
  if (form.password.length < 8 || form.password.length > 128 || !form.password.trim()) {
    error.value = '新密码需8至128个字符，不能全为空白。'; return
  }
  if (form.password !== form.confirmation) { error.value = '两次新密码输入不一致。'; return }
  saving.value = true
  try {
    if (props.target) await props.api.resetUserPassword(props.target.user_id, form.password, controller.signal)
    else await props.api.changePassword(form.current, form.password, controller.signal)
    emit('saved')
  } catch (failure) {
    if (controller.signal.aborted) return
    if (failure instanceof ApiFailure && failure.card.http_status === 401) emit('unauthorized')
    else error.value = failure instanceof ApiFailure ? errorMessages[failure.card.code] : '修改失败，请重试。'
  } finally { clear(); saving.value = false }
}
onBeforeUnmount(() => { controller.abort(); clear() })
</script>

<template>
  <el-dialog :model-value="true" :title="target ? `重置 ${target.username} 的密码` : '修改密码'" width="min(480px, 92vw)"
    :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving"
    @update:model-value="value => { if (!value && !saving) emit('close') }">
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p v-if="target">重置后，该账号的所有登录都会失效，需使用新密码重新登录。{{ target.enabled ? '' : '该账号仍保持禁用。' }}</p>
    <p v-else>修改成功后，所有设备上的登录都会失效，请使用新密码重新登录。</p>
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item v-if="!target" label="原密码" for="password-current">
        <el-input id="password-current" v-model="form.current" type="password" show-password maxlength="128" autocomplete="current-password" :disabled="saving" />
      </el-form-item>
      <el-form-item label="新密码" for="password-new">
        <el-input id="password-new" v-model="form.password" type="password" show-password maxlength="128" autocomplete="new-password" :disabled="saving" />
      </el-form-item>
      <el-form-item label="确认新密码" for="password-confirm">
        <el-input id="password-confirm" v-model="form.confirmation" type="password" show-password maxlength="128" autocomplete="new-password" :disabled="saving" />
      </el-form-item>
      <div class="password-actions">
        <el-button :disabled="saving" @click="emit('close')">取消</el-button>
        <el-button type="primary" native-type="submit" :loading="saving">{{ target ? '确认重置' : '保存新密码' }}</el-button>
      </div>
    </el-form>
  </el-dialog>
</template>

<style scoped>
p { line-height: 1.7; color: var(--el-text-color-regular); }
.password-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
