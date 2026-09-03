<script setup lang="ts">
import type { RouteStop } from '../types'

defineProps<{
  stop: RouteStop
  isCurrent?: boolean
}>()

const emit = defineEmits<{
  click: [stop: RouteStop]
}>()
</script>

<template>
  <button class="poi-card" :class="{ current: isCurrent }" type="button" @click="emit('click', stop)">
    <span class="sequence">{{ stop.sequence }}</span>
    <span class="content">
      <span class="title-row">
        <strong>{{ stop.poi_name }}</strong>
        <span class="category">{{ stop.category }}</span>
      </span>
      <span class="time-row">
        {{ stop.arrival_time }} - {{ stop.departure_time }}
      </span>
      <span class="meta-row">
        停留 {{ stop.visit_duration_min }} 分钟
        <template v-if="stop.queue_wait_min > 0"> · 预计排队 {{ stop.queue_wait_min }} 分钟</template>
      </span>
      <span v-if="stop.opening_hours_text" class="hours-row">营业时间：{{ stop.opening_hours_text }}</span>
      <span v-if="stop.slot_source === 'policy'" class="policy-row">根据全天行程自动加入</span>
    </span>
  </button>
</template>

<style scoped>
.poi-card {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 0.85rem;
  border: 1px solid #dcebe1;
  border-radius: 12px;
  margin-bottom: 0.6rem;
  background: #fff;
  color: inherit;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(38, 50, 44, .04);
  transition: border-color 0.2s, box-shadow 0.2s, transform .2s;
}
.poi-card:hover,
.poi-card.current {
  border-color: #238862;
  box-shadow: 0 4px 12px rgba(31, 112, 76, 0.11);
  transform: translateY(-1px);
}
.sequence {
  width: 1.75rem;
  height: 1.75rem;
  flex: 0 0 1.75rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: #def3e5;
  color: #147150;
  font-weight: 700;
}
.content {
  min-width: 0;
  display: grid;
  gap: 0.25rem;
}
.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}
.category {
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  background: #eff8f1;
  color: #4d7563;
  font-size: 0.78rem;
}
.time-row,
.meta-row {
  color: #6d8b7c;
  font-size: 0.88rem;
}
.hours-row {
  color: #8a6a31;
  font-size: 0.79rem;
  line-height: 1.45;
}
.policy-row {
  width: fit-content;
  padding: 0.12rem 0.48rem;
  border-radius: 999px;
  background: #eef4ff;
  color: #506c9c;
  font-size: 0.74rem;
}
</style>
