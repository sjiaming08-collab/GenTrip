<script setup lang="ts">
import { ref } from 'vue'
import type { RoutePlanRequest } from '../types'

const props = defineProps<{
  isLoading?: boolean
}>()

const emit = defineEmits<{
  submit: [request: RoutePlanRequest]
}>()

const query = ref('')
const suggestions = ['下午出发，3 小时', '少走路', '想吃日料', '适合朋友聚会']

function handleSubmit() {
  const value = query.value.trim()
  if (!value || props.isLoading) return
  emit('submit', { query: value })
  query.value = ''
}

function applySuggestion(value: string) {
  query.value = query.value.trim() ? `${query.value}，${value}` : value
}
</script>

<template>
  <form class="route-planner" @submit.prevent="handleSubmit">
    <div class="composer-field">
      <label for="route-query">这次想怎么走</label>
      <textarea
        id="route-query"
        v-model="query"
        placeholder="例如：周末下午和朋友在徐汇区逛吃 3 小时，火锅，人均 200 元"
        rows="2"
        :disabled="isLoading"
        @keydown.enter.exact.prevent="handleSubmit"
      />
      <div class="suggestion-row" aria-label="快捷补充条件">
        <button v-for="suggestion in suggestions" :key="suggestion" type="button" :disabled="isLoading" @click="applySuggestion(suggestion)">{{ suggestion }}</button>
      </div>
    </div>
    <div class="composer-actions">
      <span>{{ query.trim() ? '准备生成路线' : '输入出行想法' }}</span>
      <button type="submit" :disabled="isLoading || !query.trim()">
        {{ isLoading ? '规划中' : '开始规划' }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.route-planner { display: grid; gap: 8px; padding: 13px 16px 11px; border: 1px solid #c8dad0; border-radius: 8px; background: #fff; box-shadow: 0 12px 30px rgba(31, 68, 49, .10); }
.composer-field { display: grid; gap: 5px; }
label { color: #54806a; font-size: 11px; font-weight: 800; letter-spacing: .08em; }
textarea {
  width: 100%;
  min-height: 62px;
  box-sizing: border-box;
  padding: 0.55rem 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #254a39;
  font-size: 15px;
  line-height: 1.55;
  resize: none;
}
.composer-field:focus-within label { color: #167b59; }
textarea:focus { outline: none; }
textarea::placeholder { color: #9bb2a5; }
.suggestion-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:1px}.suggestion-row button{min-height:auto;padding:4px 7px;border:1px solid #d7e5db;border-radius:4px;background:#f8fbf9;color:#527366;font-size:11px;font-weight:600}.suggestion-row button:not(:disabled):hover{border-color:#72a88a;background:#edf6ef;color:#236f4e}
.composer-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 9px; border-top: 1px solid #e5f0e8; }
.composer-actions span { color: #80998b; font-size: 12px; }
button {
  min-height: 36px;
  padding: 0.5rem 0.9rem;
  background: #167b59;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}
button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
button:not(:disabled):hover { background: #0e6748; }
@media (max-width: 560px) { .route-planner { padding: 11px; } }
</style>
