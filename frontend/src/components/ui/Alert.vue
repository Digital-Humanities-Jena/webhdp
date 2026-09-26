<template>
  <div
    v-if="modelValue"
    :class="[
      'px-4 py-3 rounded relative border',
      variantClasses[variant]
    ]"
    role="alert"
  >
    <div class="flex items-start">
      <div class="flex-shrink-0">
        <component :is="iconComponent" class="h-5 w-5" />
      </div>
      <div class="ml-3 flex-1">
        <p v-if="title" class="font-medium">{{ title }}</p>
        <p class="text-sm" :class="{ 'mt-1': title }">
          <slot>{{ message }}</slot>
        </p>
      </div>
      <button
        v-if="dismissible"
        @click="$emit('update:modelValue', false)"
        aria-label="Dismiss alert"
        class="ml-3 flex-shrink-0"
      >
        <svg class="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: Boolean,
  variant: {
    type: String,
    default: 'info',
    validator: (value) => ['success', 'error', 'warning', 'info'].includes(value)
  },
  title: String,
  message: String,
  dismissible: {
    type: Boolean,
    default: true
  }
})

defineEmits(['update:modelValue'])

const variantClasses = {
  success: 'bg-green-50 border-green-400 text-green-700',
  error: 'bg-red-50 border-red-400 text-red-700',
  warning: 'bg-yellow-50 border-yellow-400 text-yellow-700',
  info: 'bg-blue-50 border-blue-400 text-blue-700'
}

const iconComponent = computed(() => {
  const icons = {
    success: 'CheckCircleIcon',
    error: 'XCircleIcon',
    warning: 'ExclamationIcon',
    info: 'InformationCircleIcon'
  }
  return icons[props.variant]
})
</script>
