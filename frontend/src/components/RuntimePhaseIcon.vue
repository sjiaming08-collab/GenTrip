<script setup lang="ts">
import { computed } from 'vue'
import {
  BrainCircuit,
  Check,
  Database,
  FileText,
  MapPin,
  Route,
  Search,
  ShieldCheck,
  Sparkles,
} from '@lucide/vue'

const props = withDefaults(defineProps<{
  phase: string
  size?: number
}>(), {
  size: 16,
})

const icon = computed(() => {
  const phase = props.phase
  if (phase === 'complete') return Check
  if (['turn_orchestrate', 'constraint_extract', 'replan_parse'].includes(phase)) return BrainCircuit
  if (['constraint_compile', 'planning_decision', 'route_validate', 'validate_delta', 'failure_directed_repair'].includes(phase)) return ShieldCheck
  if (['geo_resolve'].includes(phase)) return MapPin
  if (['activity_blueprint', 'blueprint_compile'].includes(phase)) return Sparkles
  if (['poi_retrieve', 'partial_retrieval'].includes(phase)) return Search
  if (['route_generate', 'local_optimize', 'route_evaluate'].includes(phase)) return Route
  if (['route_bundle_search', 'route_bundle_ingest', 'dialog_summary'].includes(phase)) return Database
  if (['route_present', 'render_diff'].includes(phase)) return FileText
  return Sparkles
})
</script>

<template>
  <component :is="icon" :size="size" :stroke-width="1.8" aria-hidden="true" />
</template>
