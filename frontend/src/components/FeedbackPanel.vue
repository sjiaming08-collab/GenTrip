<script setup lang="ts">
import { ref, watch } from 'vue'
import type { FeedbackRequest, RoutePlanResult } from '../types'

const props = defineProps<{ result?: RoutePlanResult | null; sessionId?: string | null }>()
const emit = defineEmits<{ submitFeedback: [feedback: FeedbackRequest] }>()
const score = ref(5)
const comments = ref('')
const submitted = ref(false)
const expanded = ref(false)

watch(() => props.result?.route.plan_id, () => {
  submitted.value = false
  expanded.value = false
  comments.value = ''
  score.value = 5
})

function handleSubmitFeedback() {
  if (!props.result || !props.sessionId) return
  emit('submitFeedback', {
    session_id: props.sessionId,
    action: 'rate',
    route_id: props.result.route.plan_id,
    score: score.value,
    comment: comments.value.trim() || undefined,
  })
  submitted.value = true
}
</script>

<template>
  <section v-if="result" class="feedback-panel">
    <div class="feedback-header">
      <div>
        <h3>路线反馈 <span>可选</span></h3>
        <p>帮助后续路线更贴合你的偏好，不影响继续使用。</p>
      </div>
      <button type="button" class="toggle-button" @click="expanded = !expanded">{{ expanded ? '收起' : '评价路线' }}</button>
    </div>
    <p v-if="submitted" class="thanks">感谢反馈，已记录到当前会话。</p>
    <form v-else-if="expanded" class="feedback-form" @submit.prevent="handleSubmitFeedback">
      <label>评分<select v-model.number="score"><option v-for="s in [5, 4, 3, 2, 1]" :key="s" :value="s">{{ s }} 分</option></select></label>
      <label>备注<textarea v-model="comments" rows="2" placeholder="例如：减少步行，增加咖啡店" /></label>
      <button type="submit">提交评价</button>
    </form>
  </section>
</template>

<style scoped>
.feedback-panel{margin-top:1.25rem;padding:.9rem 1rem;border:1px solid #d9e3dd;border-radius:12px;background:#fafcfb}.feedback-header{display:flex;align-items:center;justify-content:space-between;gap:1rem}h3{margin:0;color:#2e4037;font-size:.9rem}h3 span{margin-left:.35rem;color:#789087;font-size:.7rem;font-weight:400}.feedback-header p{margin:.3rem 0 0;color:#718078;font-size:.75rem}.feedback-form{display:grid;gap:.75rem;margin-top:.85rem}label{display:grid;gap:.35rem;color:#465b51;font-size:.9rem}select,textarea{box-sizing:border-box;width:100%;padding:.55rem;border:1px solid #cfdcd4;border-radius:10px;font:inherit;background:#fff}button{justify-self:start;padding:.5rem 1rem;border:0;border-radius:10px;background:#167b59;color:#fff;cursor:pointer}.toggle-button{padding:.45rem .7rem;border:1px solid #c3d7ca;border-radius:9px;background:#fff;color:#26704f;white-space:nowrap}.thanks{margin:.75rem 0 0;color:#167b59;font-size:.8rem}@media(max-width:520px){.feedback-header{align-items:flex-start}.feedback-header p{max-width:15rem}}
</style>
