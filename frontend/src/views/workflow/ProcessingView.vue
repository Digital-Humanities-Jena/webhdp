<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-3xl mx-auto px-4">
      <div class="bg-white shadow rounded-lg p-8">
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-700">Submission progress</p>
            <h1 class="mt-2 text-2xl font-bold text-gray-900">Continue monitoring your submission</h1>
            <p class="mt-3 text-sm text-gray-600">
              Open the submission monitor to see processing progress, download results, or review any errors. Opening the monitor will not submit your files again.
            </p>
          </div>
          <div class="rounded-full bg-indigo-100 p-3">
            <svg class="h-6 w-6 text-indigo-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
        </div>

        <div v-if="hasSession" class="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <dl class="grid gap-3 sm:grid-cols-3 text-sm">
            <div>
              <dt class="text-slate-500">Session</dt>
              <dd class="mt-1 font-medium text-slate-900">{{ sessionIdLabel }}</dd>
            </div>
            <div>
              <dt class="text-slate-500">Submission</dt>
              <dd class="mt-1 font-medium text-slate-900">{{ submissionIdLabel }}</dd>
            </div>
            <div>
              <dt class="text-slate-500">Pipeline run</dt>
              <dd class="mt-1 font-medium text-slate-900 break-all">{{ runIdLabel }}</dd>
            </div>
          </dl>
        </div>

        <LoadingSpinner v-if="restoring" class="mt-6" text="Loading your saved submission…" />
        <div v-else-if="restoreError" role="alert" class="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <p>{{ restoreError }}</p>
          <button type="button" class="mt-3 font-semibold underline" @click="restoreSession">Try again</button>
        </div>
        <p v-else-if="!hasSession" class="mt-6 text-sm text-gray-600">
          No submission is selected. Choose a saved submission from your dashboard to resume it.
        </p>

        <div class="mt-8 flex flex-col gap-3 sm:flex-row sm:justify-end">
          <button
            type="button"
            class="px-4 py-2 text-sm font-medium border border-slate-300 rounded-lg text-slate-700 hover:bg-slate-50"
            @click="router.push('/dashboard')"
          >
            Go to Dashboard
          </button>
          <button
            type="button"
            class="px-4 py-2 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
            v-if="hasSession"
            :disabled="restoring || Boolean(restoreError)"
            @click="router.push(resumeLocation)"
          >
            Open Submission Monitor
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import { useWorkflowStore } from '@/stores/workflow'
import { buildWorkflowResumeLocation, restoreWorkflowContext, shouldRestoreWorkflowContext } from '@/utils/workflowState'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()

const restoring = ref(false)
const restoreError = ref('')
const hasSession = computed(() => {
  const id = Number(route.query.sessionId || workflowStore.sessionId)
  return Number.isSafeInteger(id) && id > 0
})

const sessionIdLabel = computed(() => String(route.query.sessionId || workflowStore.sessionId || 'Unknown'))
const submissionIdLabel = computed(() => String(route.query.submissionId || 'Not attached'))
const runIdLabel = computed(() => String(route.query.runId || 'Not attached'))
const resumeLocation = computed(() => buildWorkflowResumeLocation(
  route.query.sessionId || workflowStore.sessionId,
  {
    resume_route: '/workflow/submit',
    submission_id: route.query.submissionId,
    pipeline_run_id: route.query.runId,
  },
  '/workflow/submit'
))

const restoreSession = async () => {
  const resumeSessionId = Number(route.query.sessionId || workflowStore.sessionId)
  restoreError.value = ''
  if (!hasSession.value) return
  if (shouldRestoreWorkflowContext(workflowStore, resumeSessionId, { force: route.query.resume === 'workflow' })) {
    restoring.value = true
    try {
      await restoreWorkflowContext(workflowStore, resumeSessionId, { includeDraft: true })
    } catch (err) {
      restoreError.value = 'Could not load this submission. Check your connection and try again, or choose a submission from your dashboard.'
    } finally {
      restoring.value = false
    }
  }
}

onMounted(restoreSession)
</script>
