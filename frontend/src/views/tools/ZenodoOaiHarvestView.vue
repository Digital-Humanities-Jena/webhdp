<template>
  <div class="space-y-6">
    <section class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-indigo-700">Zenodo OAI Harvest</p>
          <h2 class="mt-2 text-2xl font-semibold text-slate-900">Harvest public Zenodo metadata into .hdpc collections</h2>
          <p class="mt-2 max-w-3xl text-sm text-slate-600">
            Build explorer-only inventories from Zenodo OAI-PMH sets for public discovery, quality review, and community monitoring.
          </p>
        </div>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Harvested</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">{{ progress.harvested_records || summary.harvested_records || 0 }}</p>
          </div>
          <div class="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Shards</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">{{ collection.shard_count || shards.length }}</p>
          </div>
          <div class="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Duplicates</p>
            <p class="mt-1 text-2xl font-semibold text-amber-800">{{ progress.duplicate_records_skipped || summary.duplicate_records_skipped || 0 }}</p>
          </div>
          <div class="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">State</p>
            <p class="mt-1 text-sm font-semibold uppercase text-emerald-800">{{ currentJob?.state || 'Ready' }}</p>
          </div>
        </div>
      </div>
    </section>

    <section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div class="space-y-6">
        <section class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Start Harvest</h3>
              <p class="mt-1 text-xs text-slate-500">Default scope is the public Zenodo set user-3dbigdataspace.</p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                class="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                :disabled="preflighting"
                @click="runPreflight"
              >
                {{ preflighting ? 'Checking...' : 'Preflight' }}
              </button>
              <button
                type="button"
                class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
                :disabled="launching"
                @click="launchHarvest"
              >
                {{ launching ? 'Queueing...' : 'Start Harvest' }}
              </button>
            </div>
          </div>

          <div class="mt-5 grid gap-4 lg:grid-cols-4">
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Set Identifier
              <input v-model="setIdentifier" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Metadata
              <select v-model="metadataPrefix" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900">
                <option value="oai_datacite">OAI DataCite</option>
                <option value="dcat">DCAT</option>
                <option value="oai_dc">OAI Dublin Core</option>
              </select>
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Mode
              <select v-model="harvestMode" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900">
                <option value="full">Full harvest</option>
                <option value="historical_backfill">Historical backfill</option>
              </select>
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Record Limit
              <input v-model="maxRecords" type="number" min="1" placeholder="No limit" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
          </div>

          <div class="mt-4 grid gap-4 lg:grid-cols-4">
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              From
              <input v-model="fromDate" type="date" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Until
              <input v-model="untilDate" type="date" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Retries
              <input v-model="requestRetries" type="number" min="0" max="10" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Timeout
              <input v-model="requestTimeoutSeconds" type="number" min="1" max="300" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
          </div>

          <div class="mt-4 flex flex-wrap items-center gap-4">
            <label class="inline-flex items-center gap-2 text-sm font-medium text-slate-700">
              <input v-model="incremental" type="checkbox" class="rounded border-slate-300 text-indigo-600" />
              Incremental
            </label>
            <label class="inline-flex items-center gap-2 text-sm font-medium text-slate-700">
              Overlap
              <input v-model="incrementalOverlapHours" type="number" min="0" max="168" class="w-24 rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </label>
          </div>

          <div v-if="preflightReport" class="mt-5 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <p class="text-sm font-semibold text-slate-900">Preflight</p>
            <div class="mt-2 grid gap-2 text-xs text-slate-600 md:grid-cols-3">
              <p>Status: <span class="font-semibold" :class="preflightReport.ok ? 'text-emerald-700' : 'text-amber-700'">{{ preflightReport.ok ? 'OK' : 'Check warnings' }}</span></p>
              <p>Sample: {{ preflightReport.sample?.records_seen ?? 'N/A' }} records</p>
              <p>Resumption: {{ preflightReport.sample?.has_resumption_token ? 'present' : 'none' }}</p>
            </div>
          </div>
        </section>

        <section v-if="currentJob" class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Current Harvest</h3>
              <p class="mt-1 break-all text-xs text-slate-500">{{ currentJob.harvest_id }}</p>
              <p v-if="currentJob.stale" class="mt-2 text-sm font-medium text-amber-700">No recent heartbeat. Resume after confirming no worker is still running.</p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button v-if="canPause" type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700" @click="pauseHarvest">Pause</button>
              <button v-if="canResume" type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700" @click="resumeHarvest">Resume</button>
              <button v-if="canCancel" type="button" class="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-700" @click="cancelHarvest">Cancel</button>
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60" :disabled="compacting" @click="compactHarvest">Compact</button>
              <button type="button" class="rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold text-rose-700 disabled:opacity-60" :disabled="deleting" @click="deleteHarvest">Delete</button>
            </div>
          </div>
          <div class="mt-5 h-2 overflow-hidden rounded-full bg-slate-100">
            <div class="h-full bg-indigo-600 transition-all" :style="{ width: `${progress.percent || 0}%` }"></div>
          </div>
          <div class="mt-4 grid gap-3 md:grid-cols-4">
            <p class="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">Pages: <span class="font-semibold">{{ progress.pages_retrieved || summary.pages_retrieved || 0 }}</span></p>
            <p class="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">Records/hour: <span class="font-semibold">{{ progress.records_per_hour || 0 }}</span></p>
            <p class="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">Latest: <span class="font-semibold">{{ formatShortDate(collection.latest_datestamp || summary.latest_datestamp) }}</span></p>
            <p class="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">Token: <span class="font-semibold">{{ progress.current_resumption_token ? 'active' : 'none' }}</span></p>
          </div>
          <div class="mt-4 flex flex-wrap gap-2">
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60" :disabled="!!exportingFormat" @click="downloadExport('manifest')">Manifest</button>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60" :disabled="!!exportingFormat" @click="downloadExport('csv')">CSV</button>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60" :disabled="!!exportingFormat" @click="downloadExport('archive')">Archive</button>
          </div>
        </section>

        <section v-if="currentJob" class="grid gap-6 lg:grid-cols-2">
          <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div class="flex items-end gap-2">
              <label class="flex-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Search
                <input v-model="recordSearch" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal" />
              </label>
              <button type="button" class="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white" @click="searchRecords">Search</button>
            </div>
            <p class="mt-3 text-xs text-slate-500">{{ recordSearchMessage }}</p>
            <div class="mt-3 divide-y divide-slate-100">
              <div v-for="record in recordResults" :key="`${record.session_id}-${record.local_record_id}`" class="py-3">
                <p class="text-sm font-semibold text-slate-900">{{ record.title }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ record.zenodo_record_id }} - {{ record.doi || 'No DOI' }}</p>
              </div>
            </div>
          </div>

          <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div class="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Detector
                <select v-model="selectedDetector" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal">
                  <option v-for="detector in detectorPresets" :key="detector.id" :value="detector.id">{{ detector.label }}</option>
                </select>
              </label>
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Target
                <input v-model="targetCommunity" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal" />
              </label>
              <button type="button" class="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white" @click="runDetector">Run</button>
            </div>
            <p class="mt-3 text-xs text-slate-500">Candidates: {{ detectorResult?.total || 0 }}</p>
            <div class="mt-3 divide-y divide-slate-100">
              <div v-for="record in detectorCandidates" :key="`${record.session_id}-${record.local_record_id}`" class="py-3">
                <p class="text-sm font-semibold text-slate-900">{{ record.title }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ record.reason }}</p>
              </div>
            </div>
          </div>
        </section>
      </div>

      <aside class="space-y-6">
        <section class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h3 class="text-sm font-semibold text-slate-900">History</h3>
          <div v-if="historyLoading" class="mt-4 text-sm text-slate-500">Loading harvest history...</div>
          <div v-else-if="jobs.length === 0" class="mt-4 text-sm text-slate-500">No OAI harvests yet.</div>
          <div v-else class="mt-3 divide-y divide-slate-100">
            <button
              v-for="job in jobs"
              :key="job.harvest_id"
              type="button"
              class="block w-full py-3 text-left"
              @click="selectJob(job)"
            >
              <p class="text-sm font-semibold text-slate-900">{{ job.collection?.record_count || job.summary?.harvested_records || 0 }} records - {{ job.state }}</p>
              <p class="mt-1 truncate text-xs text-slate-500">{{ job.options?.set_spec || 'user-3dbigdataspace' }} - {{ job.harvest_id }}</p>
            </button>
          </div>
        </section>

        <section v-if="currentJob" class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h3 class="text-sm font-semibold text-slate-900">Schedule</h3>
          <div class="mt-4 space-y-3">
            <label class="inline-flex items-center gap-2 text-sm font-medium text-slate-700">
              <input v-model="scheduleEnabled" type="checkbox" class="rounded border-slate-300 text-indigo-600" />
              Enabled
            </label>
            <select v-model="scheduleFrequency" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
            <button type="button" class="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white" @click="saveSchedule">Save Schedule</button>
            <button type="button" class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700" @click="runScheduleNow">Run Now</button>
          </div>
        </section>
      </aside>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import toolsService from '@/services/tools.service'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const setIdentifier = ref('3dbigdataspace')
const metadataPrefix = ref('oai_datacite')
const harvestMode = ref('full')
const maxRecords = ref('')
const fromDate = ref('')
const untilDate = ref('')
const requestRetries = ref(2)
const requestTimeoutSeconds = ref(30)
const incremental = ref(false)
const incrementalOverlapHours = ref(24)
const detectorPresets = ref([
  { id: 'community_migration_candidates', label: 'Community migration candidates' },
  { id: 'objaverse', label: 'Objaverse in description' },
  { id: '3d_model_files', label: '3D model files' },
  { id: 'missing_target_community', label: 'Missing target community' },
])
const jobs = ref([])
const currentJob = ref(null)
const loadingContext = ref(false)
const historyLoading = ref(false)
const launching = ref(false)
const preflighting = ref(false)
const preflightReport = ref(null)
const deleting = ref(false)
const compacting = ref(false)
const exportingFormat = ref('')
const recordSearch = ref('')
const recordResults = ref([])
const recordSearchMessage = ref('Run a search to inspect harvested records.')
const selectedDetector = ref('community_migration_candidates')
const targetCommunity = ref('3dbigdataspace')
const detectorResult = ref(null)
const scheduleEnabled = ref(false)
const scheduleFrequency = ref('weekly')
let pollTimer = null

const progress = computed(() => currentJob.value?.progress || {})
const summary = computed(() => currentJob.value?.summary || {})
const collection = computed(() => currentJob.value?.collection || {})
const shards = computed(() => currentJob.value?.manifest?.shards || [])
const detectorCandidates = computed(() => detectorResult.value?.candidates || [])
const terminalStates = ['SUCCESS', 'FAILURE', 'CANCELLED']
const canPause = computed(() => currentJob.value && !terminalStates.includes(currentJob.value.state) && currentJob.value.state !== 'PAUSED')
const canResume = computed(() => currentJob.value?.state === 'PAUSED')
const canCancel = computed(() => currentJob.value && !terminalStates.includes(currentJob.value.state))

const formatShortDate = (value) => value ? String(value).slice(0, 10) : 'N/A'

const buildPayload = () => ({
  set_identifier: setIdentifier.value,
  metadata_prefix: metadataPrefix.value,
  harvest_mode: harvestMode.value,
  max_records: maxRecords.value || null,
  from_date: fromDate.value || null,
  until_date: untilDate.value || null,
  request_retries: Number(requestRetries.value || 2),
  request_timeout_seconds: Number(requestTimeoutSeconds.value || 30),
  incremental: incremental.value,
  sync_mode: incremental.value ? 'incremental' : 'full',
  incremental_overlap_hours: Number(incrementalOverlapHours.value || 24),
  execution_target: 'celery_local',
})

const loadContext = async () => {
  loadingContext.value = true
  try {
    const response = await toolsService.getZenodoOaiHarvestContext()
    const defaults = response.data?.defaults || {}
    setIdentifier.value = defaults.set_identifier || '3dbigdataspace'
    metadataPrefix.value = defaults.metadata_prefix || 'oai_datacite'
    detectorPresets.value = response.data?.detectors || detectorPresets.value
  } catch (err) {
    console.error('Failed to load OAI harvest context', err)
    toast.error(err.error?.message || err.message || 'Failed to load OAI harvest context')
  } finally {
    loadingContext.value = false
  }
}

const loadJobs = async () => {
  historyLoading.value = true
  try {
    const response = await toolsService.listZenodoOaiHarvestJobs({ limit: 12 })
    jobs.value = response.data?.jobs || []
    if (!currentJob.value && jobs.value.length) currentJob.value = jobs.value[0]
  } catch (err) {
    console.error('Failed to load OAI harvest jobs', err)
  } finally {
    historyLoading.value = false
  }
}

const pollCurrent = async () => {
  if (!currentJob.value?.harvest_id) return
  try {
    const response = await toolsService.getZenodoOaiHarvestJob(currentJob.value.harvest_id)
    currentJob.value = response.data
  } catch (err) {
    console.error('Failed to poll OAI harvest job', err)
  }
}

const runPreflight = async () => {
  preflighting.value = true
  try {
    const response = await toolsService.preflightZenodoOaiHarvest(buildPayload())
    preflightReport.value = response.data?.preflight || null
    toast.success('OAI preflight completed')
  } catch (err) {
    toast.error(err.error?.message || err.message || 'Failed to preflight OAI harvest')
  } finally {
    preflighting.value = false
  }
}

const launchHarvest = async () => {
  launching.value = true
  try {
    const response = await toolsService.launchZenodoOaiHarvest(buildPayload())
    currentJob.value = {
      harvest_id: response.data?.harvest_id,
      state: 'PENDING',
      status: 'Queued Zenodo OAI harvest',
      progress: { percent: 0 },
      summary: {},
      options: buildPayload(),
    }
    toast.success('Zenodo OAI harvest queued')
    await loadJobs()
  } catch (err) {
    toast.error(err.error?.message || err.message || 'Failed to queue OAI harvest')
  } finally {
    launching.value = false
  }
}

const selectJob = async (job) => {
  currentJob.value = job
  await pollCurrent()
}

const pauseHarvest = async () => {
  await toolsService.pauseZenodoOaiHarvest(currentJob.value.harvest_id)
  await pollCurrent()
}

const resumeHarvest = async () => {
  const response = await toolsService.resumeZenodoOaiHarvest(currentJob.value.harvest_id)
  currentJob.value = response.data
}

const cancelHarvest = async () => {
  await toolsService.cancelZenodoOaiHarvest(currentJob.value.harvest_id)
  await pollCurrent()
}

const deleteHarvest = async () => {
  deleting.value = true
  try {
    await toolsService.deleteZenodoOaiHarvest(currentJob.value.harvest_id)
    currentJob.value = null
    await loadJobs()
    toast.success('OAI harvest deleted')
  } finally {
    deleting.value = false
  }
}

const compactHarvest = async () => {
  compacting.value = true
  try {
    const response = await toolsService.compactZenodoOaiHarvest(currentJob.value.harvest_id, { target_records_per_shard: 5000 })
    currentJob.value = response.data?.job || currentJob.value
    toast.success('OAI harvest compacted')
  } finally {
    compacting.value = false
  }
}

const searchRecords = async () => {
  if (!currentJob.value?.harvest_id) return
  const response = await toolsService.searchZenodoOaiHarvestRecords(currentJob.value.harvest_id, { q: recordSearch.value, limit: 50 })
  recordResults.value = response.data?.records || []
  recordSearchMessage.value = `${response.data?.total || 0} matching records`
}

const runDetector = async () => {
  if (!currentJob.value?.harvest_id) return
  const response = await toolsService.runZenodoOaiHarvestDetector(currentJob.value.harvest_id, {
    detector: selectedDetector.value,
    target_community: targetCommunity.value,
    limit: 50,
  })
  detectorResult.value = response.data
}

const saveSchedule = async () => {
  const response = await toolsService.updateZenodoOaiHarvestSchedule(currentJob.value.harvest_id, {
    enabled: scheduleEnabled.value,
    frequency: scheduleFrequency.value,
    incremental_overlap_hours: Number(incrementalOverlapHours.value || 24),
  })
  currentJob.value = response.data
  toast.success('Schedule saved')
}

const runScheduleNow = async () => {
  const response = await toolsService.runZenodoOaiHarvestScheduleNow(currentJob.value.harvest_id)
  currentJob.value = response.data
  toast.success('Incremental harvest queued')
  await loadJobs()
}

const exportFilename = (format) => {
  const harvestId = currentJob.value?.harvest_id || 'harvest'
  if (format === 'csv') return `zenodo-oai-harvest-${harvestId}.csv`
  if (format === 'archive') return `zenodo-oai-harvest-${harvestId}.zip`
  return `zenodo-oai-harvest-${harvestId}.json`
}

const downloadExport = async (format) => {
  if (!currentJob.value?.harvest_id) return
  exportingFormat.value = format
  try {
    const payload = await toolsService.exportZenodoOaiHarvest(currentJob.value.harvest_id, format)
    const blob = payload instanceof Blob ? payload : new Blob([payload])
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = exportFilename(format)
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    toast.error(err.error?.message || err.message || `Failed to export ${format}`)
  } finally {
    exportingFormat.value = ''
  }
}

onMounted(async () => {
  await Promise.all([loadContext(), loadJobs()])
  pollTimer = window.setInterval(pollCurrent, 5000)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>
