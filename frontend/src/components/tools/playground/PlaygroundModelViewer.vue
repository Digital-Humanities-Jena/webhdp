<template>
  <div class="overflow-hidden rounded-2xl border border-slate-200 bg-slate-950/5">
    <div
      v-if="loadError"
      class="flex aspect-[4/3] items-center justify-center bg-slate-100 px-4 text-center text-xs text-slate-600"
    >
      {{ loadError }}
    </div>

    <div
      v-else-if="!isReady"
      class="flex aspect-[4/3] items-center justify-center bg-slate-100 text-xs text-slate-500"
    >
      Loading 3D preview…
    </div>

    <model-viewer
      ref="viewerElement"
      v-else
      :src="src"
      :alt="alt"
      camera-controls
      touch-action="pan-y"
      crossorigin="anonymous"
      exposure="1"
      shadow-intensity="1"
      environment-image="neutral"
      class="aspect-[4/3] w-full bg-[radial-gradient(circle_at_top,_rgba(255,255,255,0.95),_rgba(226,232,240,0.9)_38%,_rgba(148,163,184,0.38))]"
    />
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import modelViewerScriptUrl from '@google/model-viewer/dist/model-viewer.min.js?url'

const props = defineProps({
  src: {
    type: String,
    required: true
  },
  alt: {
    type: String,
    default: '3D preview'
  }
})

let registrationPromise = null

function ensureModelViewerRegistered() {
  if (typeof window === 'undefined') {
    return Promise.resolve()
  }
  if (window.customElements?.get('model-viewer')) {
    return Promise.resolve()
  }
  if (!registrationPromise) {
    registrationPromise = new Promise((resolve, reject) => {
      const existingScript = document.querySelector('script[data-model-viewer-loader="true"]')

      const handleReady = () => {
        if (window.customElements?.get('model-viewer')) {
          resolve()
          return
        }
        registrationPromise = null
        reject(new Error('model-viewer did not register the custom element.'))
      }

      const handleError = () => {
        registrationPromise = null
        reject(new Error('Failed to load model-viewer.'))
      }

      if (existingScript) {
        if (existingScript.dataset.loaded === 'true') {
          handleReady()
          return
        }
        existingScript.addEventListener('load', handleReady, { once: true })
        existingScript.addEventListener('error', handleError, { once: true })
        return
      }

      const script = document.createElement('script')
      script.type = 'module'
      script.async = true
      script.src = modelViewerScriptUrl
      script.dataset.modelViewerLoader = 'true'
      script.addEventListener('load', () => {
        script.dataset.loaded = 'true'
        handleReady()
      }, { once: true })
      script.addEventListener('error', handleError, { once: true })
      document.head.appendChild(script)
    })
  }
  return registrationPromise
}

const isReady = ref(typeof window !== 'undefined' && Boolean(window.customElements?.get('model-viewer')))
const loadError = ref('')
const viewerElement = ref(null)
let removeErrorListener = null

function clearErrorListener() {
  if (removeErrorListener) {
    removeErrorListener()
    removeErrorListener = null
  }
}

onMounted(async () => {
  if (isReady.value) {
    return
  }
  try {
    await ensureModelViewerRegistered()
    isReady.value = true
  } catch {
    loadError.value = '3D preview could not be initialized in this browser.'
  }
})

watch(
  () => [isReady.value, viewerElement.value],
  async ([ready, element]) => {
    clearErrorListener()
    if (!ready || !element) {
      return
    }
    await nextTick()
    const currentElement = viewerElement.value
    if (!currentElement) {
      return
    }
    const handleError = () => {
      loadError.value = 'The selected 3D asset could not be rendered inline.'
    }
    currentElement.addEventListener('error', handleError)
    removeErrorListener = () => {
      currentElement.removeEventListener('error', handleError)
    }
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  clearErrorListener()
})
</script>
