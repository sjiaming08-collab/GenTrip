<script setup lang="ts">
import { ref, watch } from 'vue'
import type { FeedbackRequest, RoutePlanResult } from '../types'

const props = defineProps<{
  result?: RoutePlanResult | null
  sessionId?: string | null
}>()

const emit = defineEmits<{
  submitFeedback: [feedback: FeedbackRequest]
}>()

const score = ref(5)
const comments = ref('')
const submitted = ref(false)

watch(
  () => props.result?.route.plan_id,
  () => {
    submitted.value = false
    comments.value = ''
    score.value = 5
  }
)

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
    <h3>这次路线怎么样？</h3>
    <p v-if="submitted" class="thanks">感谢反馈</p>
    <form v-else class="feedback-form" @submit.prevent="handleSubmitFeedback">
      <label>
        评分
        <select v-model.number="score">
          <option v-for="s in [5, 4, 3, 2, 1]" :key="s" :value="s">
            {{ s }} 分
          </option>
        </select>
      </label>
      <label>
        备注
        <textarea v-model="comments" rows="2" placeholder="例如：想减少步行、增加咖啡店" />
      </label>
      <button type="submit">提交反馈</button>
    </form>
  </section>
</template>

<style scoped>
.feedback-panel {
  margin-top: 1.5rem;
  padding: 1rem;
  border: 1px solid #d9ebdf;
  border-radius: 8px;
  background: #fff;
}
h3 {
  margin: 0 0 0.75rem;
}
.feedback-form {
  display: grid;
  gap: 0.75rem;
}
label {
  display: grid;
  gap: 0.35rem;
  color: #416454;
  font-size: 0.9rem;
}
select,
textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 0.55rem;
  border: 1px solid #cfe4d6;
  border-radius: 8px;
  font: inherit;
}
button {
  justify-self: start;
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 8px;
  background: #167b59;
  color: #fff;
  cursor: pointer;
}
.thanks {
  margin: 0;
  color: #167b59;
}
</style>
