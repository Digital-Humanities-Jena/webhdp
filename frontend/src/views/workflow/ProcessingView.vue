<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-3xl mx-auto px-4">
      <div class="bg-white shadow rounded-lg p-8">
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-700">Processing Handoff</p>
            <h1 class="mt-2 text-2xl font-bold text-gray-900">Submission monitoring moved into the submit screen</h1>
            <p class="mt-3 text-sm text-gray-600">
              This route is now a stable handoff page instead of a redirect shell. Open the canonical submission monitor to continue tracking the active run or failed terminal state.
            </p>
          </div>
          <div class="rounded-full bg-indigo-100 p-3">
            <svg class="h-6 w-6 text-indigo-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
        </div>

        <div class="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
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

        <div class="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <p class="text-sm font-semibold text-amber-900">Record lifecycle reminder</p>
          <p class="mt-1 text-sm text-amber-800">
            Upload does not create Zenodo records. Record creation or reuse happens at submit time under the resolved publishing context.
          </p>
        </div>

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
            class="px-4 py-2 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700"
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
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useWorkflowStore } from '@/stores/workflow'
import { buildWorkflowResumeLocation, restoreWorkflowContext, shouldRestoreWorkflowContext } from '@/utils/workflowState'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()

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

onMounted(async () => {
  const resumeSessionId = Number.parseInt(route.query.sessionId, 10)
  if (shouldRestoreWorkflowContext(workflowStore, resumeSessionId, { force: route.query.resume === 'workflow' })) {
    try {
      await restoreWorkflowContext(workflowStore, resumeSessionId, { includeDraft: true })
    } catch (err) {
      console.warn('Failed to restore workflow context on processing handoff page:', err)
    }
  }
})
</script>
