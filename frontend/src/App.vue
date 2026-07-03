<script setup lang="ts">
import RoutePlanner from './components/RoutePlanner.vue'
import ItineraryTimeline from './components/ItineraryTimeline.vue'
import MapView from './components/MapView.vue'
import FeedbackPanel from './components/FeedbackPanel.vue'

// TODO: 实现状态管理
// const currentRoute = ref<RoutePlanResponse | null>(null)
// const phase = ref<string>('idle')
</script>

<template>
  <div class="app-container">
    <header class="app-header">
      <h1>DeoReview</h1>
      <p class="subtitle">智能路线规划</p>
    </header>

    <main class="app-main">
      <!-- 查询输入区 -->
      <RoutePlanner />

      <!-- 路线结果: 时间线 + 地图 -->
      <div class="result-layout">
        <ItineraryTimeline />
        <MapView />
      </div>

      <!-- 反馈面板 (路线完成后显示) -->
      <FeedbackPanel />
    </main>
  </div>
</template>

<style scoped>
.app-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 1rem;
}
.app-header {
  text-align: center;
  margin-bottom: 2rem;
}
.subtitle {
  color: #666;
  font-size: 0.9rem;
}
.result-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-top: 1.5rem;
}
</style>
