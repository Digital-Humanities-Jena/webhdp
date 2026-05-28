<template>
  <main class="min-h-screen bg-slate-50 text-slate-900">
    <section class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-5 sm:px-6 lg:px-8">
        <router-link to="/" class="text-lg font-semibold tracking-tight text-slate-950">WebHDP</router-link>
        <div class="flex flex-wrap items-center gap-4">
          <LegalLinks />
          <a
            v-if="record?.zenodo_url"
            :href="record.zenodo_url"
            target="_blank"
            rel="noopener noreferrer"
            class="rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
          >
            Open on Zenodo
          </a>
        </div>
      </div>
    </section>

    <LoadingSpinner v-if="loading" size="lg" text="Loading public record..." />

    <section v-else-if="error" class="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
      <div class="border border-rose-200 bg-white p-6">
        <h1 class="text-xl font-semibold text-rose-800">Record unavailable</h1>
        <p class="mt-2 text-sm text-slate-600">{{ error }}</p>
      </div>
    </section>

    <template v-else-if="record">
      <section class="bg-white">
        <div class="mx-auto grid max-w-6xl grid-cols-1 gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)] lg:px-8">
          <div class="min-w-0">
            <p class="text-xs font-semibold uppercase tracking-wide text-indigo-700">
              {{ record.environment === 'sandbox' ? 'Zenodo Sandbox' : 'Zenodo' }} record
            </p>
            <h1 class="mt-3 max-w-4xl text-3xl font-bold leading-tight text-slate-950 sm:text-4xl">
              {{ record.title }}
            </h1>
            <p v-if="creatorLabel" class="mt-3 text-base text-slate-700">{{ creatorLabel }}</p>
            <dl class="mt-6 grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
              <div v-if="record.doi">
                <dt class="font-medium text-slate-500">DOI</dt>
                <dd class="mt-1 break-all text-slate-900">{{ record.doi }}</dd>
              </div>
              <div v-if="record.publication_date">
                <dt class="font-medium text-slate-500">Publication Date</dt>
                <dd class="mt-1 text-slate-900">{{ record.publication_date }}</dd>
              </div>
              <div>
                <dt class="font-medium text-slate-500">Files</dt>
                <dd class="mt-1 text-slate-900">{{ record.file_count || 0 }}</dd>
              </div>
              <div>
                <dt class="font-medium text-slate-500">Record ID</dt>
                <dd class="mt-1 text-slate-900">{{ record.zenodo_record_id }}</dd>
              </div>
            </dl>
          </div>

          <div class="min-w-0">
            <PublicRecordPreview :record="record" />
          </div>
        </div>
      </section>

      <section class="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <div class="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div v-if="plainDescription" class="border border-slate-200 bg-white p-5">
            <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">Description</h2>
            <p class="mt-3 whitespace-pre-line text-sm leading-6 text-slate-700">{{ plainDescription }}</p>
          </div>

          <aside class="border border-slate-200 bg-white p-5">
            <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">Embed</h2>
            <p class="mt-3 text-sm text-slate-700">This public record exposes an oEmbed profile for rich embeds.</p>
            <a :href="record.oembed_url" class="mt-4 block break-all text-sm font-medium text-indigo-700 hover:text-indigo-900">
              {{ record.oembed_url }}
            </a>
          </aside>
        </div>
      </section>
    </template>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import publicRecordService, { publicOembedUrl } from '@/services/publicRecord.service.js'
import PublicRecordPreview from '@/views/public/PublicRecordPreview.vue'
import LegalLinks from '@/components/legal/LegalLinks.vue'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const record = ref(null)
let discoveryLink = null

const creatorLabel = computed(() => (record.value?.creators || []).join(', '))
const plainDescription = computed(() => stripHtml(record.value?.description || ''))

function stripHtml(value) {
  if (typeof document === 'undefined') return String(value || '').replace(/<[^>]+>/g, ' ').trim()
  const element = document.createElement('div')
  element.innerHTML = String(value || '')
  return (element.textContent || element.innerText || '').replace(/\s+\n/g, '\n').trim()
}

function setDiscoveryLink(oembedUrl) {
  if (typeof document === 'undefined' || !oembedUrl) return
  discoveryLink = document.createElement('link')
  discoveryLink.rel = 'alternate'
  discoveryLink.type = 'application/json+oembed'
  discoveryLink.href = oembedUrl
  discoveryLink.title = 'WebHDP oEmbed profile'
  document.head.appendChild(discoveryLink)
}

onMounted(async () => {
  try {
    const response = await publicRecordService.getRecord(route.params.environment, route.params.zenodoRecordId)
    record.value = response.data
    const currentUrl = window.location.href
    const discoveredUrl = publicOembedUrl(currentUrl)
    setDiscoveryLink(discoveredUrl)
    if (record.value) {
      record.value.oembed_url = discoveredUrl
      document.title = `${record.value.title} | WebHDP`
    }
  } catch (err) {
    error.value = err.response?.data?.error?.message || err.response?.data?.error || err.message || 'The public record could not be loaded.'
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  discoveryLink?.remove()
  discoveryLink = null
})
</script>
