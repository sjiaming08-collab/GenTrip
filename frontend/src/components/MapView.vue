<script setup lang="ts">
import type { RouteStop } from '../types'

defineProps<{
  stops?: RouteStop[]
  selectedStopId?: string | null
}>()

const emit = defineEmits<{
  selectPoi: [poiId: string]
}>()
</script>

<template>
  <section class="map-container">
    <div class="map-placeholder">
      <div class="map-header">
        <h3>路线概览</h3>
        <p>当前后端未返回 POI 经纬度，先展示站点顺序；后续可接高德地图 Marker。</p>
      </div>

      <ol v-if="stops?.length" class="route-list">
        <li
          v-for="stop in stops"
          :key="stop.poi_id"
          :class="{ selected: selectedStopId === stop.poi_id }"
          @click="emit('selectPoi', stop.poi_id)"
        >
          <span>{{ stop.sequence }}</span>
          <strong>{{ stop.poi_name }}</strong>
          <small>{{ stop.category }}</small>
        </li>
      </ol>
      <p v-else class="hint">规划完成后显示站点顺序</p>
    </div>
  </section>
</template>

<style scoped>
.map-container {
  min-height: 400px;
  border: 1px solid #d9ebdf;
  border-radius: 8px;
  overflow: hidden;
  background: #f4fbf6;
}
.map-placeholder {
  height: 100%;
  padding: 1rem;
  color: #315444;
}
.map-header h3 {
  margin: 0;
}
.map-header p,
.hint {
  color: #718c7e;
  font-size: 0.9rem;
}
.route-list {
  list-style: none;
  display: grid;
  gap: 0.6rem;
  padding: 0;
  margin: 1rem 0 0;
}
.route-list li {
  display: grid;
  grid-template-columns: 1.5rem 1fr auto;
  align-items: center;
  gap: 0.6rem;
  padding: 0.7rem;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #dcebe1;
  cursor: pointer;
}
.route-list li.selected {
  border-color: #19805d;
  background: #e9f7ed;
}
.route-list span {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 999px;
  background: #d9f0e1;
  color: #13704f;
  font-weight: 700;
}
.route-list small {
  color: #719082;
}
</style>
