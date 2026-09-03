<script setup lang="ts">
import { computed } from 'vue'
import type { RoutePlanResult, RouteStop } from '../types'
import PoiCard from './PoiCard.vue'
import TravelLegCard from './TravelLegCard.vue'

const props = defineProps<{
  result?: RoutePlanResult | null
  selectedStopId?: string | null
}>()

const emit = defineEmits<{
  selectStop: [stop: RouteStop]
}>()

const totals = computed(() => {
  const route = props.result?.route
  if (!route) return []
  const travel = route.stops.reduce((sum, stop) => sum + stop.travel_time_from_prev_min, 0)
  const queue = route.stops.reduce((sum, stop) => sum + stop.queue_wait_min, 0)
  return [
    { label: '总时长', value: `${route.total_duration_min} 分钟` },
    { label: '人均预算', value: `${route.estimated_cost_per_person} 元` },
    { label: '路上时间', value: `${travel} 分钟` },
    { label: '预计排队', value: `${queue} 分钟` },
  ]
})
</script>

<template>
  <section class="route-canvas" aria-label="路线方案">
    <div v-if="result" class="route-overview">
      <div class="route-title">
        <p>已生成方案</p>
        <h2>{{ result.route.plan_name }}</h2>
        <span>综合评分 {{ result.scores.final.toFixed(2) }}</span>
      </div>
      <dl class="route-totals">
        <div v-for="item in totals" :key="item.label">
          <dt>{{ item.label }}</dt>
          <dd>{{ item.value }}</dd>
        </div>
      </dl>
    </div>

    <div v-if="result" class="route-body">
      <section class="timeline-panel">
        <div class="panel-heading"><h3>行程时间线</h3><span>{{ result.route.stops.length }} 个地点</span></div>
        <p class="route-summary">{{ result.route.summary }}</p>
        <div class="stops-list">
          <template v-for="(stop, index) in result.route.stops" :key="`${result.route.plan_id}-${stop.sequence}`">
            <PoiCard
              :stop="stop"
              :is-current="selectedStopId === stop.poi_id"
              @click="emit('selectStop', stop)"
            />
            <TravelLegCard v-if="result.route.legs[index]" :leg="result.route.legs[index]" />
          </template>
        </div>
      </section>

      <aside class="route-inspector">
        <div class="panel-heading"><h3>路线概览</h3><span>按顺序出发</span></div>
        <ol class="route-strip">
          <li v-for="stop in result.route.stops" :key="stop.poi_id" :class="{ selected: selectedStopId === stop.poi_id }" @click="emit('selectStop', stop)">
            <span>{{ stop.sequence }}</span>
            <div><strong>{{ stop.poi_name }}</strong><small>{{ stop.category }} · {{ stop.arrival_time }}</small></div>
          </li>
        </ol>
        <p class="inspector-note">地点坐标可用后，此区域会显示真实地图与路线。</p>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.route-canvas{overflow:hidden;border:1px solid #d8e0db;border-radius:14px;background:#fff;box-shadow:0 8px 26px rgba(38,50,44,.06)}.route-overview{display:flex;align-items:end;justify-content:space-between;gap:24px;padding:24px 26px;border-bottom:1px solid #dde3df}.route-title p,.panel-heading span{margin:0;color:#6f7e77;font-size:12px}.route-title h2{margin:5px 0;color:#283831;font:700 24px/1.3 "Microsoft YaHei","微软雅黑",sans-serif}.route-title>span{color:#207854;font-size:13px;font-weight:700}.route-totals{display:grid;grid-template-columns:repeat(4,minmax(82px,1fr));gap:18px;margin:0}.route-totals div{min-width:0;padding:8px 10px;border-radius:9px;background:#f6f8f7}.route-totals dt{color:#7a8580;font-size:11px}.route-totals dd{margin:5px 0 0;color:#34443d;font-size:14px;font-weight:700;white-space:nowrap}.route-body{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(260px,.8fr)}.timeline-panel{padding:22px 24px}.route-inspector{padding:22px;border-left:1px solid #dde3df;background:#f4f7f9}.panel-heading{display:flex;justify-content:space-between;align-items:baseline;gap:12px}.panel-heading h3{margin:0;color:#30433a;font-size:14px}.route-summary{margin:8px 0 17px;color:#687870;font-size:13px;line-height:1.6}.stops-list{display:grid;gap:8px}.stops-list :deep(.poi-card){margin:0}.route-strip{display:grid;gap:0;margin:16px 0;padding:0;list-style:none}.route-strip li{position:relative;display:flex;gap:10px;padding:0 0 18px;cursor:pointer}.route-strip li:not(:last-child)::before{position:absolute;top:25px;bottom:0;left:10px;width:1px;background:#cbded2;content:""}.route-strip li>span{z-index:1;display:grid;width:21px;height:21px;place-items:center;border-radius:50%;background:#dcefe2;color:#156b4b;font-size:11px;font-weight:800}.route-strip li.selected>span{background:#176f50;color:#fff}.route-strip strong,.route-strip small{display:block}.route-strip strong{overflow:hidden;color:#34443d;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.route-strip small{margin-top:3px;color:#74817b;font-size:11px}.inspector-note{margin:5px 0 0;padding-top:14px;border-top:1px solid #dce3df;color:#75837d;font-size:12px;line-height:1.55}@media(max-width:780px){.route-overview{display:grid;padding:19px}.route-totals{grid-template-columns:repeat(2,1fr);gap:14px}.route-body{grid-template-columns:1fr}.timeline-panel{padding:19px}.route-inspector{padding:19px;border-top:1px solid #d8e3dc;border-left:0}}
</style>
