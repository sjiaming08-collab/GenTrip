<script setup lang="ts">
import { ref } from 'vue'
import type { RoutePlanResponse, FeedbackRequest } from '../types'

// ============================================================
// Props (组件接口)
// ============================================================
defineProps<{
  route?: RoutePlanResponse | null
}>()

// ============================================================
// Events
// ============================================================
const emit = defineEmits<{
  submitFeedback: [feedback: FeedbackRequest]
}>()

// ============================================================
// 状态
// ============================================================
const overallScore = ref(0)
const comments = ref('')
const submitted = ref(false)

async function handleSubmitFeedback() {
  // TODO: 实现
  // emit('submitFeedback', {
  //   route_id: route.route_id,
  //   overall_score: overallScore.value,
  //   comments: comments.value,
  // })
  throw new Error('Not implemented')
}
</script>

<template>
  <div v-if="route && !submitted" class="feedback-panel">
    <h3>这次路线怎么样？</h3>
    <!-- TODO: 实现评分 UI -->
    <!-- - 星级评分 (1-5) -->
    <!-- - 各 POI 分别评分 -->
    <!-- - 文字评论 -->
    <!-- - 提交按钮 -->
    <!-- - 提交后显示 "感谢反馈" -->
  </div>
</template>

<style scoped>
.feedback-panel {
  margin-top: 2rem;
  padding: 1rem;
  border: 1px solid #eee;
  border-radius: 8px;
}
</style>
