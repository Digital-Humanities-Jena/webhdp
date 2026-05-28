<template>
  <div class="space-y-6">
    <section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.22em] text-teal-700">Community Migration</p>
          <h2 class="mt-2 text-2xl font-semibold text-slate-900">Move Zenodo community membership safely</h2>
        </div>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Candidates</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">{{ planSummary.total_records || 0 }}</p>
          </div>
          <div class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Append</p>
            <p class="mt-1 text-2xl font-semibold text-emerald-800">{{ planSummary.append_needed || 0 }}</p>
          </div>
          <div class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Already Target</p>
            <p class="mt-1 text-2xl font-semibold text-amber-800">{{ planSummary.already_in_target || 0 }}</p>
          </div>
          <div class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-rose-700">Ineligible</p>
            <p class="mt-1 text-2xl font-semibold text-rose-800">{{ planSummary.ineligible || 0 }}</p>
          </div>
        </div>
      </div>
    </section>

    <section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div class="space-y-6">
        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Plan</h3>
              <p class="mt-1 text-xs text-slate-500">Source collection, communities, and filters.</p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                :disabled="planning || !canPlan"
                @click="buildPlan"
              >
                {{ planning ? 'Planning...' : 'Build Plan' }}
              </button>
              <button
                type="button"
                class="rounded-lg bg-teal-600 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-700 disabled:opacity-50"
                :disabled="launching || !canLaunch"
                @click="launchMigration"
              >
                {{ launching ? 'Queueing...' : 'Queue Migration' }}
              </button>
            </div>
          </div>

          <div class="mt-5 grid gap-4 lg:grid-cols-3">
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Source Collection
              <select v-model="form.source_retrieval_id" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900">
                <option value="">Select retrieval</option>
                <option v-for="item in retrievals" :key="item.retrieval_id" :value="item.retrieval_id">
                  {{ item.collection?.record_count || item.summary?.retrieved_records || 0 }} records · {{ item.retrieval_id }}
                </option>
              </select>
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Source Community
              <input v-model="form.source_community" type="text" placeholder="community-a" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Target Community
              <input v-model="form.target_community" type="text" placeholder="community-b" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
          </div>

          <div class="mt-4 grid gap-4 lg:grid-cols-4">
            <select v-model="form.record_status" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900">
              <option value="all">All statuses</option>
              <option value="published">Published</option>
              <option value="draft">Draft</option>
            </select>
            <select v-model="form.target_acceptance_policy" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900">
              <option value="direct">Target accepts all</option>
              <option value="moderated">Target moderates requests</option>
            </select>
            <input v-model="form.q" type="search" placeholder="Title, DOI, record ID" class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900" />
            <input v-model="form.created_from" type="date" class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900" />
          </div>

          <div class="mt-4 grid gap-4 lg:grid-cols-4">
            <input v-model="form.created_to" type="date" class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900" />
          </div>

          <div class="mt-4 flex flex-wrap gap-4">
            <label class="inline-flex items-center gap-2 text-sm text-slate-700">
              <input v-model="form.editable_only" type="checkbox" class="rounded border-slate-300 text-teal-600" />
              Editable only
            </label>
            <label class="inline-flex items-center gap-2 text-sm text-slate-700">
              <input v-model="form.remove_source_after_verify" type="checkbox" class="rounded border-slate-300 text-teal-600" />
              Remove source after target verification
            </label>
          </div>
        </section>

        <section v-if="plan" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Dry-Run Summary</h3>
              <p class="mt-1 text-xs text-slate-500">{{ plan.summary?.pending_moderation_note }}</p>
            </div>
          </div>
          <div class="mt-4 grid gap-3 md:grid-cols-3">
            <div v-for="item in summaryCards" :key="item.label" class="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">{{ item.label }}</p>
              <p class="mt-1 text-xl font-semibold text-slate-900">{{ item.value }}</p>
            </div>
          </div>
        </section>

        <section v-if="planRecords.length" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 class="text-sm font-semibold text-slate-900">Preview</h3>
          <div class="mt-4 divide-y divide-slate-100">
            <article v-for="record in planRecords.slice(0, 12)" :key="`${record.session_id}-${record.local_record_id}`" class="py-3">
              <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p class="text-sm font-semibold text-slate-900">{{ record.record_title || 'Untitled record' }}</p>
                  <p class="mt-1 text-xs text-slate-500">Session {{ record.session_id }} · Record {{ record.local_record_id }} · {{ record.record_status }}</p>
                </div>
                <span :class="record.is_editable ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'" class="rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide">
                  {{ record.is_editable ? 'Editable' : 'Ineligible' }}
                </span>
              </div>
              <p class="mt-2 text-xs text-slate-500">{{ (record.before_communities || []).join(', ') }}</p>
            </article>
          </div>
        </section>
      </div>

      <aside class="space-y-6 xl:sticky xl:top-24 xl:self-start">
        <section v-if="currentJob" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <h3 class="text-sm font-semibold text-slate-900">Job Progress</h3>
            <span class="rounded-full border border-slate-300 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700">{{ currentJob.state }}</span>
          </div>
          <p class="mt-2 text-sm text-slate-600">{{ currentJob.phase || 'queued' }}</p>
          <div class="mt-4 h-2.5 overflow-hidden rounded-full bg-slate-100">
            <div class="h-full rounded-full bg-teal-600 transition-all duration-300" :style="{ width: `${jobProgress.percent || 0}%` }"></div>
          </div>
          <div class="mt-4 grid grid-cols-2 gap-3 text-sm">
            <div><p class="text-slate-500">Processed</p><p class="font-semibold text-slate-900">{{ jobProgress.processed || 0 }} / {{ jobProgress.total_records || 0 }}</p></div>
            <div><p class="text-slate-500">Succeeded</p><p class="font-semibold text-emerald-700">{{ jobProgress.succeeded || 0 }}</p></div>
            <div><p class="text-slate-500">Failed</p><p class="font-semibold text-rose-700">{{ jobProgress.failed || 0 }}</p></div>
            <div><p class="text-slate-500">Verified</p><p class="font-semibold text-slate-900">{{ currentJob.summary?.target_verified || 0 }}</p></div>
          </div>
          <div class="mt-4 flex flex-wrap gap-2">
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="!canResume" @click="resumeJob">Resume</button>
            <button type="button" class="rounded-lg border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50" :disabled="!canCancel" @click="cancelJob">Cancel</button>
            <a
              :href="exportUrl('csv')"
              class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Export CSV
            </a>
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <h3 class="text-sm font-semibold text-slate-900">Recent Jobs</h3>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="loadJobs">Refresh</button>
          </div>
          <div v-if="jobs.length === 0" class="mt-4 text-sm text-slate-500">No community migrations yet.</div>
          <div v-else class="mt-4 space-y-3">
            <button
              v-for="job in jobs"
              :key="job.job_id"
              type="button"
              class="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-left transition hover:bg-white"
              @click="restoreJob(job)"
            >
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-semibold text-slate-900">{{ job.source_community }} -> {{ job.target_community }}</p>
                <span class="text-xs text-slate-500">{{ job.state }}</span>
              </div>
              <p class="mt-1 text-xs text-slate-500">{{ job.progress?.processed || 0 }} / {{ job.progress?.total_records || job.summary?.total_records || 0 }} processed</p>
            </button>
          </div>
        </section>
      </aside>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import toolsService from '@/services/tools.service'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const retrievals = ref([])
const jobs = ref([])
const plan = ref(null)
const currentJob = ref(null)
const planning = ref(false)
const launching = ref(false)
let pollTimer = null

const form = ref({
  source_retrieval_id: '',
  source_community: '',
  target_community: '',
  record_status: 'all',
  editable_only: true,
  q: '',
  created_from: '',
  created_to: '',
  remove_source_after_verify: false,
  target_acceptance_policy: 'direct',
})

const planSummary = computed(() => plan.value?.summary || {})
const planRecords = computed(() => plan.value?.records_preview || [])
const jobProgress = computed(() => currentJob.value?.progress || {})
const terminalStates = ['SUCCESS', 'FAILURE', 'CANCELLED']
const canPlan = computed(() => {
  return !!form.value.source_retrieval_id
    && !!form.value.source_community.trim()
    && !!form.value.target_community.trim()
    && form.value.source_community.trim().toLowerCase() !== form.value.target_community.trim().toLowerCase()
})
const canLaunch = computed(() => {
  const summary = plan.value?.summary || {}
  return canPlan.value && Number(summary.total_records || 0) > 0 && (Number(summary.append_needed || 0) > 0 || Number(summary.already_in_target || 0) > 0)
})
const canResume = computed(() => currentJob.value && ['FAILURE', 'PENDING'].includes(currentJob.value.state))
const canCancel = computed(() => currentJob.value && !terminalStates.includes(currentJob.value.state))

const summaryCards = computed(() => [
  { label: 'Total', value: planSummary.value.total_records || 0 },
  { label: 'Editable', value: planSummary.value.editable || 0 },
  { label: 'Append Needed', value: planSummary.value.append_needed || 0 },
  { label: 'Already Target', value: planSummary.value.already_in_target || 0 },
  { label: 'Ineligible', value: planSummary.value.ineligible || 0 },
  { label: 'Community B Owner Token', value: planSummary.value.target_owner_token_status || (planSummary.value.target_owner_token_required ? 'Required' : 'Not required') },
  { label: 'Remove After Verify', value: form.value.remove_source_after_verify ? 'On' : 'Off' },
])

const requestPayload = ({ includePlanChecksum = false } = {}) => ({
  source_retrieval_id: form.value.source_retrieval_id,
  source_community: form.value.source_community.trim(),
  target_community: form.value.target_community.trim(),
  filters: {
    record_status: form.value.record_status,
    editable_only: form.value.editable_only,
    q: form.value.q.trim(),
    created_from: form.value.created_from || null,
    created_to: form.value.created_to || null,
  },
  options: {
    remove_source_after_verify: form.value.remove_source_after_verify,
    target_acceptance_policy: form.value.target_acceptance_policy,
  },
  ...(includePlanChecksum && plan.value?.plan_checksum ? { plan_checksum: plan.value.plan_checksum } : {}),
})

const loadContext = async () => {
  const response = await toolsService.getCommunityMigrationContext()
  retrievals.value = response.data?.retrievals || []
  const defaults = response.data?.defaults || {}
  if (defaults.record_status) form.value.record_status = defaults.record_status
  if (typeof defaults.editable_only === 'boolean') form.value.editable_only = defaults.editable_only
  if (typeof defaults.remove_source_after_verify === 'boolean') form.value.remove_source_after_verify = defaults.remove_source_after_verify
  if (defaults.target_acceptance_policy) form.value.target_acceptance_policy = defaults.target_acceptance_policy
  if (!form.value.source_retrieval_id && retrievals.value.length) {
    form.value.source_retrieval_id = retrievals.value[0].retrieval_id
  }
}

const loadJobs = async () => {
  const response = await toolsService.listCommunityMigrationJobs({ limit: 12 })
  jobs.value = response.data?.jobs || []
}

const buildPlan = async () => {
  planning.value = true
  try {
    const response = await toolsService.planCommunityMigration(requestPayload())
    plan.value = response.data
    toast.success('Community migration plan built')
  } catch (err) {
    toast.error(err.error?.message || err.message || 'Failed to build migration plan')
  } finally {
    planning.value = false
  }
}

const pollJob = async () => {
  if (!currentJob.value?.job_id) return
  try {
    const response = await toolsService.getCommunityMigrationJob(currentJob.value.job_id)
    currentJob.value = response.data || currentJob.value
    if (terminalStates.includes(currentJob.value.state)) {
      clearPoll()
      await loadJobs()
    }
  } catch (err) {
    clearPoll()
  }
}

const startPoll = () => {
  clearPoll()
  pollTimer = window.setInterval(pollJob, 2500)
}

const clearPoll = () => {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

const launchMigration = async () => {
  launching.value = true
  try {
    const response = await toolsService.launchCommunityMigration(requestPayload({ includePlanChecksum: true }))
    currentJob.value = response.data
    toast.success('Community migration queued')
    await loadJobs()
    await pollJob()
    startPoll()
  } catch (err) {
    toast.error(err.error?.message || err.message || 'Failed to queue community migration')
  } finally {
    launching.value = false
  }
}

const restoreJob = async (job) => {
  currentJob.value = job
  await pollJob()
  if (currentJob.value && !terminalStates.includes(currentJob.value.state)) startPoll()
}

const resumeJob = async () => {
  if (!currentJob.value?.job_id) return
  const response = await toolsService.resumeCommunityMigration(currentJob.value.job_id)
  currentJob.value = response.data || currentJob.value
  startPoll()
  toast.success('Community migration resumed')
}

const cancelJob = async () => {
  if (!currentJob.value?.job_id) return
  const response = await toolsService.cancelCommunityMigration(currentJob.value.job_id)
  currentJob.value = response.data || currentJob.value
  toast.success('Community migration cancellation requested')
}

const exportUrl = (format) => `/api/v1/tools/community-migrations/jobs/${encodeURIComponent(currentJob.value?.job_id || '')}/export?format=${format}`

watch(
  () => ({ ...form.value }),
  () => {
    plan.value = null
    if (currentJob.value && terminalStates.includes(currentJob.value.state)) {
      currentJob.value = null
      clearPoll()
    }
  },
)

onMounted(async () => {
  try {
    await Promise.all([loadContext(), loadJobs()])
    if (currentJob.value && !terminalStates.includes(currentJob.value.state)) startPoll()
  } catch (err) {
    toast.error(err.error?.message || err.message || 'Failed to load community migration')
  }
})

onBeforeUnmount(clearPoll)
</script>
