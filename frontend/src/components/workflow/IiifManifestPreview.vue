<template>
  <div v-if="manifest" class="space-y-3">
    <p class="text-xs font-medium text-slate-700">{{ manifest.versionLabel }}</p>
    <template v-if="manifest.scenes.length">
      <article v-for="(scene, sceneIndex) in manifest.scenes" :key="sceneIndex" class="space-y-2">
        <p class="text-sm font-medium text-slate-800">Scene · {{ scene.label }}</p>
        <div v-for="(model, modelIndex) in scene.models" :key="modelIndex" class="space-y-2 rounded border border-slate-200 p-2">
          <p v-if="model.label !== scene.label" class="text-sm font-medium text-slate-800">{{ model.label }}</p>
          <div class="flex flex-wrap gap-x-3 gap-y-1 text-sm">
            <button v-if="inlineUrl(model)" type="button" class="text-indigo-700 underline"
              :aria-expanded="isExpanded(sceneIndex, modelIndex)" @click="toggleModel(sceneIndex, modelIndex)">
              {{ isExpanded(sceneIndex, modelIndex) ? 'Hide model asset' : 'Preview model asset' }}
            </button>
            <a :href="openUrl(model)" target="_blank" rel="noopener noreferrer" class="text-indigo-700 underline">Open model file</a>
          </div>
          <p v-if="!inlineUrl(model)" class="text-xs text-slate-600">Open this file directly or use a compatible IIIF viewer.</p>
          <div v-if="isExpanded(sceneIndex, modelIndex)" class="space-y-2">
            <p class="text-xs text-slate-600">This preview shows the GLB/glTF asset. Scene placement, cameras and annotations are described in the manifest.</p>
            <PlaygroundModelViewer :src="inlineUrl(model)" :alt="model.label" />
          </div>
          <details v-if="model.point || model.transforms.length" class="text-xs text-slate-700">
            <summary class="cursor-pointer font-medium">Scene placement</summary>
            <p v-if="model.point" class="mt-1">Target point (X, Y, Z) {{ model.point.join(', ') }}</p>
            <ol v-if="model.transforms.length" class="mt-1 list-decimal pl-5">
              <li v-for="(transform, index) in model.transforms" :key="index">
                {{ transform.name }} (X, Y, Z) {{ transform.values.join(', ') }}
              </li>
            </ol>
          </details>
        </div>
      </article>
      <a :href="IIIF_VIEWER_MATRIX_URL" target="_blank" rel="noopener noreferrer" class="inline-block text-xs text-indigo-700 underline">IIIF Presentation 4 viewer support</a>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import PlaygroundModelViewer from '@/components/tools/playground/PlaygroundModelViewer.vue'
import { IIIF_ADMIN_SAMPLE_ID, IIIF_VIEWER_MATRIX_URL, iiifInlineModelUrl, inspectIiifManifest } from '@/utils/iiifPresentation'

const props = defineProps({
  content: { type: [String, Object], default: '' },
  adminSampleUrl: { type: String, default: '' },
})
const manifest = computed(() => inspectIiifManifest(props.content))
const expandedModel = ref('')

function inlineUrl(model) {
  return iiifInlineModelUrl(model, window.location.origin, props.adminSampleUrl)
}
function openUrl(model) {
  return model.url === IIIF_ADMIN_SAMPLE_ID && props.adminSampleUrl ? props.adminSampleUrl : model.url
}
function isExpanded(sceneIndex, modelIndex) {
  return expandedModel.value === `${sceneIndex}/${modelIndex}`
}
function toggleModel(sceneIndex, modelIndex) {
  expandedModel.value = isExpanded(sceneIndex, modelIndex) ? '' : `${sceneIndex}/${modelIndex}`
}
watch(() => props.content, () => { expandedModel.value = '' })
</script>
