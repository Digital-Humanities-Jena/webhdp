<template>
  <main class="min-h-screen bg-slate-950 text-white">
    <LoadingSpinner v-if="loading" size="lg" text="Loading embed..." />

    <section v-else-if="error" class="flex min-h-screen items-center justify-center px-4">
      <div class="max-w-md text-center">
        <p class="text-sm font-semibold uppercase tracking-wide text-rose-300">WebHDP</p>
        <h1 class="mt-2 text-xl font-semibold">Preview unavailable</h1>
        <p class="mt-2 text-sm text-slate-300">{{ error }}</p>
      </div>
    </section>

    <section v-else-if="record" class="flex min-h-screen flex-col">
      <div class="min-h-0 flex-1">
        <PublicRecordPreview :record="record" />
      </div>
      <footer class="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 bg-slate-950 px-4 py-3">
        <div class="min-w-0">
          <h1 class="truncate text-sm font-semibold">{{ record.title }}</h1>
          <p class="truncate text-xs text-slate-400">{{ creatorLabel || 'WebHDP public record' }}</p>
        </div>
        <a
          :href="record.public_url"
          target="_blank"
          rel="noopener noreferrer"
          class="shrink-0 rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-indigo-50"
        >
          Details
        </a>
      </footer>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import publicRecordService from '@/services/publicRecord.service.js'
import PublicRecordPreview from '@/views/public/PublicRecordPreview.vue'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const record = ref(null)

const creatorLabel = computed(() => (record.value?.creators || []).join(', '))

onMounted(async () => {
  try {
    const response = await publicRecordService.getRecord(route.params.environment, route.params.zenodoRecordId)
    record.value = response.data
    document.title = `${record.value.title} | WebHDP Embed`
  } catch (err) {
    error.value = err.response?.data?.error?.message || err.response?.data?.error || err.message || 'The public embed could not be loaded.'
  } finally {
    loading.value = false
  }
})
</script>
