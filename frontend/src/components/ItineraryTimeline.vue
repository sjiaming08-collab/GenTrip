<script setup lang="ts">
import type { ItineraryStop, RoutePlanResponse } from '../types'
import PoiCard from './PoiCard.vue'

// ============================================================
// Props (组件接口)
// ============================================================
defineProps<{
  route?: RoutePlanResponse | null
  currentStopIndex?: number
}>()

// ============================================================
// Events
// ============================================================
const emit = defineEmits<{
  selectStop: [stop: ItineraryStop]
}>()
</script>

<template>
  <div class="itinerary-timeline">
    <h3>路线时间线</h3>
    <div v-if="!route" class="empty-state">
      输入需求开始规划路线
    </div>
    <div v-else class="stops-list">
      <!-- TODO: 实现 stop 列表渲染 -->
      <!-- <PoiCard
        v-for="stop in route.stops"
        :key="stop.sequence"
        :stop="stop"
        @click="emit('selectStop', stop)"
      /> -->
    </div>
  </div>
</template>

<style scoped>
.itinerary-timeline {
  padding: 1rem;
  border: 1px solid #eee;
  border-radius: 8px;
}
.empty-state {
  color: #999;
  text-align: center;
  padding: 3rem 0;
}
</style>
