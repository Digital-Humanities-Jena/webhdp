<template>
  <div class="overflow-hidden border border-slate-200 bg-slate-100">
    <PlaygroundModelViewer
      v-if="previewLoaded && canPreview"
      :src="record.model_preview.url"
      :alt="record.title || record.model_preview.filename || '3D model preview'"
    />

    <div
      v-else
      class="flex aspect-[4/3] flex-col items-center justify-center bg-slate-900 px-6 text-center text-white"
      :style="thumbnailStyle"
    >
      <div class="max-w-md">
        <p class="text-xs font-semibold uppercase tracking-wide text-indigo-200">{{ formatLabel }}</p>
        <h2 class="mt-2 text-xl font-semibold leading-tight">{{ record.title || 'WebHDP record' }}</h2>
        <p class="mt-3 text-sm text-slate-200">{{ previewMessage }}</p>
        <button
          v-if="canPreview"
          type="button"
          class="mt-5 rounded-md bg-white px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-indigo-50"
          @click="previewLoaded = true"
        >
          Load 3D Preview
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import PlaygroundModelViewer from '@/components/tools/playground/PlaygroundModelViewer.vue'

const props = defineProps({
  record: {
    type: Object,
    required: true,
  },
})

const previewLoaded = ref(false)
const modelPreview = computed(() => props.record?.model_preview || {})
const canPreview = computed(() => Boolean(modelPreview.value.can_inline_preview && modelPreview.value.url))
const formatLabel = computed(() => {
  if (modelPreview.value.format) return modelPreview.value.format.toUpperCase()
  if (modelPreview.value.is_3d_record) return '3D'
  return 'Public Preview'
})
const previewMessage = computed(() => {
  if (canPreview.value) return 'Interactive WebHDP preview is available for this published model.'
  if (props.record.thumbnail_url) return 'Interactive preview is unavailable, so the published thumbnail is shown.'
  return 'Interactive preview is unavailable for this public record.'
})
const thumbnailStyle = computed(() => {
  if (!props.record?.thumbnail_url || canPreview.value) return {}
  return {
    backgroundImage: `linear-gradient(rgba(15, 23, 42, 0.50), rgba(15, 23, 42, 0.72)), url("${props.record.thumbnail_url}")`,
    backgroundSize: 'cover',
    backgroundPosition: 'center',
  }
})

watch(
  () => modelPreview.value.url,
  () => {
    previewLoaded.value = false
  }
)
</script>
