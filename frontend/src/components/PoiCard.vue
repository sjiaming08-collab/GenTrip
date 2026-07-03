<script setup lang="ts">
import type { ItineraryStop } from '../types'

// ============================================================
// Props (组件接口)
// ============================================================
defineProps<{
  stop: ItineraryStop
  isCurrent?: boolean
}>()

// ============================================================
// Events
// ============================================================
const emit = defineEmits<{
  click: [stop: ItineraryStop]
}>()
</script>

<template>
  <div class="poi-card" :class="{ current: isCurrent }">
    <!-- TODO: 实现 POI 卡片 -->
    <!-- - 封面图 -->
    <!-- - 名称 + 评分 + 人均 -->
    <!-- - 到达/离开时间 -->
    <!-- - 出行方式图标 -->
    <!-- - AI 贴士 -->
    <!-- - 排队预估 -->
  </div>
</template>

<style scoped>
.poi-card {
  padding: 0.75rem;
  border: 1px solid #eee;
  border-radius: 8px;
  margin-bottom: 0.5rem;
  cursor: pointer;
  transition: border-color 0.2s;
}
.poi-card:hover {
  border-color: #4a90d9;
}
.poi-card.current {
  border-color: #4a90d9;
  background: #f0f6ff;
}
</style>
