<template>
  <label v-if="widget === 'checkbox'" class="flex items-center gap-3 text-sm text-slate-700">
    <input
      :checked="Boolean(modelValue)"
      type="checkbox"
      class="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
      @change="$emit('update:modelValue', $event.target.checked)"
    >
    <span>{{ checkboxLabel }}</span>
  </label>

  <select
    v-else-if="widget === 'select'"
    :value="modelValue"
    class="block w-full rounded-xl border-slate-300 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
    @change="$emit('update:modelValue', $event.target.value)"
  >
    <option value="">Select an option</option>
    <option v-for="option in field.options || []" :key="option" :value="option">{{ option }}</option>
  </select>

  <input
    v-else-if="widget === 'number_input'"
    :value="modelValue"
    type="number"
    class="block w-full rounded-xl border-slate-300 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
    :placeholder="field.placeholder || ''"
    @input="$emit('update:modelValue', $event.target.value)"
  >

  <textarea
    v-else-if="widget === 'textarea' || widget === 'json_editor' || widget === 'array_editor'"
    :value="modelValue"
    :rows="textareaRows"
    class="block w-full rounded-xl border-slate-300 font-mono text-xs text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
    :placeholder="textareaPlaceholder"
    @input="$emit('update:modelValue', $event.target.value)"
  />

  <input
    v-else
    :value="modelValue"
    type="text"
    class="block w-full rounded-xl border-slate-300 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
    :placeholder="field.placeholder || ''"
    @input="$emit('update:modelValue', $event.target.value)"
  >
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  field: {
    type: Object,
    required: true
  },
  modelValue: {
    type: [String, Number, Boolean],
    default: ''
  }
})

defineEmits(['update:modelValue'])

const widget = computed(() => String(props.field?.widget || 'text_input'))
const checkboxLabel = computed(() => props.field?.help_text || props.field?.label || 'Enabled')
const textareaRows = computed(() => props.field?.rows || (widget.value === 'array_editor' ? 5 : 6))
const textareaPlaceholder = computed(() => {
  if (widget.value === 'json_editor') {
    return props.field?.placeholder || '{ }'
  }
  if (widget.value === 'array_editor') {
    return props.field?.placeholder || 'One value per line'
  }
  return props.field?.placeholder || ''
})
</script>
