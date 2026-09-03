<script setup lang="ts">
import { Bike, BusFront, Car, Footprints } from '@lucide/vue'
import type { RouteLeg } from '../types'

defineProps<{ leg: RouteLeg }>()

const labels = {
  walking: '步行',
  cycling: '骑行',
  transit: '公交',
  driving: '驾车',
}

const icons = {
  walking: Footprints,
  cycling: Bike,
  transit: BusFront,
  driving: Car,
}

function distanceLabel(distance: number) {
  return distance >= 1000 ? `${(distance / 1000).toFixed(1)} km` : `${distance} m`
}
</script>

<template>
  <div class="travel-leg" :title="leg.selection_reason">
    <span class="line" />
    <span class="mode-icon"><component :is="icons[leg.mode]" :size="15" /></span>
    <strong>{{ labels[leg.mode] }}</strong>
    <span>{{ distanceLabel(leg.distance_m) }} · {{ leg.duration_min }} 分钟</span>
    <span class="source">{{ leg.source }}</span>
    <span v-if="leg.estimated" class="estimated">估算</span>
  </div>
</template>

<style scoped>
.travel-leg{position:relative;display:flex;align-items:center;gap:7px;min-height:30px;margin:-1px 0;padding:4px 12px 4px 47px;color:#65776f;font-size:12px}.line{position:absolute;top:0;bottom:0;left:25px;width:1px;background:#c9ddd1}.mode-icon{z-index:1;display:grid;width:24px;height:24px;place-items:center;border:1px solid #cfe0d6;border-radius:50%;background:#f5faf7;color:#277457}.travel-leg strong{color:#3d5c4d}.source{color:#82928a}.estimated{padding:1px 5px;border-radius:999px;background:#fff0d7;color:#95641f;font-size:10px}
</style>
