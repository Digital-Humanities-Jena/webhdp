<template>
  <div class="flex justify-center items-center" :class="containerClass">
    <div
      :class="[
        'animate-spin rounded-full border-b-2',
        sizeClasses[size],
        colorClass
      ]"
    ></div>
    <span v-if="text" class="ml-3 text-gray-600">{{ text }}</span>
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

const colorClass = computed(() => `border-${props.color}-600`)
</script>
