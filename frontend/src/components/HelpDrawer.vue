<script setup lang="ts">
// 站内说明抽屉：在当前页内嵌打开静态说明书，不再弹出新窗口/标签页。
// 说明书自身的“返回工作台”链接在 iframe 内会自动隐藏（页面内置 embedded 检测）。
defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'update:open', value: boolean): void }>()
</script>

<template>
  <el-drawer
    :model-value="open"
    title="使用说明"
    size="min(1080px, 94%)"
    append-to-body
    destroy-on-close
    class="help-drawer"
    @update:model-value="value => emit('update:open', value)"
  >
    <iframe class="help-frame" src="/help/index.html" title="使用说明"></iframe>
  </el-drawer>
</template>

<style>
/* 抽屉 teleport 到 body，需用全局样式去掉默认内边距，让说明书占满抽屉。 */
.help-drawer .el-drawer__body { padding: 0; overflow: hidden; }
</style>

<style scoped>
.help-frame { width: 100%; height: 100%; border: 0; display: block; background: #f4f8f7; }
</style>
