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
.route-planner { display: grid; gap: 10px; padding: 14px 16px 12px; border: 1px solid #d2dcd6; border-radius: 14px; background: #fff; box-shadow: 0 12px 32px rgba(38, 50, 44, .09); }
.composer-field { display: grid; gap: 5px; }
label { color: #54806a; font-size: 11px; font-weight: 800; letter-spacing: .08em; }
textarea {
  width: 100%;
  min-height: 62px;
  box-sizing: border-box;
  padding: 0.65rem 0.75rem;
  border: 1px solid #e0e6e2;
  border-radius: 10px;
  background: #f7f9f8;
  color: #2d3c35;
  font-size: 15px;
  line-height: 1.55;
  resize: none;
}
.composer-field:focus-within label { color: #167b59; }
textarea:focus { border-color: #8dbba4; background: #fff; outline: none; box-shadow: 0 0 0 3px rgba(37, 130, 88, .08); }
textarea::placeholder { color: #9bb2a5; }
.suggestion-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:1px}.suggestion-row button{min-height:auto;padding:5px 8px;border:1px solid #d9e1dc;border-radius:9px;background:#fff;color:#526960;font-size:11px;font-weight:600}.suggestion-row button:not(:disabled):hover{border-color:#72a88a;background:#edf6ef;color:#236f4e}
.composer-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 9px; border-top: 1px solid #e5f0e8; }
.composer-actions span { color: #80998b; font-size: 12px; }
button {
  min-height: 36px;
  padding: 0.5rem 0.9rem;
  background: #167b59;
  color: white;
  border: none;
  border-radius: 10px;
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
