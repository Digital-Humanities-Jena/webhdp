<template>
  <div class="space-y-4">
    <section v-if="outputSummary.length > 0" class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
      <div class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Outputs</div>
      <div class="mt-3 space-y-3">
        <div
          v-for="output in outputSummary"
          :key="output.name"
          class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3"
        >
          <div class="text-sm font-medium text-slate-900">{{ output.label }}</div>
          <div class="mt-1 break-all text-xs text-slate-600">{{ stringifyValue(output.value) }}</div>
          <div v-if="output.description" class="mt-2 text-xs text-slate-500">{{ output.description }}</div>
        </div>
      </div>
    </section>

    <section
      v-for="group in artifactGroups"
      :key="group.id"
      class="rounded-2xl border border-slate-200 bg-white px-4 py-4"
    >
      <div class="flex items-center justify-between gap-3">
        <div>
          <div class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Artifacts</div>
          <div class="mt-1 text-sm font-medium text-slate-900">{{ group.label }}</div>
        </div>
        <div class="text-xs text-slate-500">{{ group.items.length }} {{ group.items.length === 1 ? 'file' : 'files' }}</div>
      </div>

      <div v-if="group.widget === 'image_gallery'" class="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <article
          v-for="artifact in group.items"
          :key="`${group.id}-${artifact.index}`"
          class="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50"
        >
          <div v-if="previewUrls[artifact.index]" class="aspect-[4/3] bg-white">
            <img :src="previewUrls[artifact.index]" :alt="artifact.name" class="h-full w-full object-contain">
          </div>
          <div v-else class="flex aspect-[4/3] items-center justify-center bg-slate-100 text-xs text-slate-500">
            Loading preview…
          </div>
          <div class="border-t border-slate-200 px-4 py-3">
            <div class="text-sm font-medium text-slate-900">{{ artifact.name }}</div>
            <div class="mt-1 break-all text-xs text-slate-500">{{ artifact.path }}</div>
            <button
              type="button"
              class="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-white"
              @click="downloadArtifact(artifact)"
            >
              Download
            </button>
          </div>
        </article>
      </div>

      <div v-else-if="group.widget === 'model_viewer'" class="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-2">
        <article
          v-for="artifact in group.items"
          :key="`${group.id}-${artifact.index}`"
          class="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50"
        >
          <PlaygroundModelViewer
            v-if="artifact.canInlinePreview && previewUrls[artifact.index]"
            :src="previewUrls[artifact.index]"
            :alt="artifact.name"
          />
          <div
            v-else-if="artifact.canInlinePreview && !hasPreviewEntry(artifact.index)"
            class="flex aspect-[4/3] items-center justify-center bg-slate-100 px-4 text-center text-xs text-slate-500"
          >
            Loading 3D preview…
          </div>
          <div
            v-else
            class="flex aspect-[4/3] items-center justify-center bg-slate-100 px-4 text-center text-xs text-slate-500"
          >
            {{ artifact.canInlinePreview ? 'The browser could not load this model preview, so download is used as the fallback action.' : 'Inline 3D preview is not available for this format, so download is used as the fallback action.' }}
          </div>

          <div class="border-t border-slate-200 px-4 py-3">
            <div class="text-sm font-medium text-slate-900">{{ artifact.name }}</div>
            <div class="mt-1 break-all text-xs text-slate-500">{{ artifact.path }}</div>
            <button
              type="button"
              class="mt-3 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-white"
              @click="downloadArtifact(artifact)"
            >
              Download
            </button>
          </div>
        </article>
      </div>

      <div v-else class="mt-4 space-y-3">
        <article
          v-for="artifact in group.items"
          :key="`${group.id}-${artifact.index}`"
          class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="text-sm font-medium text-slate-900">{{ artifact.name }}</div>
              <div class="mt-1 break-all text-xs text-slate-500">{{ artifact.path }}</div>
              <div v-if="group.widget === 'model_viewer'" class="mt-2 text-xs text-slate-500">
                {{ artifact.canInlinePreview ? 'Render-friendly 3D model detected. Download to inspect the generated asset.' : 'Inline 3D preview is not available for this format, so download is used as the fallback action.' }}
              </div>
            </div>
            <button
              type="button"
              class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-white"
              @click="downloadArtifact(artifact)"
            >
              Download
            </button>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onBeforeUnmount, reactive, watch, computed } from 'vue'
import PlaygroundModelViewer from './PlaygroundModelViewer.vue'
import pipelineService from '@/services/pipeline.service'
import { buildPlaygroundArtifactGroups, buildPlaygroundOutputSummary } from '@/utils/playgroundResults'

const props = defineProps({
  runId: {
    type: String,
    required: true
  },
  result: {
    type: Object,
    default: () => ({})
  },
  schema: {
    type: Object,
    required: true
  }
})

const previewUrls = reactive({})

const artifactGroups = computed(() => buildPlaygroundArtifactGroups(props.result, props.schema))
const outputSummary = computed(() => buildPlaygroundOutputSummary(props.result, props.schema))

function revokeUrls() {
  Object.values(previewUrls).forEach((url) => {
    if (url) {
      URL.revokeObjectURL(url)
    }
  })
  Object.keys(previewUrls).forEach((key) => {
    delete previewUrls[key]
  })
}

function hasPreviewEntry(index) {
  return Object.prototype.hasOwnProperty.call(previewUrls, index)
}

async function loadPreviews() {
  revokeUrls()
  const previewableArtifacts = artifactGroups.value.flatMap((group) => {
    if (group.widget === 'image_gallery') {
      return group.items
    }
    if (group.widget === 'model_viewer') {
      return group.items.filter((artifact) => artifact.canInlinePreview)
    }
    return []
  })
  await Promise.all(previewableArtifacts.map(async (artifact) => {
    try {
      const blob = await pipelineService.downloadPlaygroundArtifact(props.runId, artifact.index, { suppressGlobalError: true })
      previewUrls[artifact.index] = URL.createObjectURL(blob)
    } catch {
      previewUrls[artifact.index] = ''
    }
  }))
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function downloadArtifact(artifact) {
  const blob = await pipelineService.downloadPlaygroundArtifact(props.runId, artifact.index)
  triggerBlobDownload(blob, artifact.name || `artifact-${artifact.index}`)
}

function stringifyValue(value) {
  if (Array.isArray(value)) {
    return value.join(', ')
  }
  if (value && typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}

watch(
  () => [props.runId, props.result],
  () => {
    void loadPreviews()
  },
  { immediate: true, deep: true }
)

onBeforeUnmount(() => {
  revokeUrls()
})
</script>
