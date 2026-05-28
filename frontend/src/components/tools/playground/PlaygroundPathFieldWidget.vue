<template>
  <div class="space-y-3">
    <SessionPathPicker
      v-if="suggestions.length > 0"
      :title="sessionPickerTitle"
      :description="`Filter available session ${pathSourceLabel} and apply one to this field.`"
      :items="suggestions"
      :selected-item="String(modelValue || '')"
      :item-label="pathSourceLabel"
      selection-mode="single"
      item-action-label="Use"
      selected-action-label="Selected"
      :search-placeholder="`Filter session ${pathSourceLabel}`"
      :data-testid-prefix="`session-path-${field.name}`"
      @select="applySuggestedValue"
    />

    <input
      :value="modelValue"
      type="text"
      class="block w-full rounded-xl border-slate-300 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
      :placeholder="field.placeholder || '/absolute/path'"
      @input="$emit('update:modelValue', $event.target.value)"
    >

    <div v-if="previewError" class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
      {{ previewError }}
    </div>

    <div v-else-if="previewUrl && isImagePreview" class="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50">
      <img :src="previewUrl" :alt="field.label" class="max-h-56 w-full object-contain bg-white">
    </div>

    <PlaygroundModelViewer
      v-else-if="previewUrl && wantsModelPreview && isModelPreviewable"
      :src="previewUrl"
      :alt="field.label"
    />

    <div v-else-if="hasModelValue && wantsModelPreview" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
      <div class="font-medium text-slate-900">3D Input Selected</div>
      <div class="mt-1 break-all">{{ modelValue }}</div>
      <div class="mt-2 text-xs text-slate-500">
        {{ isModelPreviewable ? 'Inline preview is available for session-backed GLB and GLTF files. If loading fails, the run and download actions remain available.' : 'This model format falls back to run/download actions because inline rendering is not practical here.' }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import SessionPathPicker from '@/components/ui/SessionPathPicker.vue'
import PlaygroundModelViewer from './PlaygroundModelViewer.vue'
import pipelineService from '@/services/pipeline.service'
import { filterSessionPathsForField } from '@/utils/playgroundManifest'
import { canInlinePreviewModel, isImageExtension } from '@/utils/playgroundResults'

const props = defineProps({
  field: {
    type: Object,
    required: true
  },
  modelValue: {
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
  }
})

const emit = defineEmits(['update:modelValue'])

const previewUrl = ref('')
const previewError = ref('')

const suggestions = computed(() => {
  if (props.field?.path_source === 'directories') {
    return props.suggestedDirectories
  }
  return filterSessionPathsForField(props.field, props.suggestedFiles)
})

const pathSourceLabel = computed(() => props.field?.path_source === 'directories' ? 'directories' : 'files')
const sessionPickerTitle = computed(() => props.field?.path_source === 'directories' ? 'Session Directories' : 'Session Files')
const hasModelValue = computed(() => String(props.modelValue || '').trim().length > 0)
const wantsImagePreview = computed(() => props.field?.preview_kind === 'image' || props.field?.widget === 'image_input')
const wantsModelPreview = computed(() => props.field?.preview_kind === 'model' || props.field?.widget === 'model_input')
const isImagePreview = computed(() => wantsImagePreview.value && isImageExtension(props.modelValue))
const isModelPreviewable = computed(() => wantsModelPreview.value && canInlinePreviewModel(props.modelValue))

function revokePreview() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
}

function applySuggestedValue(value) {
  if (!value) {
    return
  }
  emit('update:modelValue', value)
}

async function loadPreview() {
  revokePreview()
  previewError.value = ''
  if (!wantsImagePreview.value && !isModelPreviewable.value) {
    return
  }
  const normalizedSessionId = Number.parseInt(props.sessionId, 10)
  const normalizedPath = String(props.modelValue || '').trim()
  const canLoadImage = wantsImagePreview.value && isImageExtension(normalizedPath)
  if (!Number.isInteger(normalizedSessionId) || normalizedSessionId <= 0 || !normalizedPath || (!canLoadImage && !isModelPreviewable.value)) {
    return
  }

  try {
    const blob = await pipelineService.getPlaygroundSessionFile(normalizedSessionId, normalizedPath, { suppressGlobalError: true })
    previewUrl.value = URL.createObjectURL(blob)
  } catch {
    previewError.value = 'Preview unavailable for the selected session file.'
  }
}

watch(
  () => [props.sessionId, props.modelValue, props.field?.widget, props.field?.preview_kind],
  () => {
    void loadPreview()
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  revokePreview()
})
</script>
