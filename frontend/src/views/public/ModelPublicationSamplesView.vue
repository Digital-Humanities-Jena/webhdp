<template>
  <div class="min-h-screen bg-slate-50 text-slate-900">
    <header class="border-b border-slate-200 bg-white">
      <nav aria-label="Public navigation" class="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
        <router-link to="/" class="text-lg font-semibold hover:text-indigo-700">WebHDP</router-link>
        <router-link to="/model-publication" class="rounded-md bg-indigo-700 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-800">
          Open 3D workflow
        </router-link>
      </nav>
    </header>
    <main class="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
      <h1 class="text-3xl font-bold tracking-tight sm:text-4xl">Sample 3D models</h1>
      <p class="mt-3 max-w-2xl text-base leading-7 text-slate-600">
        Each ZIP contains a small model and a metadata spreadsheet (MSF). Try a different folder layout
        or see how WebHDP handles missing, misplaced, misnamed, or unreadable textures.
      </p>
      <a v-if="publishedExample" :href="publishedExample" target="_blank" rel="noopener noreferrer"
        class="mt-3 inline-block text-sm font-semibold text-indigo-700 underline underline-offset-4">
        See a finished record in Zenodo Sandbox
      </a>
      <div v-if="samples.length" class="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ModelSampleCard v-for="sample in singleSamples" :key="sample.id" :sample="sample" />
      </div>
      <p v-else-if="loading" role="status" class="mt-7 text-sm text-slate-600">Loading sample models…</p>
      <div v-else role="alert" class="mt-7 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
        <p>Sample downloads could not be loaded.</p>
        <button type="button" class="mt-2 font-semibold underline" @click="loadSamples">Try again</button>
      </div>
      <section v-if="batchSample" aria-labelledby="batch-title" class="mt-9 max-w-xl">
        <h2 id="batch-title" class="text-xl font-semibold">Batch sample</h2>
        <p class="mb-4 mt-1 text-sm text-slate-600">Three models share one metadata spreadsheet. WebHDP creates one Sandbox draft for each row.</p>
        <ModelSampleCard :sample="batchSample" />
      </section>
    </main>
    <footer class="border-t border-slate-200 bg-white px-4 py-5"><LegalLinks /></footer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import ModelSampleCard from '@/components/model-publication/ModelSampleCard.vue'
import LegalLinks from '@/components/legal/LegalLinks.vue'
import publicationService, { sandboxDraftUrl } from '@/services/modelPublication.service'

const samples = ref([])
const batchSample = computed(() => samples.value.find(sample => sample.format === 'batch'))
const singleSamples = computed(() => samples.value.filter(sample => sample.format !== 'batch'))
const loading = ref(true)
const publishedExample = ref('')

async function loadSamples() {
  loading.value = true
  try {
    const response = await publicationService.samples()
    samples.value = response.datasets
    publishedExample.value = sandboxDraftUrl(response.published_example)
  } catch {
    samples.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadSamples)
</script>
