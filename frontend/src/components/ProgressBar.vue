<script setup lang="ts">
defineProps<{
  currentPhase: string
  phases: string[]
}>()

defineEmits<{
  cancel: []
}>()

const PHASE_LABELS: Record<string, string> = {
  turn_orchestrate: '正在理解需求...',
  constraint_extract: '正在分析出行偏好...',
  geo_resolve: '正在定位目标区域...',
  activity_blueprint: '正在构思活动蓝图...',
  poi_retrieve: '正在为您挑选好去处...',
  route_generate: '正在生成候选路线...',
  route_validate: '正在检查可行性...',
  auto_relax: '正在放宽条件重新搜索...',
  route_evaluate: '正在评估最优方案...',
  route_present: '正在为您呈现推荐...',
  replan_parse: '正在理解修订需求...',
  reject_reply: '',
}

function label(phase: string): string {
  return PHASE_LABELS[phase] || phase
}
</script>

<template>
  <div class="progress-bar">
    <div class="phases">
      <span
        v-for="(phase, idx) in phases"
        :key="phase"
        class="phase-dot"
        :class="{
          active: phase === currentPhase,
          done: phases.indexOf(currentPhase) > idx,
        }"
      >
        <span class="dot" />
        <span class="phase-label">{{ label(phase) }}</span>
      </span>
    </div>
    <button v-if="currentPhase && currentPhase !== 'complete'" class="cancel-btn" @click="$emit('cancel')">
      取消
    </button>
  </div>
</template>

<style scoped>
.progress-bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.4rem 0;
  border-radius: 0;
  background: transparent;
  border: 0;
}
.phases {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.phase-dot {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.8rem;
  color: #97aa9e;
}
.phase-dot .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d8e7dc;
}
.phase-dot.active {
  color: #167b59;
  font-weight: 600;
}
.phase-dot.active .dot {
  background: #218a64;
  box-shadow: 0 0 0 3px rgba(33, 138, 100, 0.18);
}
.phase-dot.done {
  color: #27815e;
}
.phase-dot.done .dot {
  background: #42a97d;
}
.cancel-btn {
  flex-shrink: 0;
  padding: 0.3rem 0.6rem;
  border: 1px solid #bcdcc7;
  border-radius: 6px;
  background: #fff;
  font-size: 0.8rem;
  cursor: pointer;
}
</style>
