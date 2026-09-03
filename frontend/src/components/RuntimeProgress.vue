<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { AlertCircle, Check, ChevronDown, ChevronUp, CircleDashed, CircleStop, LoaderCircle } from '@lucide/vue'
import type { SSEProgressEvent } from '../types'
import { nextPhase, presentPhase, presentStatus, stageOutcome } from '../utils/runtimePresentation'
import { normalizeRuntimeEvents, runtimeEventKey } from '../utils/runtimeEvents'
import RuntimePhaseIcon from './RuntimePhaseIcon.vue'

const props = defineProps<{
  events: SSEProgressEvent[]
  loading: boolean
  currentPhase: string
}>()

const emit = defineEmits<{ cancel: [] }>()
const expanded = ref(false)
const displayEvents = computed(() => normalizeRuntimeEvents(props.events))
const latest = computed(() => displayEvents.value[displayEvents.value.length - 1])
const completedCount = computed(() => displayEvents.value.filter((event) => ['completed', 'success'].includes(event.status || '')).length)
const activePhase = computed(() => props.loading
  ? nextPhase(latest.value) || latest.value?.phase || props.currentPhase
  : latest.value?.phase || props.currentPhase)
const activePresentation = computed(() => presentPhase(activePhase.value))
const timelineEvents = computed<SSEProgressEvent[]>(() => {
  if (!props.loading || !activePhase.value || latest.value?.phase === activePhase.value) return displayEvents.value
  return [...displayEvents.value, {
    phase: activePhase.value,
    status: 'running',
    summary: activePresentation.value.description,
    data: {},
  }]
})

function statusClass(event: SSEProgressEvent) {
  return event.status || 'running'
}

watch(() => props.loading, (loading) => { if (loading) expanded.value = false })
</script>

<template>
  <section class="runtime-progress" :class="{ complete: !loading && events.length, expanded }">
    <div class="runtime-main">
      <span class="active-icon" :class="{ running: loading }">
        <RuntimePhaseIcon :phase="activePhase" :size="18" />
      </span>

      <div class="active-copy">
        <div class="active-title-row">
          <strong>{{ loading ? activePresentation.title : '本轮规划已完成' }}</strong>
          <span class="run-state">
            <LoaderCircle v-if="loading" :size="12" class="spin" />
            <Check v-else :size="12" />
            {{ loading ? '正在处理' : '已完成' }}
          </span>
        </div>
        <p>{{ loading ? activePresentation.description : (latest ? stageOutcome(latest) : currentPhase) }}</p>
      </div>

      <span class="step-count">{{ completedCount }} 个步骤完成</span>
      <button type="button" class="details-button" :aria-expanded="expanded" @click="expanded = !expanded">
        {{ expanded ? '收起' : '查看过程' }}
        <ChevronUp v-if="expanded" :size="14" />
        <ChevronDown v-else :size="14" />
      </button>
      <button v-if="loading" type="button" class="cancel-button" title="取消规划" aria-label="取消规划" @click="emit('cancel')">
        <CircleStop :size="16" />
      </button>
    </div>

    <ol v-if="expanded && timelineEvents.length" class="event-list">
      <li
        v-for="(event, index) in timelineEvents"
        :key="runtimeEventKey(event, index)"
        :class="[statusClass(event), { current: loading && index === timelineEvents.length - 1 }]"
      >
        <span class="node-icon"><RuntimePhaseIcon :phase="event.phase" :size="16" /></span>
        <div class="node-copy">
          <div class="node-title">
            <strong>{{ presentPhase(event.phase).title }}</strong>
            <span class="node-status">
              <Check v-if="['completed', 'success'].includes(event.status || '')" :size="12" />
              <AlertCircle v-else-if="event.status === 'failed'" :size="12" />
              <LoaderCircle v-else-if="event.status === 'running'" :size="12" class="spin" />
              <CircleDashed v-else :size="12" />
              {{ presentStatus(event.status) }}
            </span>
          </div>
          <p>{{ event.status === 'running' ? presentPhase(event.phase).description : stageOutcome(event) }}</p>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.runtime-progress {
  --ink: #2f302d;
  --muted: #777873;
  --line: #deded8;
  --surface: #fbfbf9;
  --accent: #bd5d3a;
  --accent-soft: #f8ede8;
  --success: #3f7b62;
  margin: 18px 0;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  color: var(--ink);
  box-shadow: 0 1px 2px rgba(42, 39, 34, .04);
}
.runtime-main { display: flex; align-items: center; gap: 12px; min-height: 62px; padding: 11px 12px 11px 14px; }
.active-icon { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; border: 1px solid #d9d9d3; border-radius: 10px; background: #fff; color: #5f625d; }
.active-icon.running { border-color: #e4c4b7; background: var(--accent-soft); color: var(--accent); }
.active-copy { min-width: 0; flex: 1; }
.active-title-row { display: flex; align-items: center; gap: 8px; }
.active-copy strong { overflow: hidden; color: var(--ink); font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.active-copy p { overflow: hidden; margin: 4px 0 0; color: var(--muted); font-size: 12px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.run-state { display: inline-flex; align-items: center; gap: 4px; color: var(--accent); font-size: 10px; white-space: nowrap; }
.complete .run-state { color: var(--success); }
.step-count { color: #888983; font: 10px "Microsoft YaHei", "微软雅黑", sans-serif; white-space: nowrap; }
.details-button, .cancel-button { display: inline-flex; align-items: center; justify-content: center; border: 0; background: transparent; cursor: pointer; }
.details-button { gap: 4px; padding: 6px 4px; color: #5f625d; font-size: 11px; white-space: nowrap; }
.details-button:hover { color: var(--ink); }
.cancel-button { width: 30px; height: 30px; border-radius: 9px; color: #9a5b4a; }
.cancel-button:hover { background: #f5e9e5; color: #8c3f2e; }
.event-list { position: relative; display: grid; margin: 0; padding: 5px 14px 13px; border-top: 1px solid #e7e7e2; list-style: none; }
.event-list::before { position: absolute; top: 25px; bottom: 27px; left: 30px; width: 1px; background: var(--line); content: ""; }
.event-list li { position: relative; display: flex; gap: 12px; min-height: 48px; padding: 7px 0; }
.node-icon { z-index: 1; display: grid; width: 32px; height: 32px; flex: 0 0 auto; place-items: center; border: 1px solid #ddddD7; border-radius: 10px; background: var(--surface); color: #747670; }
.event-list li.completed .node-icon, .event-list li.success .node-icon { color: var(--success); }
.event-list li.failed .node-icon { border-color: #e4bcb5; color: #aa4e3f; }
.event-list li.current .node-icon { border-color: #dfb29f; background: var(--accent-soft); color: var(--accent); box-shadow: 0 0 0 3px rgba(189, 93, 58, .08); }
.node-copy { min-width: 0; flex: 1; padding-top: 1px; }
.node-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.node-title strong { color: #3b3c38; font-size: 12px; font-weight: 620; }
.node-status { display: inline-flex; align-items: center; gap: 4px; color: #8a8b85; font-size: 10px; white-space: nowrap; }
.completed .node-status, .success .node-status { color: var(--success); }
.failed .node-status { color: #a64b3d; }
.current .node-status { color: var(--accent); }
.node-copy p { margin: 4px 0 0; color: var(--muted); font-size: 11px; line-height: 1.45; }
.spin { animation: spin 1.1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
@media (max-width: 600px) {
  .runtime-main { align-items: flex-start; flex-wrap: wrap; }
  .active-copy { width: calc(100% - 48px); flex-basis: calc(100% - 48px); }
  .step-count { margin-left: 46px; }
  .details-button { margin-left: auto; }
  .event-list { padding-right: 12px; padding-left: 12px; }
  .event-list::before { left: 28px; }
}
</style>
