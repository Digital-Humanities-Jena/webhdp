<template>
  <div class="w-full min-w-0">
    <div v-if="showLabel" class="flex justify-between gap-3 mb-2 text-sm font-medium text-gray-700">
      <span class="break-words">{{ label }}</span>
      <span v-if="!isIndeterminate" class="shrink-0 tabular-nums">{{ value }}%</span>
    </div>
    <div
      role="progressbar"
      :aria-label="label || 'Progress'"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="isIndeterminate ? undefined : value"
      :aria-valuetext="isIndeterminate ? 'In progress' : undefined"
      class="w-full overflow-hidden bg-gray-200 rounded-full h-2.5"
    >
      <div
        class="h-full rounded-full motion-safe:transition-all motion-safe:duration-300"
        :class="[colorClass, { 'motion-safe:animate-pulse': isIndeterminate }]"
        :style="{ width: isIndeterminate ? '100%' : `${value}%` }"
      ></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  percentage: { type: Number, default: null },
  indeterminate: { type: Boolean, default: false },
  label: { type: String, default: '' },
  showLabel: { type: Boolean, default: true },
  color: { type: String, default: 'indigo' }
})

const isIndeterminate = computed(() => props.indeterminate || !Number.isFinite(props.percentage))
const value = computed(() => Math.round(Math.min(100, Math.max(0, props.percentage || 0))))
const colors = {
  indigo: 'bg-indigo-600', blue: 'bg-blue-600', green: 'bg-green-600',
  red: 'bg-red-600', yellow: 'bg-yellow-600', amber: 'bg-amber-600',
  emerald: 'bg-emerald-600', gray: 'bg-gray-600', purple: 'bg-purple-600'
}
const colorClass = computed(() => colors[props.color] || colors.indigo)
</script>
