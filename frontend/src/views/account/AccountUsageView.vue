<template>
  <div class="mx-auto max-w-5xl space-y-5 px-4 py-8 sm:px-6">
    <header>
      <h1 class="text-3xl font-semibold text-slate-950">Your usage and limits</h1>
      <p class="mt-2 max-w-2xl text-sm text-slate-700">See what your account can access and how much capacity you are using.</p>
    </header>

    <section class="rounded-xl border border-slate-200 bg-white p-5" aria-labelledby="access-title">
      <h2 id="access-title" class="text-lg font-semibold text-slate-950">Access</h2>
      <ul class="mt-3 space-y-2 text-sm text-slate-700">
        <li><strong>Workspaces.</strong> Your sessions are private by default. Access to shared work depends on your permissions for the session.</li>
        <li><strong>Zenodo.</strong> You can publish with a credential you are allowed to use in the selected environment.</li>
        <li><strong>HPC.</strong> {{ authStore.user?.hpc?.has_access ? 'Your account has HPC access.' : 'An administrator can approve HPC access for your account.' }}</li>
        <li><strong>Server-mounted inputs.</strong> {{ hasMountedInputAccess ? 'Your account can use server-mounted inputs where configured.' : 'You can upload your own files. An administrator can grant access to server-mounted inputs.' }}</li>
      </ul>
      <div class="mt-4 flex flex-wrap gap-4 text-sm font-medium text-indigo-700">
        <router-link to="/account/configuration" class="underline">Account settings</router-link>
        <router-link to="/account/institutions" class="underline">Workspace memberships</router-link>
        <router-link to="/hpc-resources" class="underline">HPC access and allocations</router-link>
        <router-link to="/docs/account-usage" class="underline">How limits are counted</router-link>
      </div>
    </section>

    <section class="rounded-xl border border-slate-200 bg-white p-5" aria-labelledby="usage-title" :aria-busy="loading">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h2 id="usage-title" class="text-lg font-semibold text-slate-950">Usage</h2>
        <button type="button" :disabled="loading" class="text-sm font-medium text-indigo-700 underline disabled:opacity-50" @click="loadUsage">Refresh usage</button>
      </div>
      <p v-if="loading" class="mt-3 text-sm text-slate-700" role="status">Checking your usage…</p>
      <p v-if="error" class="mt-3 text-sm text-rose-800" role="alert">Could not load usage. Refresh to try again.</p>

      <div v-if="usage" class="mt-4 grid gap-4 md:grid-cols-2">
        <article v-if="usage.uploads" class="rounded-lg border border-slate-200 p-4">
          <h3 class="font-semibold text-slate-950">Uploads</h3>
          <dl class="mt-3 space-y-2 text-sm text-slate-700">
            <div class="flex flex-wrap justify-between gap-1"><dt>Source files and pending uploads</dt><dd>{{ withLimit(bytes(usage.uploads.used_bytes), usage.uploads.limit_bytes, bytes) }}</dd></div>
            <div class="flex flex-wrap justify-between gap-1"><dt>Uploads in progress</dt><dd>{{ withLimit(usage.uploads.active, usage.uploads.active_limit) }}</dd></div>
            <div class="flex flex-wrap justify-between gap-1"><dt>Maximum size per request</dt><dd>{{ bytes(usage.uploads.request_limit_bytes) }}</dd></div>
            <div v-if="usage.uploads.stream_bytes_last_24_hours != null" class="flex flex-wrap justify-between gap-1"><dt>Cloud-streamed uploads in the past 24 hours</dt><dd>{{ withLimit(bytes(usage.uploads.stream_bytes_last_24_hours), usage.uploads.stream_limit_bytes, bytes) }}</dd></div>
          </dl>
          <router-link to="/uploads" class="mt-3 inline-block text-sm font-medium text-indigo-700 underline">Open your uploads</router-link>
        </article>

        <article v-if="usage.model_publication" class="rounded-lg border border-slate-200 p-4">
          <h3 class="font-semibold text-slate-950">3D tutorial and Sandbox</h3>
          <dl class="mt-3 space-y-2 text-sm text-slate-700">
            <div class="flex flex-wrap justify-between gap-1"><dt>Queued and running requests</dt><dd>{{ usage.model_publication.active }} of {{ usage.model_publication.active_limit }}</dd></div>
            <div class="flex flex-wrap justify-between gap-1"><dt>Requests accepted in the past 24 hours</dt><dd>{{ usage.model_publication.accepted_last_24_hours }} of {{ usage.model_publication.daily_limit }}</dd></div>
            <div class="flex flex-wrap justify-between gap-1"><dt>Workspace space held</dt><dd>{{ bytes(usage.model_publication.stored_bytes) }} of {{ bytes(usage.model_publication.storage_limit_bytes) }}</dd></div>
          </dl>
          <router-link to="/tutorial/3d" class="mt-3 inline-block text-sm font-medium text-indigo-700 underline">Open your practice runs</router-link>
        </article>

        <article v-if="usage.native_processing" class="rounded-lg border border-slate-200 p-4">
          <h3 class="font-semibold text-slate-950">Pipelines and Playground</h3>
          <dl class="mt-3 space-y-2 text-sm text-slate-700">
            <div class="flex flex-wrap justify-between gap-1"><dt>Queued and running</dt><dd>{{ withLimit(usage.native_processing.active, usage.native_processing.active_limit) }}</dd></div>
            <div class="flex flex-wrap justify-between gap-1"><dt>Queued</dt><dd>{{ usage.native_processing.queued }}</dd></div>
            <div class="flex flex-wrap justify-between gap-1"><dt>Running</dt><dd>{{ usage.native_processing.running }}</dd></div>
          </dl>
          <router-link to="/submissions" class="mt-3 inline-block text-sm font-medium text-indigo-700 underline">Open submissions</router-link>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import api from '@/services/api'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const hasMountedInputAccess = computed(() => authStore.user?.role === 'admin' || authStore.user?.capabilities?.includes('mounted_input_access'))
const usage = ref(null)
const loading = ref(false)
const error = ref(false)
let controller

const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
function bytes(value) {
  if (!Number.isFinite(value)) return 'Unavailable'
  const unit = value > 0 ? Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1) : 0
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value / 1024 ** unit)} ${units[unit]}`
}

function withLimit(used, limit, format = String) {
  return limit === null ? `${used} used` : `${used} of ${format(limit)}`
}

async function loadUsage() {
  if (loading.value) return
  const request = new AbortController()
  controller = request
  loading.value = true
  error.value = false
  try {
    const result = await api.get('/account/usage', { signal: request.signal, suppressGlobalError: true })
    if (!request.signal.aborted) usage.value = result.data
  } catch {
    if (!request.signal.aborted) error.value = true
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}

onMounted(loadUsage)
onBeforeUnmount(() => controller?.abort())
</script>
