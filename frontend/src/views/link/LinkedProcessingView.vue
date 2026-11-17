<template>
  <main class="linked-processing mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
    <header class="flex flex-wrap items-start justify-between gap-4">
      <div><router-link v-if="runId" to="/link/jobs" class="text-sm font-medium text-indigo-600">← All linked processing</router-link><p v-else class="text-xs font-semibold uppercase tracking-wider text-indigo-600">WebHDP-Link</p><h1 class="mt-2 text-2xl font-semibold text-gray-900">{{ runId ? (job?.pipeline_name || 'Processing details') : 'Linked processing' }}</h1><p class="mt-3 max-w-3xl text-sm text-gray-600">{{ runId ? 'Follow this job and download its results. You can bookmark this page and return after signing in.' : 'Follow processing requested by your connected applications. Jobs and results stay available here when you leave the application.' }}</p></div>
      <div class="flex flex-wrap items-center gap-3"><label class="flex items-center gap-2 text-sm text-gray-600"><input v-model="autoRefresh" type="checkbox" class="accent-indigo-600">Auto refresh</label><button class="secondary" :disabled="loading || Boolean(busy)" @click="load">{{ loading ? 'Refreshing…' : 'Refresh' }}</button></div>
    </header>
    <div v-if="error" class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">{{ error }}</div>
    <div v-if="notice" class="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800" role="status">{{ notice }}</div>
    <p v-if="loading && !job && !jobs.length" class="text-sm text-gray-500" role="status">Loading your processing jobs…</p>

    <template v-if="!runId">
      <div class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white p-4"><label class="flex items-center gap-3 text-sm font-medium text-gray-700">Show<select v-model="filter" class="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"><option value="all">All jobs</option><option value="active">Queued and running</option><option value="succeeded">Completed</option><option value="failed">Failed</option><option value="cancelled">Cancelled</option></select></label><router-link to="/account/connected-apps" class="text-sm font-medium text-indigo-600">Manage connected applications</router-link></div>
      <p v-if="!loading && !filteredJobs.length" class="panel p-8 text-sm text-gray-600">{{ jobs.length ? 'No jobs match this filter.' : 'No linked processing yet. Start a pipeline in an application connected to WebHDP.' }}</p>
      <p v-if="jobs.length >= 100" class="text-xs text-gray-500">Showing the 100 most recent jobs. Use a saved job link to open an older result.</p>
      <section v-for="group in groups" :key="group.id" class="panel" :aria-label="group.name">
        <header class="border-b border-gray-100 px-5 py-4"><h2 class="font-semibold text-gray-900">{{ group.name }}</h2><p class="mt-1 text-xs text-gray-500">{{ group.jobs.length }} {{ group.jobs.length === 1 ? 'job' : 'jobs' }}</p></header>
        <div class="divide-y divide-gray-100"><article v-for="run in group.jobs" :key="run.id" class="flex flex-wrap items-center justify-between gap-4 px-5 py-5"><div class="min-w-0"><router-link :to="`/link/jobs/${encodeURIComponent(run.id)}`" class="font-semibold text-indigo-700 hover:underline">{{ run.pipeline_name || run.pipeline_id }}</router-link><p class="mt-1 text-xs text-gray-500">Version {{ run.pipeline_version }} · {{ formatDate(run.created_at) }}</p><p class="mt-1 font-mono text-xs text-gray-400">{{ run.id }}</p></div><div class="flex items-center gap-4"><div class="text-right"><span :class="['badge', statusClass(run.status)]">{{ statusLabel(run.status) }}</span><p v-if="linkProgressPhase(run)" class="mt-2 text-sm font-medium text-indigo-700">{{ linkProgressPhase(run).label }}</p><p class="mt-2 text-xs text-gray-500">{{ progressText(run) }}</p></div><router-link :to="`/link/jobs/${encodeURIComponent(run.id)}`" class="secondary">View job</router-link></div></article></div>
      </section>
    </template>

    <template v-else-if="job">
      <section class="panel p-5 sm:p-6">
        <div class="flex flex-wrap items-center justify-between gap-4"><div><span :class="['badge', statusClass(job.status)]">{{ statusLabel(job.status) }}</span><h2 class="mt-3 text-xl font-semibold text-gray-900">{{ job.pipeline_name || job.pipeline_id }}</h2><p class="mt-1 text-sm text-gray-500">{{ job.client_name || job.client_id }} · Version {{ job.pipeline_version }}</p></div><button v-if="isActive(job)" class="rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50" :disabled="Boolean(busy) || job.cancel_requested" @click="cancel">{{ job.cancel_requested ? 'Cancellation requested' : 'Cancel job' }}</button></div>
        <div v-if="linkProgressPhase(job)" class="mt-5 rounded-lg bg-indigo-50 p-4 text-sm text-indigo-900" role="status" aria-live="polite"><p class="font-semibold">{{ linkProgressPhase(job).label }}</p><p class="mt-1">{{ linkProgressPhase(job).detail }}</p></div>
        <div class="mt-6"><div class="mb-2 flex flex-wrap justify-between gap-2 text-sm"><span class="font-medium text-gray-700">{{ progressText(job) }}</span><span class="text-gray-500">{{ progressPercent(job) }}%</span></div><div class="h-2 overflow-hidden rounded-full bg-gray-100" role="progressbar" :aria-valuenow="progressPercent(job)" aria-valuemin="0" aria-valuemax="100" aria-label="Processing progress"><div class="h-full rounded-full bg-indigo-600 transition-all" :style="{ width: `${progressPercent(job)}%` }"></div></div></div>
        <p v-if="job.cancel_requested && job.status === 'running'" class="mt-3 text-sm text-amber-800">The current component may finish before cancellation takes effect.</p>
        <div v-if="job.error" class="mt-4 rounded-lg bg-red-50 p-4 text-sm text-red-800" role="alert">{{ typeof job.error === 'string' ? job.error : job.error.detail || job.error.message }}</div>
        <dl class="mt-6 grid gap-4 border-t border-gray-100 pt-5 text-sm sm:grid-cols-3"><div><dt class="text-gray-500">Submitted</dt><dd class="mt-1 text-gray-900">{{ formatDate(job.created_at) }}</dd></div><div><dt class="text-gray-500">Worker accepted</dt><dd class="mt-1 text-gray-900">{{ formatDate(job.started_at) }}</dd></div><div><dt class="text-gray-500">Finished</dt><dd class="mt-1 text-gray-900">{{ formatDate(job.completed_at) }}</dd></div></dl><p class="mt-5 break-all font-mono text-xs text-gray-400">Job {{ job.id }}</p>
      </section>
      <section v-if="job.steps?.length" class="panel"><h2 class="border-b border-gray-100 px-5 py-4 font-semibold text-gray-900">Pipeline progress</h2><ol class="divide-y divide-gray-100"><li v-for="(step, index) in job.steps" :key="step.id" class="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm"><span class="text-gray-700"><span class="mr-3 text-gray-400">{{ index + 1 }}.</span>{{ step.name }}</span><span :class="['badge', statusClass(step.status)]">{{ statusLabel(step.status) }}</span></li></ol></section>
      <section class="panel"><div class="border-b border-gray-100 px-5 py-4"><h2 class="font-semibold text-gray-900">Results</h2><p class="mt-1 text-sm text-gray-500">Downloads are checked against the recorded file size and SHA-256 checksum.</p></div><div v-if="job.artifacts?.length" class="divide-y divide-gray-100"><article v-for="artifact in job.artifacts" :key="artifact.id" class="px-5 py-4"><div class="flex flex-wrap items-center justify-between gap-3"><div class="min-w-0"><h3 class="break-all text-sm font-medium text-gray-900">{{ artifact.name }}</h3><p class="mt-1 text-xs text-gray-500">{{ formatBytes(artifact.size) }} · {{ artifact.media_type }}</p></div><button class="secondary" :disabled="Boolean(busy)" @click="download(artifact)">{{ busy === artifact.id ? 'Downloading…' : 'Download' }}</button></div><details class="mt-3"><summary class="cursor-pointer text-xs text-indigo-700">SHA-256 checksum</summary><p class="mt-2 break-all font-mono text-xs text-gray-500">{{ artifact.sha256 }}</p></details></article></div><p v-else class="px-5 py-7 text-sm text-gray-500">{{ isActive(job) ? 'Results will appear here when processing finishes.' : 'This job has no downloadable results.' }}</p></section>
    </template>
    <p v-if="updatedAt" class="text-xs text-gray-400">Last refreshed {{ formatDate(updatedAt) }}<span v-if="autoRefresh"> · every 5 seconds while processing</span></p>
  </main>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import linkService from '@/services/webhdpLink.service'
import { linkErrorMessage, verifyLinkArtifact, linkProgressPhase } from '@/utils/webhdpLink'
const route = useRoute()
const runId = computed(() => typeof route.params?.runId === 'string' ? route.params.runId : '')
const jobs = ref([]), job = ref(null), loading = ref(false), busy = ref(''), error = ref(''), notice = ref(''), updatedAt = ref(''), filter = ref('all'), autoRefresh = ref(true)
let timer, generation = 0
const isActive = (run) => ['queued', 'running'].includes(run.status)
const statusLabel = (status) => ({ queued: 'Queued', running: 'Running', succeeded: 'Completed', completed: 'Completed', failed: 'Failed', cancelled: 'Cancelled', pending: 'Pending', skipped: 'Skipped' })[status] || status
const statusClass = (status) => ['succeeded', 'completed'].includes(status) ? 'bg-emerald-50 text-emerald-800' : status === 'failed' ? 'bg-red-50 text-red-800' : ['running', 'queued'].includes(status) ? 'bg-indigo-50 text-indigo-700' : 'bg-gray-100 text-gray-600'
const formatDate = (value) => value ? new Date(value).toLocaleString() : '—'
const formatBytes = (value) => value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KiB` : `${(value / 1048576).toFixed(1)} MiB`
const progressText = (run) => `${run.progress?.completed || 0} of ${run.progress?.total || 0} steps finished`
const progressPercent = (run) => run.status === 'succeeded' ? 100 : run.progress?.total ? Math.min(100, Math.round((run.progress.completed || 0) / run.progress.total * 100)) : 0
const filteredJobs = computed(() => jobs.value.filter(run => filter.value === 'all' || (filter.value === 'active' ? isActive(run) : run.status === filter.value)))
const groups = computed(() => {
  const result = new Map()
  for (const run of filteredJobs.value) {
    const id = run.client_id || 'application'
    if (!result.has(id)) result.set(id, { id, name: run.client_name || run.client_id || 'Connected application', jobs: [] })
    result.get(id).jobs.push(run)
  }
  return [...result.values()]
})
async function load() {
  const current = ++generation, id = runId.value
  loading.value = true
  error.value = ''
  try {
    const result = id ? await linkService.getJob(id) : await linkService.listJobs()
    if (current !== generation) return
    if (id) job.value = result
    else jobs.value = result.jobs
    updatedAt.value = new Date().toISOString()
  } catch (err) { if (current === generation) error.value = linkErrorMessage(err) }
  finally { if (current === generation) loading.value = false }
}
async function cancel() {
  if (busy.value || !job.value) return
  busy.value = 'cancel'; notice.value = ''; error.value = ''
  try { job.value = await linkService.cancelJob(job.value.id); notice.value = 'Cancellation requested.' }
  catch (err) { error.value = linkErrorMessage(err) }
  finally { busy.value = '' }
}
async function download(artifact) {
  if (busy.value || !job.value) return
  busy.value = artifact.id; error.value = ''
  try {
    const blob = await linkService.downloadJobArtifact(job.value.id, artifact.id)
    await verifyLinkArtifact(blob, artifact)
    const url = URL.createObjectURL(blob), anchor = document.createElement('a')
    anchor.href = url; anchor.download = artifact.name; anchor.rel = 'noopener'
    document.body.appendChild(anchor); anchor.click(); anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (err) { error.value = linkErrorMessage(err) }
  finally { busy.value = '' }
}
watch(runId, () => { job.value = null; notice.value = ''; load() })
onMounted(() => { load(); timer = setInterval(() => { if (autoRefresh.value && !loading.value && !busy.value && (!runId.value || !job.value || isActive(job.value))) load() }, 5000) })
onUnmounted(() => { generation++; clearInterval(timer) })
</script>
<style scoped>
.panel { @apply overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm; }
.secondary { @apply inline-block rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50; }
.badge { @apply inline-flex rounded-full px-2.5 py-1 text-xs font-medium; }
button:focus-visible, a:focus-visible, summary:focus-visible { @apply outline outline-2 outline-offset-2 outline-indigo-600; }
</style>
