<script setup lang="ts">
import type { RoutePlanResult, RouteStop } from '../types'
import PoiCard from './PoiCard.vue'

defineProps<{
  result?: RoutePlanResult | null
  currentStopIndex?: number
}>()

const emit = defineEmits<{
  selectStop: [stop: RouteStop]
}>()
</script>

<template>
  <section class="itinerary-timeline">
    <div class="header-row">
      <div>
        <h3>路线时间线</h3>
        <p v-if="result" class="summary">{{ result.route.summary }}</p>
      </div>
      <span v-if="result" class="score">评分 {{ result.scores.final.toFixed(3) }}</span>
    </div>

    <div v-if="!result" class="empty-state">
      输入需求开始规划路线
    </div>
    <div v-else class="stops-list">
      <PoiCard
        v-for="(stop, index) in result.route.stops"
        :key="`${result.route.plan_id}-${stop.sequence}`"
        :stop="stop"
        :is-current="index === currentStopIndex"
        @click="emit('selectStop', stop)"
      />
    </div>
  </section>
</template>

<style scoped>
.itinerary-timeline {
  padding: 1rem;
  border: 1px solid #d9ebdf;
  border-radius: 8px;
  background: #fff;
}
.header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}
h3 {
  margin: 0;
}
.summary {
  margin: 0.25rem 0 0;
  color: #6b8678;
  font-size: 0.9rem;
}
.score {
  flex: 0 0 auto;
  color: #167b59;
  font-weight: 700;
  font-size: 0.9rem;
}
.empty-state {
  color: #87a093;
  text-align: center;
  padding: 3rem 0;
}
</style>
