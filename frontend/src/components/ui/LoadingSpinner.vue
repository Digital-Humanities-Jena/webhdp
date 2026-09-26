<template>
  <div class="flex justify-center items-center" :class="containerClass" role="status">
    <div
      aria-hidden="true"
      :class="[
        'motion-safe:animate-spin rounded-full border-b-2',
        sizeClasses[size],
        colorClass
      ]"
    ></div>
    <span :class="text ? 'ml-3 text-gray-600' : 'sr-only'">{{ text || 'Loading…' }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  size: {
    type: String,
    default: 'md',
    validator: (value) => ['sm', 'md', 'lg', 'xl'].includes(value)
  },
  color: {
    type: String,
    default: 'indigo'
  },
  text: {
    type: String,
    default: ''
  },
  containerClass: {
    type: String,
    default: ''
  }
})

const sizeClasses = {
  sm: 'h-4 w-4',
  md: 'h-8 w-8',
  lg: 'h-12 w-12',
  xl: 'h-16 w-16'
}

const colors = { indigo: 'border-indigo-600', blue: 'border-blue-600', green: 'border-green-600', red: 'border-red-600', gray: 'border-gray-600' }
const colorClass = computed(() => colors[props.color] || colors.indigo)
</script>
