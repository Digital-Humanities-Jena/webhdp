<template>
  <aside class="space-y-4 2xl:sticky 2xl:top-28 2xl:max-h-[calc(100vh-8rem)] 2xl:overflow-y-auto">
    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Validation</h2>
      <p class="mt-2 text-sm text-slate-500">
        Server diagnostics for mappings, triggers, and publish readiness.
      </p>
      <div class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="font-medium text-slate-700">Status</span>
          <span :class="!validationResult ? 'text-slate-500' : validationResult.valid ? 'text-emerald-700' : 'text-rose-700'" class="font-semibold">
            {{ validationResult ? (validationResult.valid ? 'Passed' : 'Needs attention') : 'Not checked for current edits' }}
          </span>
        </div>
        <div class="mt-2 flex items-center justify-between text-slate-600">
          <span>Errors</span>
          <span>{{ validationResult?.errors?.length || 0 }}</span>
        </div>
        <div class="mt-1 flex items-center justify-between text-slate-600">
          <span>Warnings</span>
          <span>{{ validationResult?.warnings?.length || 0 }}</span>
        </div>
      </div>
      <div v-if="validationResult?.errors?.length" class="mt-4 space-y-2">
        <div v-for="message in validationResult.errors" :key="message" class="rounded-2xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {{ message }}
        </div>
      </div>
      <div v-if="validationResult?.warnings?.length" class="mt-4 space-y-2">
        <div v-for="message in validationResult.warnings" :key="message" class="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
          {{ message }}
        </div>
      </div>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Preflight</h2>
      <p class="mt-2 text-sm text-slate-500">
        Simulate trigger matching and input resolution against sample files without running heavy processing steps.
      </p>
      <div class="mt-4 space-y-3">
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Session ID</label>
          <input aria-label="Preflight session ID" v-model.trim="preflightSessionIdModel" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" data-testid="preflight-session-id" />
        </div>
        <div v-if="preflightSessionId" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div class="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div class="text-sm font-medium text-slate-900">Session Context</div>
              <div class="mt-1 text-xs text-slate-500">
                {{ constructorSessionFiles.length }} files and {{ constructorSessionDirectories.length }} directories available for constructor-backed path fields.
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-3">
              <button
                type="button"
                class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-white disabled:opacity-50"
                :disabled="loadingSessionPaths"
                @click="$emit('refresh-session-resources')"
              >
                {{ loadingSessionPaths ? 'Refreshing…' : 'Refresh Paths' }}
              </button>
              <LoadingSpinner v-if="loadingSessionPaths" size="sm" text="Loading session paths..." />
            </div>
          </div>
        </div>
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Local File Paths</label>
          <textarea
            aria-label="Preflight file paths"
            v-model="preflightFilePathsTextModel"
            rows="8"
            class="w-full rounded-2xl border border-slate-300 px-3 py-2 font-mono text-xs"
            placeholder="/abs/path/model.glb&#10;/abs/path/pointcloud.ply"
            data-testid="preflight-local-file-paths"
          />
        </div>
        <SessionPathPicker
          v-if="constructorSessionFiles.length > 0"
          title="Session Files"
          description="Filter session files, toggle them into the preflight list, or bulk-append matching files."
          :items="constructorSessionFiles"
          :selected-items="selectedPreflightPaths"
          item-label="files"
          selection-mode="multiple"
          item-action-label="Add"
          selected-action-label="Added"
          search-placeholder="Filter preflight session files"
          :bulk-actions="bulkActions"
          data-testid-prefix="preflight-session-files"
          @toggle="togglePreflightFilePath"
          @bulk-action="handleBulkAction"
        />
      </div>

      <button type="button" class="mt-4 w-full rounded-xl border border-indigo-300 px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50" :disabled="!preflightSessionId || !selectedPreflightPaths.length" @click="$emit('run-preflight')">Check selected files</button>
      <p v-if="preflightResult" role="status" class="mt-3 text-sm" :class="preflightResult.valid ? 'text-emerald-700' : 'text-rose-700'">{{ preflightResult.valid ? 'Preflight passed for the current files.' : 'Preflight needs attention. Review the validation and file diagnostics.' }}</p>

      <div v-if="preflightResult?.steps?.length" class="mt-4 space-y-3">
        <article
          v-for="step in preflightResult.steps"
          :key="step.step_id"
          class="rounded-2xl border border-slate-200 bg-slate-50 p-4"
          :data-testid="`preflight-step-${step.step_id}`"
        >
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-slate-900">{{ step.step_id }}</h3>
            <span class="rounded-full bg-white px-2 py-1 text-[11px] font-medium text-slate-600">{{ step.scope }}</span>
          </div>
          <div v-if="step.buckets?.length" class="mt-3 text-xs text-slate-600">
            Buckets:
            <span class="font-medium text-slate-900">{{ step.buckets.length }}</span>
          </div>
          <div v-if="getPreflightBucketWarnings(step).length" class="mt-3 space-y-2">
            <div
              v-for="warning in getPreflightBucketWarnings(step)"
              :key="warning.key"
              class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
              :data-testid="`preflight-warning-${step.step_id}-${warning.index}`"
            >
              <div class="font-semibold text-amber-900">Bucket {{ warning.bucketIndex }}</div>
              <div class="mt-1">{{ warning.message }}</div>
              <div v-if="warning.recordPaths.length" class="mt-1 break-all text-[11px] text-amber-700">
                Records: {{ warning.recordPaths.join(', ') }}
              </div>
            </div>
          </div>
          <div class="mt-3 space-y-2">
            <div
              v-for="record in step.records"
              :key="`${step.step_id}-${record.record_path}`"
              class="rounded-xl border border-white bg-white px-3 py-2 text-xs text-slate-600"
            >
              <div class="break-all font-medium text-slate-900">{{ record.record_path }}</div>
              <div class="mt-1">Action: {{ record.action }}<span v-if="record.matched_rule_id"> | Rule: {{ record.matched_rule_id }}</span></div>
              <div class="mt-1 break-all">Inputs: {{ JSON.stringify(record.resolved_inputs) }}</div>
            </div>
          </div>
        </article>
      </div>
    </section>
    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Execution</h2>
      <p class="mt-2 text-sm text-slate-500">
        Run the selected pipeline against the same session files used for preflight and inspect the persisted run output.
      </p>
      <button
        type="button"
        class="mt-4 w-full rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-indigo-700 disabled:opacity-50"
        :disabled="Boolean(executionBlockedReason) || executingPipeline || !preflightSessionId || !selectedPreflightPaths.length"
        data-testid="run-pipeline-execution"
        @click="$emit('run-pipeline-execution')"
      >
        {{ executingPipeline ? 'Running...' : 'Run Pipeline' }}
      </button>
      <p v-if="executionBlockedReason" class="mt-3 text-sm text-slate-600">{{ executionBlockedReason }}</p>
      <div v-if="pipelineExecutionError" role="alert" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
        {{ pipelineExecutionError }}
      </div>
      <div v-if="pipelineExecutionSummary" class="mt-4 rounded-2xl border px-4 py-3 text-sm" :class="executionFailed ? 'border-rose-200 bg-rose-50 text-rose-900' : 'border-emerald-200 bg-emerald-50 text-emerald-900'">
        <div class="font-semibold">Run {{ pipelineExecutionRunId || 'completed' }}</div>
        <div class="mt-1">
          {{ pipelineExecutionSummary.successful_count || 0 }} successful,
          {{ pipelineExecutionSummary.failed_count || 0 }} failed,
          {{ pipelineExecutionSummary.processed_count || 0 }} processed.
        </div>
      </div>
      <div v-if="pipelineExecutionRunError" class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
        {{ pipelineExecutionRunError }}
      </div>
      <div v-if="pipelineExecutionRun?.steps?.length" class="mt-4 space-y-2">
        <article
          v-for="step in pipelineExecutionRun.steps"
          :key="`${step.pipeline_step_id}-${step.record_id}-${step.id}`"
          class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
          :data-testid="`execution-step-${step.pipeline_step_id}`"
        >
          <div class="flex items-center justify-between gap-3">
            <span class="font-semibold text-slate-900">{{ stepName(step) }}</span>
            <span :class="step.status === 'completed' ? 'text-emerald-700' : 'text-rose-700'" class="font-medium">{{ step.status }}</span>
          </div>
          <div v-if="Object.keys(stepOutputs(step)).length" class="mt-1 break-all">
            Outputs: {{ JSON.stringify(stepOutputs(step)) }}
          </div>
          <div v-if="step.error" class="mt-1 text-rose-700">{{ step.error }}</div>
        </article>
      </div>
      <div v-if="pipelineExecutionArtifacts.length" class="mt-4">
        <h3 class="text-xs font-semibold uppercase tracking-wide text-slate-500">Artifacts And Reports</h3>
        <div class="mt-2 space-y-2">
          <div
            v-for="artifact in pipelineExecutionArtifacts"
            :key="`${artifact.name}-${artifact.path || artifact.record_id}`"
            class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
          >
            <div class="font-medium text-slate-900">{{ artifact.name }}</div>
            <div v-if="artifact.metadata?.role" class="mt-1">{{ artifact.metadata.role }}</div>
            <div v-if="artifact.path" class="mt-1 break-all font-mono text-[11px]">{{ artifact.path }}</div>
          </div>
        </div>
      </div>
    </section>

  </aside>
</template>

<script setup>
import { computed } from 'vue'
import SessionPathPicker from '@/components/ui/SessionPathPicker.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'

const props = defineProps({
  executionBlockedReason: { type: String, default: '' },
  validationResult: {
    type: Object,
    default: null,
  },
  preflightResult: {
    type: Object,
    default: null,
  },
  preflightSessionId: {
    type: String,
    required: true,
  },
  preflightFilePathsText: {
    type: String,
    required: true,
  },
  constructorSessionFiles: {
    type: Array,
    required: true,
  },
  constructorSessionDirectories: {
    type: Array,
    required: true,
  },
  loadingSessionPaths: {
    type: Boolean,
    default: false,
  },
  executingPipeline: {
    type: Boolean,
    default: false,
  },
  pipelineExecutionResult: {
    type: Object,
    default: null,
  },
  pipelineExecutionRun: {
    type: Object,
    default: null,
  },
  pipelineExecutionError: {
    type: String,
    default: '',
  },
})

const emit = defineEmits([
  'update:preflight-session-id',
  'update:preflight-file-paths-text',
  'refresh-session-resources',
  'run-pipeline-execution',
  'run-preflight',
])

const preflightSessionIdModel = computed({
  get: () => props.preflightSessionId,
  set: (value) => emit('update:preflight-session-id', value),
})

const preflightFilePathsTextModel = computed({
  get: () => props.preflightFilePathsText,
  set: (value) => emit('update:preflight-file-paths-text', value),
})

const selectedPreflightPaths = computed(() => (
  String(props.preflightFilePathsText || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
))

const bulkActions = [
  { id: 'append_all_matching', label: 'Append All Matching' },
  { id: 'replace_all_matching', label: 'Replace With Matching' },
]

const pipelineExecutionSummary = computed(() => (
  props.pipelineExecutionResult?.result?.summary
  || props.pipelineExecutionRun?.result?.summary
  || null
))

const executionFailed = computed(() => Boolean(props.pipelineExecutionError || props.pipelineExecutionRun?.status === 'failed' || pipelineExecutionSummary.value?.failed_count > 0))

const pipelineExecutionRunId = computed(() => (
  props.pipelineExecutionRun?.run_id
  || props.pipelineExecutionResult?.run_id
  || props.pipelineExecutionResult?.result?.run_id
  || ''
))

const pipelineExecutionRunError = computed(() => (
  props.pipelineExecutionRun?.error
  || props.pipelineExecutionResult?.result?.error
  || ''
))

const pipelineExecutionArtifacts = computed(() => props.pipelineExecutionRun?.artifacts || [])

function stepOutputs(step) {
  return step?.result?.outputs || {}
}

function stepName(step) {
  return step?.step_key || step?.component_key || step?.pipeline_step_id || step?.id || 'step'
}

function setPreflightPaths(paths) {
  preflightFilePathsTextModel.value = paths.join('\n')
}

function togglePreflightFilePath(path) {
  const values = new Set(selectedPreflightPaths.value)
  if (values.has(path)) {
    values.delete(path)
  } else {
    values.add(path)
  }
  setPreflightPaths(Array.from(values))
}

function handleBulkAction({ id, items }) {
  if (id === 'append_all_matching') {
    const values = new Set(selectedPreflightPaths.value)
    items.forEach((item) => values.add(item))
    setPreflightPaths(Array.from(values))
    return
  }
  if (id === 'replace_all_matching') {
    setPreflightPaths(items)
  }
}

function getPreflightBucketWarnings(step) {
  return (step?.buckets || []).flatMap((bucket, bucketIndex) =>
    (bucket?.warnings || []).map((message, warningIndex) => ({
      key: `${step.step_id}-${bucket.bucket_key || bucketIndex}-${warningIndex}-${message}`,
      index: `${bucketIndex}-${warningIndex}`,
      bucketIndex: bucketIndex + 1,
      message,
      recordPaths: Array.isArray(bucket?.record_paths) ? bucket.record_paths : [],
    }))
  )
}
</script>
