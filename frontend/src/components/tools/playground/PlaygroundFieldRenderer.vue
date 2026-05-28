<template>
  <article :class="containerClass">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div class="flex flex-wrap items-center gap-2">
          <component :is="compact ? 'label' : 'h4'" class="text-sm font-semibold text-slate-900">{{ field.label }}</component>
          <span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">{{ field.type }}</span>
          <span v-if="field.required" class="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">Required</span>
        </div>
        <p v-if="field.description" :class="compact ? 'mt-1 text-xs text-slate-500' : 'mt-1 text-sm text-slate-500'">{{ field.description }}</p>
        <p v-if="field.help_text" :class="compact ? 'mt-2 text-[11px] text-indigo-600' : 'mt-2 text-xs text-indigo-600'">{{ field.help_text }}</p>
      </div>
    </div>

    <div class="mt-3">
      <component
        :is="widgetComponent"
        :field="field"
        :model-value="modelValue"
        :session-id="sessionId"
        :suggested-files="suggestedFiles"
        :suggested-directories="suggestedDirectories"
        @update:model-value="$emit('update:modelValue', $event)"
      />
    </div>

    <p v-if="error" :class="compact ? 'mt-2 text-xs text-rose-600' : 'mt-3 text-xs text-rose-600'">{{ error }}</p>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import PlaygroundFileListFieldWidget from './PlaygroundFileListFieldWidget.vue'
import PlaygroundPathFieldWidget from './PlaygroundPathFieldWidget.vue'
import PlaygroundScalarFieldWidget from './PlaygroundScalarFieldWidget.vue'

const props = defineProps({
  field: {
    type: Object,
    required: true
  },
  modelValue: {
    type: [String, Number, Boolean],
    default: ''
  },
  error: {
    type: String,
    default: ''
  },
  sessionId: {
    type: [String, Number],
    default: ''
  },
  suggestedFiles: {
    type: Array,
    default: () => []
  },
  suggestedDirectories: {
    type: Array,
    default: () => []
  },
  compact: {
    type: Boolean,
    default: false
  }
})

defineEmits(['update:modelValue'])

const widgetComponentRegistry = {
  file_picker: PlaygroundPathFieldWidget,
  directory_picker: PlaygroundPathFieldWidget,
  image_input: PlaygroundPathFieldWidget,
  model_input: PlaygroundPathFieldWidget,
  file_list_picker: PlaygroundFileListFieldWidget
}

const widgetComponent = computed(() => widgetComponentRegistry[props.field?.widget] || PlaygroundScalarFieldWidget)
const containerClass = computed(() => (
  props.compact
    ? 'rounded-xl border border-slate-200 bg-slate-50 px-4 py-3'
    : 'rounded-2xl border border-slate-200 bg-white px-4 py-4'
))
</script>
