<template>
  <div class="mx-auto max-w-5xl px-4 py-8 text-slate-900 sm:px-6 sm:py-12">
    <header class="mb-7">
      <p class="text-sm font-semibold text-teal-800">Zenodo Sandbox workflow</p>
      <h1 class="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">Prepare a 3D model for publication</h1>
      <p class="mt-3 max-w-2xl text-base leading-7 text-slate-600">
        Choose a sample or upload your model. WebHDP checks texture references, maps your metadata, and
        prepares a draft with linked data files in the Zenodo test environment.
      </p>
    </header>

    <div class="publication-queue mb-5" :style="{ '--publication-nav-offset': demoAccount ? '0px' : `${navigationHeight}px` }">
      <ModelPublicationQueue :queue="queue" :job="activeJob" :unavailable="queueUnavailable"
        :offline="processingOffline" :can-open-job="Boolean(activeJob && (showForm || activeJob.id !== currentJob?.id))"
        :submitting="submitting" :upload-percent="uploadPercent" :expires-at="demoAccount ? authStore.user?.model_publication_expires_at : null"
        @open-job="openJob(activeJob)" @refresh="refreshQueue" />
    </div>

    <div v-if="!showForm && currentJob" class="space-y-5">
      <ModelPublicationRun :key="currentJob.id" :job="currentJob" :refresh-error="refreshError" :published-example="publishedExample" :demo-account="demoAccount"
        @refresh="refreshJobs" />
      <button v-if="!demoAccount || ['completed', 'failed'].includes(currentJob.status)" type="button" class="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50"
        @click="startAnother">
        Prepare another model
      </button>
    </div>

    <form v-else class="space-y-5" @submit.prevent="submit">
      <fieldset :disabled="submitting" class="space-y-5">
        <section class="rounded-xl border border-slate-200 bg-white p-4 sm:p-6" aria-labelledby="source-heading">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="source-heading" ref="sourceHeading" tabindex="-1" class="text-lg font-semibold">Choose a model</h2>
              <p class="mt-1 text-sm text-slate-600">Samples include a metadata spreadsheet and are ready to try.</p>
            </div>
            <router-link to="/model-publication/samples" class="text-sm font-semibold text-indigo-700 underline underline-offset-4">
              Sample downloads
            </router-link>
          </div>

          <div class="mt-4 inline-flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1" role="group" aria-label="Model source">
            <button type="button" :aria-pressed="mode === 'sample'" :class="modeButton('sample')" @click="changeMode('sample')">
              Use a sample
            </button>
            <button type="button" :aria-pressed="mode === 'upload'" :class="modeButton('upload')" @click="changeMode('upload')">
              {{ demoAccount ? 'Upload a sample ZIP' : 'Upload my model' }}
            </button>
          </div>

          <div v-if="mode === 'sample'" class="mt-4">
            <div v-if="samples.length" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <ModelSampleCard v-for="sample in samples" :key="sample.id" :sample="sample"
                :selected="sample.id === selectedSample?.id" selectable @select="chooseSample" />
            </div>
            <p v-else-if="loadingSamples" role="status" class="text-sm text-slate-600">Loading samples…</p>
            <div v-else role="alert" class="text-sm text-amber-900">
              Sample models could not be loaded.
              <button type="button" class="ml-1 font-semibold underline" @click="loadSamples">Try again</button>
            </div>
          </div>

          <div v-else class="mt-5">
            <label for="model-archive" class="block text-sm font-semibold">3D model file</label>
            <p id="model-archive-hint" class="mt-1 text-sm leading-6 text-slate-600">
              {{ demoAccount
                ? 'Select one of the unmodified ZIPs from Sample downloads. The spreadsheet in the ZIP supplies the metadata.'
                : 'Select a self-contained GLB or a ZIP (up to 24 MiB). The ZIP should contain one model with its original material and texture folders.' }}
            </p>
            <input id="model-archive" type="file" :accept="demoAccount ? '.zip' : '.zip,.glb'" required
              :aria-describedby="archiveError ? 'model-archive-hint model-archive-error' : 'model-archive-hint'" :aria-invalid="Boolean(archiveError)"
              class="mt-2 block w-full min-w-0 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:font-semibold file:text-slate-900 hover:file:bg-slate-200"
              @change="setArchive" />
            <p v-if="archiveError" id="model-archive-error" role="alert" class="mt-2 text-sm text-rose-800">{{ archiveError }}</p>
          </div>
        </section>

        <section v-if="mode === 'upload' && !demoAccount" class="rounded-xl border border-slate-200 bg-white p-4 sm:p-6" aria-labelledby="metadata-heading">
          <h2 id="metadata-heading" class="text-lg font-semibold">Describe the model</h2>
          <label for="metadata-source" class="mt-3 block text-sm font-semibold">Metadata source</label>
          <select id="metadata-source" v-model="metadataSource"
            class="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm sm:max-w-sm">
            <option value="form">Enter the description here</option>
            <option v-if="!standaloneGlb" value="archive">Use the metadata spreadsheet inside the ZIP</option>
            <option value="upload">Add a separate metadata spreadsheet</option>
          </select>
          <div v-if="metadataSource === 'form'" class="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <label for="publication-title" class="block text-sm font-semibold">Title</label>
              <input id="publication-title" v-model.trim="metadata.title" maxlength="250" required class="metadata-input" />
            </div>
            <div>
              <label for="publication-creator" class="block text-sm font-semibold">Creator</label>
              <input id="publication-creator" v-model.trim="metadata.creator" maxlength="200" required class="metadata-input" autocomplete="off" />
            </div>
            <div class="sm:col-span-2">
              <label for="publication-description" class="block text-sm font-semibold">Description</label>
              <textarea id="publication-description" v-model.trim="metadata.description" rows="3" maxlength="5000" required class="metadata-input" />
            </div>
          </div>
          <div v-else class="mt-4">
            <div v-if="metadataSource === 'upload'">
              <label for="publication-msf" class="block text-sm font-semibold">Metadata spreadsheet (MSF)</label>
              <input id="publication-msf" type="file" accept=".csv,.xls,.xlsx" required
                :aria-describedby="msfError ? 'publication-msf-hint publication-msf-error' : 'publication-msf-hint'" :aria-invalid="Boolean(msfError)"
                class="mt-2 block w-full min-w-0 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:font-semibold file:text-slate-900 hover:file:bg-slate-200"
                @change="setMsf" />
              <p v-if="msfError" id="publication-msf-error" role="alert" class="mt-2 text-sm text-rose-800">{{ msfError }}</p>
            </div>
            <p id="publication-msf-hint" class="mt-2 text-sm leading-6 text-slate-600">
              Include the model path or filename, title, creator, and description. WebHDP matches the model to its row.
              <router-link to="/model-publication/samples" class="font-semibold text-indigo-700 underline underline-offset-4">See sample spreadsheets in the ZIPs.</router-link>
            </p>
          </div>
        </section>

        <section v-if="selectedSample && mode === 'sample'" ref="selectedSampleSummary" aria-label="Selected sample" tabindex="-1"
          class="rounded-xl border border-teal-100 bg-teal-50 p-4 text-sm text-teal-950 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-600">
          <p class="font-semibold">Using the spreadsheet supplied with {{ selectedSample.title }}</p>
          <p v-if="selectedSample.creator" class="mt-1">Creator {{ selectedSample.creator }}</p>
        </section>

        <div v-if="availabilityError || missingCredential" role="status" class="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <p v-if="availabilityError">Could not check your Sandbox access.</p>
          <p v-else-if="demoAccount">Sandbox access is temporarily unavailable. Check again or ask the presenter.</p>
          <p v-else>Add a Zenodo Sandbox key to create drafts from your WebHDP account.</p>
          <router-link v-if="!demoAccount && missingCredential" to="/account/configuration" class="mt-2 inline-block font-semibold underline">
            Manage your Zenodo Sandbox key
          </router-link>
          <button type="button" class="mt-2 block font-semibold underline" @click="loadAvailability">Check again</button>
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <button type="submit" :disabled="submitting || !canSubmit"
            class="rounded-md bg-indigo-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-800 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-600">
            {{ submitting ? 'Sending model…' : 'Prepare Sandbox draft' }}
          </button>
          <p class="text-sm text-slate-600">
            <template v-if="processingOffline">You can set up your request while the worker is offline.</template>
            <template v-else-if="demoAccount && activeJob">Wait for your current request before starting another.</template>
            <template v-else>Creates a private draft for review.</template>
          </p>
        </div>
      </fieldset>

      <div v-if="submitting" class="rounded-lg border border-slate-200 bg-white p-4 text-sm" role="status">
        <p>{{ uploadPercent === null ? 'Sending your request…' : `Uploading model… ${uploadPercent}%` }}</p>
        <progress v-if="uploadPercent !== null" :value="uploadPercent" max="100" class="mt-2 w-full accent-indigo-700"
          aria-label="File upload progress" />
      </div>
      <div v-if="submitError" role="alert" class="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
        <p>{{ submitError }}</p>
      </div>
    </form>

    <section v-if="jobs.length" class="mt-8 border-t border-slate-200 pt-4" aria-labelledby="recent-model-jobs">
      <h2 id="recent-model-jobs" class="text-sm font-semibold">Recent requests</h2>
      <ul class="mt-2 flex flex-wrap gap-2">
        <li v-for="job in jobs.slice(0, 5)" :key="job.id">
          <button type="button" :aria-pressed="!showForm && currentJob?.id === job.id"
            class="rounded-md border border-slate-200 bg-white px-3 py-2 text-left text-sm text-indigo-800 hover:bg-indigo-50 aria-pressed:border-indigo-400 aria-pressed:bg-indigo-50"
            @click="openJob(job)">
            {{ job.title || 'Model request' }} · {{ statusLabel(job.status) }}
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ModelPublicationQueue from '@/components/model-publication/ModelPublicationQueue.vue'
import ModelPublicationRun from '@/components/model-publication/ModelPublicationRun.vue'
import ModelSampleCard from '@/components/model-publication/ModelSampleCard.vue'
import publicationService, { sandboxDraftUrl } from '@/services/modelPublication.service'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const authStore = useAuthStore()
const demoAccount = computed(() => Boolean(authStore.user?.model_publication_only))
const samples = ref([])
const loadingSamples = ref(true)
const publishedExample = ref('')
const mode = ref('sample')
const selectedSample = ref(null)
const archive = ref(null)
const archiveError = ref('')
const msf = ref(null)
const msfError = ref('')
const metadataSource = ref('form')
const metadata = ref({ title: '', creator: '', description: '' })
const standaloneGlb = computed(() => archive.value?.name.toLowerCase().endsWith('.glb') ?? false)
const availability = ref(null)
const availabilityError = ref(false)
const missingCredential = computed(() => availability.value?.credential_ready === false)
const queue = ref(null)
const queueUnavailable = ref(false)
const processingOffline = computed(() => (queueUnavailable.value ? availability.value?.ready : queue.value?.ready ?? availability.value?.ready) === false)
const canSubmit = computed(() => {
  if (!availability.value?.credential_ready || availabilityError.value || processingOffline.value || (demoAccount.value && activeJob.value)) return false
  return mode.value === 'sample' ? Boolean(selectedSample.value) : Boolean(archive.value && (demoAccount.value || metadataSource.value !== 'upload' || msf.value))
})
const submitting = ref(false)
const uploadPercent = ref(null)
const submitError = ref('')
const refreshError = ref('')
const sourceHeading = ref(null)
const selectedSampleSummary = ref(null)
const jobs = ref([])
const currentJob = ref(null)
const showForm = ref(true)
const navigationHeight = ref(0)
const activeJob = computed(() => isActive(currentJob.value) ? currentJob.value : jobs.value.find(isActive))

let retryKey = ''
let refreshTimer
let pendingRefresh
let queueTimer
let pendingQueue
let pendingAvailability
let navigationObserver
let mounted = true
let setupInteracted = false
let jobRevision = 0

const statusLabel = (status) => ({ queued: 'Queued', running: 'Processing', completed: 'Ready', failed: 'Needs attention' }[status] || 'Pending')
const isActive = (job) => ['queued', 'running'].includes(job?.status)
const modeButton = (value) => [
  'rounded-md px-3 py-2 text-sm font-semibold',
  mode.value === value ? 'bg-white text-indigo-800 shadow-sm' : 'text-slate-600 hover:text-slate-900'
]

function changeMode(value) {
  if (mode.value === value) return
  setupInteracted = true
  mode.value = value
  archive.value = null
  archiveError.value = ''
  msf.value = null
  msfError.value = ''
  metadataSource.value = 'form'
}

function chooseSample(sample, moveFocus = true) {
  if (moveFocus) setupInteracted = true
  mode.value = 'sample'
  selectedSample.value = sample
  if (moveFocus) nextTick(() => focusInView(selectedSampleSummary.value))
}

function setArchive(event) {
  const file = event.target.files[0] ?? null
  const validType = demoAccount.value ? /\.zip$/i : /\.(zip|glb)$/i
  if (file && (!validType.test(file.name) || file.size === 0 || file.size > 24 * 1024 ** 2)) {
    archiveError.value = demoAccount.value
      ? 'Choose a nonempty sample ZIP up to 24 MiB.'
      : 'Choose a nonempty ZIP or GLB up to 24 MiB.'
    event.target.value = ''
    archive.value = null
    return
  }
  archiveError.value = ''
  archive.value = file
  if (standaloneGlb.value && metadataSource.value === 'archive') metadataSource.value = 'form'
}

function setMsf(event) {
  const file = event.target.files[0] ?? null
  if (file && (!/\.(csv|xls|xlsx)$/i.test(file.name) || file.size === 0 || file.size > 1024 ** 2)) {
    msfError.value = 'Choose a nonempty CSV or Excel spreadsheet up to 1 MiB.'
    event.target.value = ''
    msf.value = null
    return
  }
  msfError.value = ''
  msf.value = file
}

function focusInView(element) {
  if (!element) return
  element.focus({ preventScroll: true })
  element.scrollIntoView({ block: 'center' })
}

watch([mode, selectedSample, archive, msf, metadataSource, metadata], () => {
  retryKey = ''
  submitError.value = ''
}, { deep: true })
watch(metadataSource, () => {
  msf.value = null
  msfError.value = ''
})

async function loadSamples() {
  loadingSamples.value = true
  try {
    const payload = await publicationService.samples()
    samples.value = payload.datasets
    publishedExample.value = sandboxDraftUrl(payload.published_example)
    const requestedSample = samples.value.find(sample => sample.id === route.query.sample)
    if (requestedSample && !setupInteracted) chooseSample(requestedSample, false)
  } catch {
    samples.value = []
  } finally {
    loadingSamples.value = false
  }
}

async function loadAvailability() {
  if (!mounted || pendingAvailability) return
  const controller = new AbortController()
  pendingAvailability = controller
  try {
    const state = await publicationService.availability(controller.signal)
    if (!mounted) return
    availability.value = state
    availabilityError.value = false
  } catch {
    if (mounted) availabilityError.value = true
  } finally {
    pendingAvailability = undefined
  }
}

async function refreshQueue() {
  if (!mounted || pendingQueue) return
  window.clearTimeout(queueTimer)
  const controller = new AbortController()
  pendingQueue = controller
  try {
    const state = await publicationService.queue(controller.signal)
    if (!mounted) return
    queue.value = state
    queueUnavailable.value = false
  } catch {
    if (mounted) queueUnavailable.value = true
  } finally {
    pendingQueue = undefined
    if (mounted) {
      const delay = (document.hidden ? 15000 : 4000) + Math.random() * 2000
      queueTimer = window.setTimeout(refreshQueue, delay)
    }
  }
}

function rememberJob(job) {
  jobRevision += 1
  jobs.value = [job, ...jobs.value.filter(item => item.id !== job.id)]
}

function openJob(job, moveFocus = true) {
  showForm.value = false
  currentJob.value = job
  if (moveFocus) {
    setupInteracted = true
    nextTick(() => focusInView(document.getElementById('model-publication-result')))
  }
}

function startAnother() {
  setupInteracted = true
  showForm.value = true
  currentJob.value = null
  archive.value = null
  archiveError.value = ''
  msf.value = null
  msfError.value = ''
  submitError.value = ''
  retryKey = ''
  nextTick(() => focusInView(sourceHeading.value))
}

async function refreshJobs({ restore = false } = {}) {
  if (pendingRefresh || !mounted) return
  window.clearTimeout(refreshTimer)
  const controller = new AbortController()
  const currentRevision = jobRevision
  pendingRefresh = controller
  try {
    const result = await publicationService.jobs(controller.signal)
    if (!mounted || controller.signal.aborted || currentRevision !== jobRevision) return
    jobs.value = result.jobs
    if (currentJob.value) {
      const updatedJob = jobs.value.find(job => job.id === currentJob.value.id)
      if (updatedJob) currentJob.value = updatedJob
    } else if (restore && !setupInteracted && !route.query.sample && !submitting.value) {
      const latest = jobs.value.find(isActive) || jobs.value[0]
      if (latest) openJob(latest, false)
    }
    refreshError.value = ''
  } catch {
    if (mounted && !controller.signal.aborted) {
      refreshError.value = 'The connection was interrupted. WebHDP will check again automatically.'
    }
  } finally {
    pendingRefresh = undefined
    if (mounted && (refreshError.value || activeJob.value)) {
      const delay = document.hidden ? 5000 : 1400 + Math.random() * 800
      refreshTimer = window.setTimeout(() => refreshJobs(), delay)
    }
  }
}

async function submit() {
  if (!canSubmit.value || submitting.value) return
  setupInteracted = true
  submitting.value = true
  submitError.value = ''
  uploadPercent.value = null
  retryKey ||= crypto.randomUUID()
  const form = new FormData()
  if (mode.value === 'sample') {
    form.set('sample_id', selectedSample.value.id)
    form.set('metadata_source', 'archive')
  } else {
    form.set('archive', archive.value)
    const source = demoAccount.value ? 'archive' : metadataSource.value
    form.set('metadata_source', source)
    if (source === 'form') {
      for (const [key, value] of Object.entries(metadata.value)) form.set(key, value)
    }
    if (source === 'upload') form.set('msf', msf.value)
  }
  try {
    const job = await publicationService.start(form, retryKey, (event) => {
      if (event.total && mode.value === 'upload') uploadPercent.value = Math.round(event.loaded * 100 / event.total)
    })
    retryKey = ''
    rememberJob(job)
    openJob(job)
    refreshJobs()
    refreshQueue()
  } catch (error) {
    submitError.value = error?.error?.message || 'WebHDP could not send the request. Check your connection and try again.'
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  loadSamples()
  loadAvailability()
  refreshJobs({ restore: true })
  refreshQueue()
  document.addEventListener('visibilitychange', refreshWhenVisible)
  const navigation = document.getElementById('webhdp-primary-navigation')
  if (navigation) {
    const measureNavigation = () => { navigationHeight.value = navigation.offsetHeight }
    measureNavigation()
    if (typeof ResizeObserver !== 'undefined') {
      navigationObserver = new ResizeObserver(measureNavigation)
      navigationObserver.observe(navigation)
    }
  }
})

function refreshWhenVisible() {
  if (!document.hidden) {
    refreshQueue()
    if (activeJob.value) refreshJobs()
  }
}

onBeforeUnmount(() => {
  mounted = false
  window.clearTimeout(refreshTimer)
  window.clearTimeout(queueTimer)
  pendingRefresh?.abort()
  pendingQueue?.abort()
  pendingAvailability?.abort()
  navigationObserver?.disconnect()
  document.removeEventListener('visibilitychange', refreshWhenVisible)
})
</script>

<style scoped>
.publication-queue {
  position: sticky;
  top: var(--publication-nav-offset);
  z-index: 10;
}

@media (max-height: 440px) {
  .publication-queue {
    position: static;
  }
}

.metadata-input {
  @apply mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900;
}
</style>
