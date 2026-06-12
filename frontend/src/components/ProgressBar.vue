<script setup lang="ts">
// ============================================================
// Props (组件接口)
// ============================================================
defineProps<{
  currentPhase: string
  phases: string[]
}>()

defineEmits<{
  cancel: []
}>()
</script>

<template>
  <div class="progress-bar">
    <!-- TODO: 实现 SSE 进度条 -->
    <!-- 1. 渲染 phases 列表 -->
    <!-- 2. 高亮 currentPhase -->
    <!-- 3. 显示阶段中文名: intent_parse → "正在理解需求" -->
    <!-- 4. 取消按钮 -->
  </div>
</template>

<style scoped>
.progress-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
}
</style>
