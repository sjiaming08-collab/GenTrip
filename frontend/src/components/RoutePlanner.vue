<script setup lang="ts">
import { ref } from 'vue'
import type { RoutePlanRequest } from '../types'

// ============================================================
// Props / Emits (组件接口)
// ============================================================
const emit = defineEmits<{
  submit: [request: RoutePlanRequest]
}>()

// ============================================================
// 状态
// ============================================================
const query = ref('')
const isLoading = ref(false)

// ============================================================
// 方法 (留空，仅签名)
// ============================================================
async function handleSubmit() {
  // TODO: 实现
  // 1. emit('submit', { query: query.value })
  // 2. 触发父组件调用 useRoutePlan().submitQuery()
  throw new Error('Not implemented')
}
</script>

<template>
  <div class="route-planner">
    <textarea
      v-model="query"
      placeholder="例如：周末下午和朋友在徐汇区逛吃3小时，火锅，人均200以内，不想排队"
      rows="3"
      :disabled="isLoading"
    />
    <button @click="handleSubmit" :disabled="isLoading">
      {{ isLoading ? '规划中...' : '开始规划' }}
    </button>
  </div>
</template>

<style scoped>
.route-planner {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
textarea {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 1rem;
  resize: vertical;
}
button {
  align-self: flex-end;
  padding: 0.6rem 1.5rem;
  background: #4a90d9;
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
