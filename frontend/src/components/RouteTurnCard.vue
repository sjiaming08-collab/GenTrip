<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { FeedbackRequest, RoutePlanResult, RouteStop, RouteTurnSnapshot } from '../types'
import FeedbackPanel from './FeedbackPanel.vue'
import RouteCanvas from './RouteCanvas.vue'

const props = defineProps<{
  snapshot: RouteTurnSnapshot
  isLatest?: boolean
  expanded: boolean
  selectedStopId?: string | null
}>()

const emit = defineEmits<{
  selectStop: [stop: RouteStop]
  submitFeedback: [feedback: FeedbackRequest]
  suggestion: [query: string]
  toggle: []
}>()

const selectedResult = ref<RoutePlanResult | null>(props.snapshot.route_results[0] ?? null)
const isDiff = computed(() => props.snapshot.reply_type === 'diff')
const isReject = computed(() => props.snapshot.reply_type === 'reject')
const summaryRoute = computed(() => props.snapshot.route_results[0]?.route)

watch(
  () => props.snapshot.snapshot_id,
  () => { selectedResult.value = props.snapshot.route_results[0] ?? null },
)
</script>

<template>
  <section class="route-turn-card" :class="{ historical: !isLatest, collapsed: !expanded }">
    <button
      class="snapshot-header"
      type="button"
      :aria-expanded="expanded"
      @click="emit('toggle')"
    >
      <span class="snapshot-label">
        <span>{{ isLatest ? '当前方案' : '历史方案' }}</span>
        <small>{{ snapshot.user_query || (isLatest ? '本轮生成结果' : '保留调整前结果') }}</small>
      </span>
      <span v-if="summaryRoute" class="snapshot-metrics">
        {{ summaryRoute.stops.length }} 站 · {{ summaryRoute.total_duration_min }} 分钟 · 人均 {{ summaryRoute.estimated_cost_per_person }} 元
        <em v-if="snapshot.diff_change_count">· 调整 {{ snapshot.diff_change_count }} 处</em>
      </span>
      <span class="snapshot-chevron">{{ expanded ? '收起' : '展开' }}</span>
    </button>

    <div v-if="expanded" class="snapshot-body">

      <div v-if="snapshot.degraded" class="degraded-notice">已按可执行性放宽部分条件，以下路线仍可直接出发。</div>

    <div v-if="snapshot.presentation" class="reply-summary">
      <p class="eyebrow">{{ isReject ? '路线助手' : '路线建议' }}</p>
      <h2>{{ snapshot.presentation.title }}</h2>
      <p>{{ snapshot.presentation.summary }}</p>
      <ul v-if="snapshot.presentation.highlights.length">
        <li v-for="item in snapshot.presentation.highlights" :key="item">{{ item }}</li>
      </ul>
    </div>

    <div v-if="isReject && snapshot.next_suggested_user_moves.length" class="suggestion-row">
      <button v-for="move in snapshot.next_suggested_user_moves" :key="move" type="button" @click="emit('suggestion', move)">{{ move }}</button>
    </div>

      <template v-if="!isReject">
      <div v-if="isDiff && snapshot.presentation" class="diff-strip">{{ snapshot.presentation.summary }}</div>

      <div v-if="snapshot.assumptions.length" class="assumption-strip">
        <strong>本次默认</strong>
        <span v-for="item in snapshot.assumptions" :key="`${item.slot}-${item.assumed_value}`">{{ item.message }}</span>
      </div>

      <div v-if="snapshot.route_results.length > 1" class="route-tabs" aria-label="备选路线">
        <button
          v-for="result in snapshot.route_results"
          :key="result.route.plan_id"
          type="button"
          :class="{ active: selectedResult?.route.plan_id === result.route.plan_id }"
          @click="selectedResult = result"
        >
          方案 {{ result.rank }} <span>{{ result.scores.final.toFixed(2) }}</span>
        </button>
      </div>

      <RouteCanvas :result="selectedResult" :selected-stop-id="selectedStopId" @select-stop="emit('selectStop', $event)" />
      <FeedbackPanel
        v-if="isLatest"
        :result="selectedResult"
        :session-id="snapshot.session_id"
        @submit-feedback="emit('submitFeedback', $event)"
      />
      </template>
    </div>
  </section>
</template>

<style scoped>
.route-turn-card{margin:8px 0 28px;padding:18px;border:1px solid #d5e1d8;border-radius:16px;background:#f9fbfa}.route-turn-card.historical{background:#f5f7f6;border-color:#dfe5e1}.route-turn-card.collapsed{padding:10px 14px}.snapshot-header{display:grid;grid-template-columns:minmax(150px,1fr) auto auto;gap:14px;align-items:center;width:100%;padding:0;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer}.snapshot-label{display:flex;align-items:center;gap:9px;min-width:0}.snapshot-label span{padding:4px 8px;border-radius:999px;background:#dff1e5;color:#176c4c;font-size:11px;font-weight:800;white-space:nowrap}.historical .snapshot-label span{background:#e8ece9;color:#65736c}.snapshot-label small{overflow:hidden;color:#819088;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.snapshot-metrics{color:#537265;font-size:12px;white-space:nowrap}.snapshot-metrics em{color:#2a8661;font-style:normal}.snapshot-chevron{color:#39765a;font-size:12px;font-weight:700}.snapshot-body{padding-top:16px}.reply-summary{padding:0 0 16px}.reply-summary h2{margin:0;font-family:"Microsoft YaHei","微软雅黑",sans-serif;font-size:24px}.reply-summary>p:not(.eyebrow){margin:8px 0 0;color:#537265;line-height:1.65}.reply-summary ul{display:grid;gap:7px;margin:13px 0 0;padding:0;list-style:none;color:#456556;font-size:14px}.reply-summary li::before{content:'•';margin-right:8px;color:#2a9567}.eyebrow{margin:0 0 6px;color:#4a9171;font-size:11px;font-weight:800}.assumption-strip{display:flex;flex-wrap:wrap;gap:7px;align-items:center;margin:14px 0;color:#547366;font-size:12px}.assumption-strip strong{margin-right:4px;color:#2b5946}.assumption-strip span{padding:5px 8px;border-radius:999px;background:#e9f6ed}.degraded-notice,.diff-strip{margin:0 0 14px;padding:10px 12px;border-radius:10px;font-size:13px}.degraded-notice{border:1px solid #f0dc9f;background:#fff8e8;color:#906b22}.diff-strip{background:#eef8f1;color:#317255}.suggestion-row,.route-tabs{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 15px}.suggestion-row button,.route-tabs button{padding:7px 10px;border:1px solid #cfded4;border-radius:10px;background:#fff;color:#35624e;cursor:pointer;font-size:13px}.suggestion-row button:hover,.route-tabs button.active{border-color:#16805a;background:#e9f7ed;color:#116b4a}.route-tabs button span{margin-left:5px;color:#6d8f7e;font-size:11px}@media(max-width:760px){.route-turn-card{padding:12px;margin-bottom:22px}.snapshot-header{grid-template-columns:1fr auto}.snapshot-metrics{grid-column:1/-1;white-space:normal}.reply-summary h2{font-size:21px}}
</style>
