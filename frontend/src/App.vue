<script setup lang="ts">
import { computed, ref } from 'vue'
import RoutePlanner from './components/RoutePlanner.vue'
import ItineraryTimeline from './components/ItineraryTimeline.vue'
import MapView from './components/MapView.vue'
import FeedbackPanel from './components/FeedbackPanel.vue'
import { submitFeedback as saveFeedback } from './api'
import { useRoutePlan } from './composables/useRoutePlan'
import type { FeedbackRequest, RoutePlanRequest, RoutePlanResult, RouteStop } from './types'

const {
  loading,
  currentRoute,
  selectedResult,
  routeResults,
  presentation,
  error,
  submitQuery,
  selectResult,
} = useRoutePlan()

const selectedStop = ref<RouteStop | null>(null)

const selectedStopIndex = computed(() => {
  if (!selectedStop.value || !selectedResult.value) return -1
  return selectedResult.value.route.stops.findIndex((stop) => stop.poi_id === selectedStop.value?.poi_id)
})

function handleSubmit(request: RoutePlanRequest) {
  selectedStop.value = null
  submitQuery(request)
}

function handleSelectResult(result: RoutePlanResult) {
  selectedStop.value = null
  selectResult(result)
}

function handleSelectStop(stop: RouteStop) {
  selectedStop.value = stop
}

function handleSelectPoi(poiId: string) {
  const stop = selectedResult.value?.route.stops.find((item) => item.poi_id === poiId)
  if (stop) selectedStop.value = stop
}

async function handleFeedback(feedback: FeedbackRequest) {
  await saveFeedback(feedback.route_id, feedback)
}
</script>

<template>
  <div class="app-container">
    <header class="app-header">
      <h1>GenTrip</h1>
      <p class="subtitle">智能路线规划</p>
    </header>

    <main class="app-main">
      <RoutePlanner :is-loading="loading" @submit="handleSubmit" />

      <p v-if="error" class="error-state">{{ error }}</p>
      <p v-else-if="loading" class="loading-state">正在规划路线...</p>

      <section v-if="presentation" class="presentation">
        <h2>{{ presentation.title }}</h2>
        <p>{{ presentation.summary }}</p>
        <ul>
          <li v-for="item in presentation.highlights" :key="item">{{ item }}</li>
        </ul>
      </section>

      <section v-if="currentRoute?.assumptions.length" class="assumptions">
        <strong>系统假设</strong>
        <ul>
          <li v-for="item in currentRoute.assumptions" :key="`${item.slot}-${item.assumed_value}`">
            {{ item.message }}
          </li>
        </ul>
      </section>

      <section v-if="routeResults.length > 1" class="route-tabs" aria-label="备选路线">
        <button
          v-for="result in routeResults"
          :key="result.route.plan_id"
          type="button"
          :class="{ active: selectedResult?.route.plan_id === result.route.plan_id }"
          @click="handleSelectResult(result)"
        >
          路线 {{ result.rank }} · {{ result.scores.final.toFixed(3) }}
        </button>
      </section>

      <div class="result-layout">
        <ItineraryTimeline
          :result="selectedResult"
          :current-stop-index="selectedStopIndex"
          @select-stop="handleSelectStop"
        />
        <MapView
          :stops="selectedResult?.route.stops"
          :selected-stop-id="selectedStop?.poi_id ?? null"
          @select-poi="handleSelectPoi"
        />
      </div>

      <FeedbackPanel :result="selectedResult" @submit-feedback="handleFeedback" />
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
.app-header h1 {
  margin-bottom: 0.25rem;
}
.subtitle {
  color: #666;
  font-size: 0.9rem;
}
.loading-state,
.error-state,
.presentation,
.assumptions {
  margin-top: 1rem;
  padding: 1rem;
  border-radius: 8px;
}
.loading-state {
  background: #eff6ff;
  color: #1d4ed8;
}
.error-state {
  background: #fef2f2;
  color: #b91c1c;
}
.presentation,
.assumptions {
  border: 1px solid #e5e7eb;
  background: #fff;
}
.presentation h2 {
  margin: 0 0 0.5rem;
}
.presentation p {
  margin: 0 0 0.75rem;
  color: #4b5563;
}
.presentation ul,
.assumptions ul {
  margin: 0;
  padding-left: 1.2rem;
  color: #4b5563;
}
.route-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 1rem;
}
.route-tabs button {
  padding: 0.45rem 0.8rem;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
}
.route-tabs button.active {
  border-color: #2563eb;
  background: #eff6ff;
  color: #1d4ed8;
}
.result-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.9fr);
  gap: 1rem;
  margin-top: 1.5rem;
}
@media (max-width: 820px) {
  .result-layout {
    grid-template-columns: 1fr;
  }
}
</style>