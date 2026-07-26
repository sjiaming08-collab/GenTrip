<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { SSEProgressEvent } from '../types'
import { nextPhase, presentPhase, presentStatus, stageOutcome } from '../utils/runtimePresentation'

const props = defineProps<{
  events: SSEProgressEvent[]
  loading: boolean
  currentPhase: string
}>()

const emit = defineEmits<{ cancel: [] }>()
const expanded = ref(false)
const latest = computed(() => props.events[props.events.length - 1])
const completedCount = computed(() => props.events.filter((event) => ['completed', 'success'].includes(event.status || '')).length)
const activePhase = computed(() => props.loading ? nextPhase(latest.value) || latest.value?.phase || props.currentPhase : latest.value?.phase || props.currentPhase)
const activePresentation = computed(() => presentPhase(activePhase.value))

watch(() => props.loading, (loading) => { if (loading) expanded.value = false })
</script>

<template>
  <section class="runtime-progress" :class="{ complete: !loading && events.length }">
    <div class="runtime-main">
      <span class="run-pulse" :class="{ active: loading }" />
      <div><strong>{{ loading ? activePresentation.title : '本轮规划已完成' }}</strong><p>{{ loading ? activePresentation.description : (latest ? stageOutcome(latest) : currentPhase) }}</p></div>
      <span class="step-count">{{ completedCount }}/{{ events.length || 1 }} steps</span>
      <button type="button" class="details-button" @click="expanded = !expanded">{{ expanded ? '收起过程' : '查看过程' }}</button>
      <button v-if="loading" type="button" class="cancel-button" @click="emit('cancel')">取消</button>
    </div>
    <ol v-if="expanded && events.length" class="event-list">
      <li v-for="(event, index) in events" :key="`${event.event_id || event.phase}-${index}`">
        <span :class="event.status || 'running'" /><div><strong>{{ presentPhase(event.phase).title }} · {{ presentStatus(event.status) }}</strong><p>{{ stageOutcome(event) }}</p></div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.runtime-progress{margin:18px 0;border:1px solid #d4e4d9;background:#f8fcf9}.runtime-main{display:flex;align-items:center;gap:11px;padding:13px 15px}.run-pulse{width:9px;height:9px;flex:0 0 auto;border-radius:50%;background:#4da27a}.run-pulse.active{background:#d58b35;box-shadow:0 0 0 5px #f7ead8;animation:pulse 1.5s infinite}.runtime-main>div{min-width:0;flex:1}.runtime-main strong{display:block;color:#244b3b;font-size:13px}.runtime-main p{overflow:hidden;margin:3px 0 0;color:#708a7e;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.step-count{color:#6f8b7e;font:11px ui-monospace,SFMono-Regular,monospace;white-space:nowrap}.details-button,.cancel-button{border:0;background:transparent;color:#247353;font-size:12px;cursor:pointer;white-space:nowrap}.cancel-button{padding:5px 8px;border:1px solid #cbdbd0;color:#7c483e}.event-list{display:grid;gap:0;margin:0;padding:0 15px 14px;list-style:none}.event-list li{display:flex;gap:9px;padding:8px 0;border-top:1px solid #e3eee7}.event-list li>span{width:7px;height:7px;flex:0 0 auto;margin-top:5px;border-radius:50%;background:#9aafa3}.event-list li>span.completed,.event-list li>span.success{background:#319467}.event-list li>span.failed{background:#c75b50}.event-list strong{color:#416858;font:700 11px ui-monospace,SFMono-Regular,monospace}.event-list p{margin:3px 0 0;color:#748c81;font-size:12px}@keyframes pulse{50%{box-shadow:0 0 0 8px transparent}}@media(max-width:600px){.runtime-main{flex-wrap:wrap}.step-count{margin-left:20px}.details-button{margin-left:auto}}
</style>
