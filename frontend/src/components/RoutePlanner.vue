<script setup lang="ts">
import { ref } from 'vue'
import type { RoutePlanRequest } from '../types'

const props = defineProps<{
  isLoading?: boolean
}>()

const emit = defineEmits<{
  submit: [request: RoutePlanRequest]
}>()

const query = ref('黄浦区看展览再喝咖啡，18点前回')

function handleSubmit() {
  const value = query.value.trim()
  if (!value || props.isLoading) return
  emit('submit', { query: value })
}
</script>

<template>
  <form class="route-planner" @submit.prevent="handleSubmit">
    <textarea
      v-model="query"
      placeholder="例如：周末下午和朋友在徐汇区逛吃3小时，火锅，人均200以内"
      rows="3"
      :disabled="isLoading"
    />
    <button type="submit" :disabled="isLoading || !query.trim()">
      {{ isLoading ? '规划中...' : '开始规划' }}
    </button>
  </form>
</template>

<style scoped>
.route-planner {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
textarea {
  width: 100%;
  min-height: 88px;
  box-sizing: border-box;
  padding: 0.75rem;
  border: 1px solid #d8dde6;
  border-radius: 8px;
  font-size: 1rem;
  line-height: 1.5;
  resize: vertical;
}
button {
  align-self: flex-end;
  padding: 0.6rem 1.5rem;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  cursor: pointer;
}
button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>