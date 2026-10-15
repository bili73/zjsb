<script setup lang="ts">
import type { FieldSource } from '../business.ts'
import type { GenericResult } from '../generic-review.ts'
defineProps<{ original: GenericResult }>()
const emit=defineEmits<{(e:'locate',source:FieldSource):void}>()
</script>
<template>
  <section class="generic-sources">
    <h3 data-guide="generic-result">通用表单识别</h3>
    <p>已提取 {{ original.key_values.length }} 个键值、{{ original.tables?.length ?? 0 }} 个表格。字段可在下方修改；重复字段分别保留。位置和结构判断未经置信度标定，请对照原件核对。</p>
    <details>
      <summary>初始识别内容与来源（只读）</summary>
      <article v-for="(block,index) in original.blocks ?? []" :key="index">
        <b>第 {{ block.page }} 页 · 区域 {{ index+1 }}</b>
        <el-button v-if="block.source" link type="primary" @click="emit('locate',block.source)">查看来源区域</el-button>
        <pre>{{ block.text }}</pre>
        <details v-if="block.raw_text && block.raw_text!==block.text"><summary>原始 OCR 输出</summary><pre>{{ block.raw_text }}</pre></details>
      </article>
    </details>
    <details v-for="(table,index) in original.tables ?? []" :key="index">
      <summary>识别表格 {{ index+1 }} · {{ table.rows.length }} 行</summary>
      <el-button link type="primary" @click="emit('locate',table.source)">查看表格来源</el-button>
      <p v-if="table.rows.length>20">预览前20行；完整内容保留在正文和导出中。</p>
      <pre>{{ table.rows.slice(0,20).map(row=>row.join('\t')).join('\n') }}</pre>
    </details>
  </section>
</template>
<style scoped>
.generic-sources{margin:16px 0}.generic-sources pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;padding:12px}.generic-sources article{border-bottom:1px solid #ddd;padding:10px 0}.generic-sources summary{cursor:pointer;padding:8px 0}
</style>
