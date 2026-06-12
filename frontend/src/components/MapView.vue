<script setup lang="ts">
import type { ItineraryStop, GeoPoint } from '../types'

// ============================================================
// Props (组件接口)
// ============================================================
defineProps<{
  stops?: ItineraryStop[]
  center?: GeoPoint
  zoom?: number
}>()

// ============================================================
// Events
// ============================================================
const emit = defineEmits<{
  selectPoi: [poiId: string]
}>()
</script>

<template>
  <div class="map-container">
    <div class="map-placeholder">
      <!-- TODO: 集成高德地图 -->
      <!-- 1. 加载 @amap/amap-jsapi-loader -->
      <!-- 2. 初始化地图实例 -->
      <!-- 3. 渲染 stops 为 Marker -->
      <!-- 4. 绘制路线 Polyline -->
      <p>地图加载中...</p>
      <p class="hint">需要高德地图 JS API Key</p>
    </div>
  </div>
</template>

<style scoped>
.map-container {
  width: 100%;
  height: 400px;
  border: 1px solid #eee;
  border-radius: 8px;
  overflow: hidden;
}
.map-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #f8f8f8;
  color: #999;
}
.hint {
  font-size: 0.8rem;
  margin-top: 0.25rem;
}
</style>
