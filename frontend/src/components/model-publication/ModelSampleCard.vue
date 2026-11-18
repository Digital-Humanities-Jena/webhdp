<template>
  <article class="flex h-full min-w-0 flex-col overflow-hidden rounded-xl border bg-white"
    :class="selected ? 'border-indigo-600 ring-2 ring-indigo-100' : 'border-slate-200'">
    <div class="aspect-[16/9] overflow-hidden bg-slate-100">
      <img v-if="!previewFailed && sample.preview" :src="sampleUrl(sample.id, true)" alt="" loading="lazy"
        class="h-full w-full object-cover" @error="previewFailed = true" />
      <div v-else class="flex h-full items-center justify-center text-slate-400">
        <CubeIcon class="h-12 w-12" aria-hidden="true" />
      </div>
    </div>
    <div class="flex flex-1 flex-col p-4">
      <p class="text-xs font-medium text-teal-800">{{ sample.format === 'gltf' ? 'glTF' : sample.format.toUpperCase() }}</p>
      <h3 class="mt-1 text-base font-semibold text-slate-950">{{ sample.title }}</h3>
      <p class="mt-1 text-sm leading-5 text-slate-600">{{ sample.description }}</p>
      <dl class="mt-3 space-y-1 text-xs leading-5 text-slate-600">
        <div v-if="sample.layout">
          <dt class="inline font-semibold text-slate-800">Layout</dt>
          <dd class="ml-1 inline">{{ sample.layout }}</dd>
        </div>
        <div v-if="sample.texture_status">
          <dt class="inline font-semibold text-slate-800">Textures</dt>
          <dd class="ml-1 inline">{{ sample.texture_status }}</dd>
        </div>
        <div v-if="sample.license">
          <dt class="inline font-semibold text-slate-800">License</dt>
          <dd class="ml-1 inline">{{ sample.license === 'cc0-1.0' ? 'CC0 1.0' : sample.license }}</dd>
        </div>
      </dl>
      <div class="mt-auto flex flex-wrap items-center gap-x-3 gap-y-2 pt-4">
        <button v-if="selectable" type="button" :aria-pressed="selected" :aria-label="'Use ' + sample.title"
          class="rounded-md px-3 py-2 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
          :class="selected ? 'bg-indigo-700 text-white' : 'bg-indigo-50 text-indigo-800 hover:bg-indigo-100'"
          @click="$emit('select', sample)">
          {{ selected ? 'Selected' : 'Use sample' }}
        </button>
        <a :href="sampleUrl(sample.id)" :aria-label="'Download ' + sample.title + ' (ZIP)'" download
          class="rounded-md px-1 py-2 text-sm font-medium text-indigo-700 underline decoration-indigo-200 underline-offset-4 hover:decoration-indigo-700">
          Download ZIP
        </a>
      </div>
    </div>
  </article>
</template>

<script setup>
import { ref } from 'vue'
import { CubeIcon } from '@heroicons/vue/24/outline'
import { sampleUrl } from '@/services/modelPublication.service'

defineProps({
  sample: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  selectable: { type: Boolean, default: false }
})
defineEmits(['select'])
const previewFailed = ref(false)
</script>
