<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-4xl mx-auto px-4">
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">Submit for Processing</h1>
        <p class="mt-2 text-gray-600">{{ usesZenodo ? 'Review your files, processing tasks and Zenodo destination.' : 'Review your files and processing tasks. Generated files will be saved with your session.' }}</p>
      </div>

      <StepIndicator :batch-mode="workflowStore.isBatchMode" :current-step="7" />

      <div class="bg-white shadow rounded-lg p-6">

        <div v-if="!processing && !success">
          <h2 class="text-xl font-semibold text-gray-900 mb-6">Submission Summary</h2>
          <div v-if="recoveryPlan" class="mb-4 rounded-lg border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-900">
            <p>Continue {{ recoveryPlan.record_ids.length }} record{{ recoveryPlan.record_ids.length === 1 ? '' : 's' }} using pipeline version {{ recoveryPlan.pipeline_version }}. Unchanged, verified outputs are reused; failed work and affected dependencies run again.</p>
            <p v-if="recoveryPlan.whole_batch" class="mt-1">This batch component needs the original record group.</p>
            <p v-if="recoveryPlan.unregistered_sources?.length" class="mt-2">{{ recoveryPlan.unregistered_sources.length }} source{{ recoveryPlan.unregistered_sources.length === 1 ? ' was' : 's were' }} not registered before the interruption. <RouterLink :to="`/workflow/files?sessionId=${recoveryPlan.session_id}&resume=workflow`" class="underline">Review unregistered sources in Files</RouterLink>.</p>
            <p v-if="recoveryPlan.unregistered_record_ids?.length" class="mt-2">{{ recoveryPlan.unregistered_record_ids.length }} selected record{{ recoveryPlan.unregistered_record_ids.length === 1 ? ' was' : 's were' }} not prepared before the interruption. <RouterLink :to="`/sessions/${recoveryPlan.session_id}/records`" class="underline">Review the remaining records in Session Records</RouterLink>.</p>
            <p v-for="record in recoveryPlan.records.filter(record => !record.eligible)" :key="record.record_id" class="mt-2">{{ record.reason }} <RouterLink :to="record.route" class="underline">Review record {{ record.record_id }}</RouterLink></p>
          </div>
          <SubmissionOutcomes v-if="submissionOutcomes && !recoveryPlan" :outcomes="submissionOutcomes" class="mb-6" />
          <div v-if="error && error !== readinessError" role="alert" class="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
            <p>{{ error }}</p>
            <ul v-if="recordFailures.length" class="mt-2 list-inside list-disc space-y-1">
              <li v-for="(failure, index) in recordFailures" :key="index">{{ failure.message }}</li>
            </ul>
            <RouterLink v-if="!pipelineConfig" to="/workflow/pipeline" class="inline-flex min-h-11 items-center font-medium underline">Choose an available pipeline</RouterLink>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <!-- Left: Info Column -->
            <div class="space-y-6">
              <div class="p-4 bg-gray-50 rounded-lg border border-gray-200">
                <dl class="space-y-2 text-sm">
                  <div class="flex justify-between">
                    <dt class="text-gray-600">Selected bundles:</dt>
                    <dd class="font-medium text-gray-900">{{ workflowStore.selectedFiles.length }}</dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-gray-600">Record mode:</dt>
                    <dd class="font-medium text-gray-900 min-w-0 break-words text-right ml-4">
                      {{ submissionPlan.title }}
                    </dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-gray-600">Submission Title:</dt>
                    <dd class="font-medium text-gray-900 min-w-0 break-words text-right ml-4">
                      {{ workflowStore.submissionMetadata.title || 'Untitled Submission' }}
                    </dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-gray-600">Pipeline:</dt>
                    <dd class="font-medium text-gray-900">
                      {{ pipelineConfig?.name || workflowStore.selectedPipeline?.name || PIPELINE_ID || 'render' }}
                    </dd>
                  </div>
                  <div v-if="workflowStore.isBatchMode" class="pt-2 mt-2 border-t border-gray-100 flex items-center text-indigo-600 font-medium">
                    <svg class="h-4 w-4 mr-2" fill="currentColor" viewBox="0 0 20 20">
                      <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" />
                    </svg>
                    <span>Per-file MSF metadata applied</span>
                  </div>
                </dl>
              </div>

              <div class="p-4 rounded-lg border" :class="submissionPlanCardClass">
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <h3 class="text-sm font-medium text-gray-900">Record lifecycle</h3>
                    <p class="mt-1 text-xs text-gray-500">Upload registered the files only. Records are created or reused when you confirm submission.</p>
                  </div>
                  <span class="rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide" :class="submissionPlanBadgeClass">
                    {{ submissionPlanBadgeLabel }}
                  </span>
                </div>
                <p class="mt-3 text-sm" :class="submissionPlanTextClass">
                  {{ submissionPlan.description }}
                </p>
                <p v-if="submissionPlanLoading" class="mt-2 text-xs text-gray-500">
                  Checking whether this selection can reuse existing canonical records...
                </p>
              </div>

              <div
                v-if="workflowStore.isBatchMode && recordResolutionState"
                class="p-4 rounded-lg border border-sky-200 bg-sky-50"
              >
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <h3 class="text-sm font-medium text-gray-900">Batch record plan</h3>
                    <p class="mt-1 text-xs text-gray-500">
                      This summary is derived from the saved record-resolution decisions for the selected bundles.
                    </p>
                  </div>
                  <span class="rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide bg-white border border-sky-200 text-sky-700">
                    {{ recordResolutionState.policy_preset || 'balanced' }}
                  </span>
                </div>
                <div class="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div class="rounded-md border border-white/80 bg-white p-3">
                    <p class="text-xs uppercase tracking-wide text-slate-500">Version</p>
                    <p class="mt-1 font-semibold text-slate-900">{{ batchResolutionSummary?.create_version || 0 }}</p>
                  </div>
                  <div class="rounded-md border border-white/80 bg-white p-3">
                    <p class="text-xs uppercase tracking-wide text-slate-500">Fresh</p>
                    <p class="mt-1 font-semibold text-slate-900">{{ batchResolutionSummary?.create_fresh_record || 0 }}</p>
                  </div>
                  <div class="rounded-md border border-white/80 bg-white p-3">
                    <p class="text-xs uppercase tracking-wide text-slate-500">Forced fresh</p>
                    <p class="mt-1 font-semibold text-slate-900">{{ batchResolutionSummary?.force_create_fresh || 0 }}</p>
                  </div>
                  <div class="rounded-md border border-white/80 bg-white p-3">
                    <p class="text-xs uppercase tracking-wide text-slate-500">Skip</p>
                    <p class="mt-1 font-semibold text-slate-900">{{ batchResolutionSummary?.skip || 0 }}</p>
                  </div>
                  <div class="rounded-md border border-white/80 bg-white p-3">
                    <p class="text-xs uppercase tracking-wide text-slate-500">Unresolved</p>
                    <p class="mt-1 font-semibold" :class="batchResolutionSummary?.unresolved ? 'text-amber-700' : 'text-emerald-700'">
                      {{ batchResolutionSummary?.unresolved || 0 }}
                    </p>
                  </div>
                </div>
                <p v-if="batchResolutionBlockedReason" class="mt-3 text-sm text-amber-700">
                  {{ batchResolutionBlockedReason }}
                </p>
              </div>

              <div class="p-4 bg-slate-50 rounded-lg border border-slate-200">
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <h3 class="text-sm font-medium text-gray-900">Publishing context</h3>
                    <p class="mt-1 text-xs text-gray-500">
                      Local records are created or reused under this session workspace and credential source.
                    </p>
                  </div>
                  <span class="rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide bg-white border border-slate-200 text-slate-700">
                    {{ publishingContextBadge }}
                  </span>
                </div>
                <dl class="mt-3 space-y-2 text-sm">
                  <div class="flex justify-between">
                    <dt class="text-gray-600">Workspace:</dt>
                    <dd class="font-medium text-gray-900 min-w-0 break-words text-right ml-4">{{ workspaceSummaryLabel }}</dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-gray-600">Credential source:</dt>
                    <dd class="font-medium text-gray-900 min-w-0 break-words text-right ml-4">{{ credentialSourceLabel }}</dd>
                  </div>
                  <div class="flex justify-between">
                    <dt class="text-gray-600">Session default environment:</dt>
                    <dd class="font-medium text-gray-900 min-w-0 break-words text-right ml-4">{{ defaultEnvironmentLabel }}</dd>
                  </div>
                </dl>
              </div>

              <fieldset v-if="usesZenodo" class="p-4 bg-blue-50 rounded-lg border border-blue-200" :disabled="isBatchExecutionEnvironmentLocked || submitting">
                <legend class="px-1 text-sm font-semibold text-gray-900">Zenodo destination</legend>
                <div class="grid gap-3 sm:grid-cols-2">
                  <label class="flex cursor-pointer items-start gap-2 rounded-md border border-blue-200 bg-white p-3 text-sm">
                    <input type="radio" name="zenodo-environment" class="mt-1 text-indigo-600" :checked="effectiveExecutionEnvironmentIsSandbox" @change="isSandbox = true" />
                    <span><span class="block font-medium text-gray-900">Sandbox</span><span class="text-xs text-gray-600">Test repository</span></span>
                  </label>
                  <label class="flex cursor-pointer items-start gap-2 rounded-md border border-blue-200 bg-white p-3 text-sm">
                    <input type="radio" name="zenodo-environment" class="mt-1 text-indigo-600" :checked="!effectiveExecutionEnvironmentIsSandbox" @change="isSandbox = false" />
                    <span><span class="block font-medium text-gray-900">Production</span><span class="text-xs text-gray-600">Zenodo repository</span></span>
                  </label>
                </div>
                <p v-if="isBatchExecutionEnvironmentLocked" class="mt-3 text-sm text-gray-600">This batch uses the destination chosen at upload, where its existing records were checked.</p>
              </fieldset>

              <div
                v-if="hpcComponentKeys.length > 0"
                class="p-4 rounded-lg border"
                :class="hpcPreflightState === 'failed' ? 'border-rose-200 bg-rose-50' : 'border-slate-200 bg-slate-50'"
              >
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <h3 class="text-sm font-medium text-gray-900">{{ componentPreflightTitle }}</h3>
                    <p class="mt-1 text-xs" :class="hpcPreflightState === 'failed' ? 'text-rose-700' : 'text-gray-500'">
                      {{ hpcPreflightMessage }}
                    </p>
                  </div>
                  <span class="rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide"
                    :class="{
                      'bg-white border border-slate-200 text-slate-700': hpcPreflightState === 'idle',
                      'bg-indigo-100 text-indigo-700': hpcPreflightState === 'checking',
                      'bg-emerald-100 text-emerald-700': hpcPreflightState === 'ready',
                      'bg-rose-100 text-rose-700': hpcPreflightState === 'failed'
                    }"
                  >
                    {{ hpcPreflightState }}
                  </span>
                </div>
                <ProgressBar v-if="hpcPreflightState === 'checking'" class="mt-3" :label="componentPreflightTitle" :show-label="false" />
                <ReservedGpuAccess
                  v-if="workflowStore.sessionId"
                  class="mt-3"
                  :session-id="workflowStore.sessionId"
                  :disabled="submitting || processing || readinessBusy"
                  @claimed="onReservedGpuChanged($event)"
                  @released="onReservedGpuChanged(null)"
                />
              </div>

              <div v-if="!isUsdzDisabled" class="p-4 bg-rose-50 rounded-lg border border-rose-200">
                <div class="flex items-center justify-between">
                  <div class="pr-3">
                    <h3 class="text-sm font-medium text-gray-900">Critical Error Policy</h3>
                    <p class="text-xs text-gray-500 mt-0.5">
                      If USDZ conversion fails, decide whether to continue remaining files or stop immediately.
                    </p>
                  </div>
                  <div class="flex items-center">
                    <span class="mr-2 text-xs font-medium" :class="!abortOnCriticalError ? 'text-gray-900' : 'text-gray-400'">Continue</span>
                    <button
                      type="button"
                      class="relative inline-flex h-5 w-10 border-2 border-transparent rounded-full cursor-pointer transition-colors ease-in-out duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-rose-500"
                      :class="abortOnCriticalError ? 'bg-rose-600' : 'bg-gray-200'"
                      role="switch"
                      aria-label="Stop processing if USDZ conversion fails"
                      :aria-checked="abortOnCriticalError"
                      @click="abortOnCriticalError = !abortOnCriticalError"
                    >
                      <span aria-hidden="true" :class="[abortOnCriticalError ? 'translate-x-5' : 'translate-x-0', 'pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform ring-0 transition ease-in-out duration-200']"></span>
                    </button>
                    <span class="ml-2 text-xs font-medium" :class="abortOnCriticalError ? 'text-gray-900' : 'text-gray-400'">Abort</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Right: Pipeline Visualization -->
            <div class="bg-gray-50 rounded-lg border border-gray-200 p-4">
              <h3 class="text-sm font-medium text-gray-900 mb-4">Pipeline Workflow</h3>

              <div v-if="loadingPipeline" class="flex justify-center py-4">
                <LoadingSpinner size="sm" />
              </div>

              <div v-else-if="pipelineConfig?.steps" class="space-y-4">
                <div v-for="(step, index) in activeSteps" :key="step.id" class="relative flex items-start">
                  <!-- Connector line -->
                  <div v-if="index !== activeSteps.length - 1" class="absolute left-3.5 top-8 bottom-0 w-0.5 bg-indigo-200" aria-hidden="true"></div>

                  <div class="flex-shrink-0 relative">
                    <span class="flex items-center justify-center h-7 w-7 rounded-full bg-indigo-100 text-indigo-600 font-bold text-xs border border-indigo-200 z-10 relative">
                      {{ index + 1 }}
                    </span>
                  </div>

                  <div class="ml-4 min-w-0 flex-1">
                    <h4 class="text-xs font-semibold text-gray-900">{{ step.name }}</h4>
                    <p class="text-[10px] text-gray-500 line-clamp-1">{{ step.description }}</p>
                  </div>
                </div>

                <div v-if="activeSteps.length === 0" class="text-center py-4 text-xs text-gray-400 italic">
                  No steps configured.
                </div>
              </div>

              <div v-else class="text-center py-4 text-xs text-gray-400">
                Default processing will be applied.
              </div>
            </div>
          </div>

          <section class="mt-6 rounded-lg border border-slate-200 bg-slate-50 p-4" aria-labelledby="readiness-title" data-testid="submission-readiness" :aria-busy="readinessBusy">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h3 id="readiness-title" class="text-sm font-medium text-gray-900">Submission readiness</h3>
              <button type="button" class="min-h-11 text-sm text-indigo-700 underline disabled:opacity-50" :disabled="loadingPipeline || !pipelineConfig || readinessBusy || submitting" @click="checkReadiness">Check again</button>
            </div>
            <p class="text-sm text-slate-700" role="status" aria-live="polite">{{ readinessBusy ? readinessProgress ? `Checked ${readinessProgress.checked} of ${readinessProgress.total} selected sources…` : 'Checking selected sources and saved settings…' : readinessResult?.ready ? `Local checks passed for ${readinessResult.selected_count} selected source${readinessResult.selected_count === 1 ? '' : 's'}.` : readinessResult?.blockers?.length ? 'Resolve the items below before processing.' : 'Readiness is unverified. Use Check again before processing.' }}</p>
            <ul v-if="readinessResult?.blockers?.length" class="mt-3 space-y-2 text-sm text-rose-800">
              <li v-for="(item, index) in readinessResult.blockers" :key="index" class="break-words">
                <span v-if="item.source" class="font-medium break-all">{{ item.source }}: </span><span v-if="item.step">{{ item.step }} — </span>{{ item.message }}
                <RouterLink :to="item.route" class="ml-1 inline-flex min-h-11 items-center font-medium underline">Review {{ readinessArea(item.route) }}</RouterLink>
              </li>
            </ul>
            <p v-if="readinessError" class="mt-2 text-sm text-rose-800" role="alert">{{ readinessError }}</p>
            <details v-if="readinessResult?.unverified?.length" class="mt-3 text-sm text-slate-600">
              <summary class="cursor-pointer">Checks still unverified</summary>
              <ul class="mt-2 space-y-2"><li v-for="(item, index) in readinessResult.unverified" :key="index"><span v-if="item.step" class="font-medium">{{ item.step }}: </span>{{ item.message }}</li></ul>
            </details>
            <p class="mt-2 text-xs text-slate-500">This check creates no drafts or jobs. Processing rechecks the sources and settings before making changes.</p>
          </section>

          <!-- Warnings Based on Steps -->
          <div v-if="isRendererDisabled" class="mt-6 p-4 bg-amber-50 border-l-4 border-amber-400 rounded-r-lg">
            <div class="flex">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-amber-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="ml-3">
                <p class="text-xs text-amber-700">
                  <span class="font-bold">Note:</span> Visual rendering is currently <span class="uppercase font-bold">Disabled</span> in the pipeline settings. Your models will be submitted without 2D preview renders.
                </p>
              </div>
            </div>
          </div>

          <div class="mt-8 flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
            <button
              @click="handleBack"
              class="px-6 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 transition-colors"
            >
              ← Back
            </button>
            <button
              @click="handleSubmit"
              :disabled="loadingPipeline || submitting || readinessBusy || !readinessResult?.ready || Boolean(batchResolutionBlockedReason)"
              data-testid="submit-confirm"
              class="px-6 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors shadow-sm"
            >
              {{ loadingPipeline ? 'Loading summary…' : submitting ? 'Submitting...' : 'Confirm & Process →' }}
            </button>
          </div>
        </div>

        <div v-if="processing" class="text-center py-12">
          <div class="mb-8">
            <LoadingSpinner v-if="!monitoringStopped" size="lg" text="Processing submission..." />
            <p role="status" class="mt-4 text-sm text-indigo-700 font-medium">{{ monitoringStopped ? 'Progress monitoring stopped' : statusMessage }}</p>
          </div>

          <div v-if="monitorUnavailable" role="status" class="max-w-md mx-auto mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-left text-sm text-amber-900">
            <template v-if="monitoringStopped">
              This run is no longer accessible. Processing may still be running; do not submit it again.
              <div class="mt-2 flex gap-4">
                <button type="button" class="underline" @click="startProgressPolling">Check access again</button>
                <router-link to="/dashboard" class="underline">Return to sessions</router-link>
              </div>
            </template>
            <template v-else>Progress updates are temporarily unavailable. Processing may still be running. Reconnecting automatically; you do not need to submit again.</template>
          </div>
          <div v-if="pendingRun && !pendingRun.confirmed" class="mb-4">
            <button type="button" :disabled="submitting" class="text-indigo-700 underline disabled:opacity-50" @click="retryPendingRun">Retry this request</button>
            <p class="text-sm text-slate-600">This uses the same operation ID and will reconnect if processing has already started.</p>
          </div>
          <div v-if="nativeRunStatus === 'pending'" class="mb-4">
            <button type="button" :disabled="cancellingNativeRun" class="text-indigo-700 underline disabled:opacity-50" @click="cancelNativeRun">{{ cancellingNativeRun ? 'Cancelling…' : 'Cancel queued run' }}</button>
          </div>
          <p v-if="workflowSaveWarning" role="status" class="max-w-md mx-auto mb-4 text-sm text-amber-800">{{ workflowSaveWarning }}</p>
          <ProgressBar v-if="!monitoringStopped" class="max-w-md mx-auto mb-6" :percentage="processingProgress?.percent" label="Processing progress" />

          <div v-if="processingProgress" class="max-w-md mx-auto mb-6 text-left bg-indigo-50 border border-indigo-100 rounded-lg p-4">
            <dl class="space-y-2 text-xs">
              <div class="flex justify-between items-start">
                <dt class="text-indigo-700 font-medium">Current File</dt>
                <dd class="text-gray-900 font-medium ml-4 min-w-0 break-all">{{ processingFileName || 'Waiting...' }}</dd>
              </div>
              <div v-if="processingCounter" class="flex justify-between">
                <dt class="text-indigo-700 font-medium">Progress</dt>
                <dd class="text-gray-900">{{ processingCounter }}</dd>
              </div>
              <div class="flex justify-between">
                <dt class="text-indigo-700 font-medium">Stage</dt>
                <dd class="text-gray-900">{{ formattedCurrentStage }}</dd>
              </div>
              <div v-if="zenodoDraftRecordId" class="flex justify-between">
                <dt class="text-indigo-700 font-medium">Zenodo Record ID</dt>
                <dd class="text-gray-900 font-mono">{{ zenodoDraftRecordId }}</dd>
              </div>
            </dl>
          </div>

          <div v-if="converterRuntimeWarnings.length" class="max-w-2xl mx-auto mb-6 text-left bg-amber-50 border border-amber-200 rounded-lg p-4">
            <h4 class="text-xs font-semibold text-amber-800 uppercase tracking-wider mb-2">USDZ Converter Warnings</h4>
            <ul class="space-y-1 text-xs text-amber-800">
              <li v-for="(warning, idx) in converterRuntimeWarnings" :key="`runtime-warning-${idx}`">
                {{ warning.message }}
              </li>
            </ul>
          </div>

          <!-- Processing Steps Visualization -->
          <div class="max-w-xs mx-auto text-left">
            <div v-for="(step, index) in activeSteps" :key="'proc-'+step.id" class="flex items-center mb-3">
              <div :class="[isCurrentStep(index) ? 'bg-indigo-600 animate-pulse' : 'bg-gray-200', 'h-2 w-2 rounded-full mr-3']"></div>
              <span :class="[isCurrentStep(index) ? 'text-indigo-900 font-medium' : 'text-gray-400', 'text-xs']">{{ step.name }}</span>
            </div>
          </div>
        </div>

        <div v-else-if="success" class="text-center py-8">
          <div class="flex justify-center">
            <div :class="[hasAnyWarnings ? 'bg-amber-100' : 'bg-green-100', 'rounded-full p-3 mb-4']">
              <svg v-if="!hasAnyWarnings" class="h-12 w-12 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
              </svg>
              <svg v-else class="h-12 w-12 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-7.938 4h15.876c1.54 0 2.503-1.667 1.733-3L13.733 4c-.77-1.333-2.695-1.333-3.465 0L2.33 16c-.77 1.333.193 3 1.732 3z"></path>
              </svg>
            </div>
          </div>
          <h3 class="text-2xl font-bold text-gray-900 mb-2">
            {{ hasAnyWarnings ? 'Processing Complete (With Warnings)' : 'Processing Complete!' }}
          </h3>
          <p class="text-gray-600 mb-8">
            {{ hasAnyWarnings
              ? 'Pipeline finished, but one or more processing steps reported warnings or incomplete output.'
              : usesZenodo ? `Processing finished. Review the generated files and Zenodo record status ${effectiveExecutionEnvironmentIsSandbox ? '(Sandbox)' : ''}.` : 'Processing finished. Open a record in Session Records to download its optimized model, report and previews.' }}
          </p>

          <SubmissionOutcomes :outcomes="submissionOutcomes" class="mb-6" />
          <div v-if="hasConverterWarnings" class="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-6 text-left">
            <h4 class="text-xs font-semibold text-amber-800 uppercase tracking-wider mb-2">Converter Issues</h4>
            <ul class="space-y-1 text-sm text-amber-800">
              <li v-for="(warning, idx) in converterWarnings" :key="`final-warning-${idx}`">
                {{ warning.message }}
              </li>
            </ul>
          </div>

          <div v-if="hasPipelineWarnings" class="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-6 text-left">
            <div class="flex items-start justify-between gap-4 mb-3">
              <h4 class="text-xs font-semibold text-amber-800 uppercase tracking-wider">Pipeline Warnings</h4>
              <p class="text-[11px] text-amber-700">
                {{ pipelineWarnings.length }} unique issue{{ pipelineWarnings.length === 1 ? '' : 's' }},
                {{ pipelineWarningTotalOccurrences }} occurrence{{ pipelineWarningTotalOccurrences === 1 ? '' : 's' }}
              </p>
            </div>

            <div class="space-y-2">
              <details
                v-for="group in pipelineWarningGroups"
                :key="`pipeline-warning-group-${group.groupKey}`"
                class="rounded-md border border-amber-200 bg-white/70"
                :open="group.totalOccurrences <= 4"
              >
                <summary class="cursor-pointer select-none px-3 py-2 flex items-center justify-between gap-3 text-sm text-amber-900">
                  <span class="font-semibold">{{ group.label }}</span>
                  <span class="text-[11px] text-amber-700 whitespace-nowrap">
                    {{ group.uniqueIssues }} issue{{ group.uniqueIssues === 1 ? '' : 's' }},
                    {{ group.totalOccurrences }} occurrence{{ group.totalOccurrences === 1 ? '' : 's' }}
                  </span>
                </summary>

                <div class="px-3 pb-3">
                  <ul class="space-y-2 max-h-56 overflow-y-auto pr-1 text-sm text-amber-900">
                    <li
                      v-for="issue in group.issues"
                      :key="`pipeline-warning-${group.groupKey}-${issue.template}`"
                      class="rounded border border-amber-100 bg-amber-50/70 px-3 py-2"
                    >
                      <p class="font-medium leading-tight">{{ issue.message }}</p>
                      <p class="mt-1 text-[11px] text-amber-700">
                        {{ issue.occurrences }} occurrence{{ issue.occurrences === 1 ? '' : 's' }}
                        <span v-if="issue.affectedFiles > 0">
                          • {{ issue.affectedFiles }} affected record{{ issue.affectedFiles === 1 ? '' : 's' }}
                        </span>
                      </p>
                      <p v-if="issue.sampleFiles.length" class="mt-1 text-[11px] text-amber-700 break-words">
                        Examples: {{ issue.sampleFiles.join(', ') }}
                        <span v-if="issue.affectedFiles > issue.sampleFiles.length">
                          (+{{ issue.affectedFiles - issue.sampleFiles.length }} more)
                        </span>
                      </p>
                    </li>
                  </ul>
                </div>
              </details>
            </div>
          </div>

          <div class="bg-gray-50 rounded-lg p-6 border border-gray-200 mb-8 text-left">
            <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Workflow Summary</h4>
            <details v-if="executionTimingSummary.length" class="mb-4 text-xs">
              <summary class="cursor-pointer text-gray-600">Processing times</summary>
              <div v-for="[key, time] in executionTimingSummary" :key="key" class="flex justify-between p-2 bg-white rounded border border-gray-100">
                <span class="text-gray-500 capitalize">{{ key.replace('_', ' ') }}:</span>
                <span class="font-mono font-bold text-indigo-600">{{ time.toFixed(2) }}s</span>
              </div>
            </details>
            <ul class="space-y-2 text-sm">
              <li class="flex items-center text-green-700">
                <svg class="h-4 w-4 mr-2" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" /></svg>
                Metadata prepared successfully
              </li>
              <li class="flex items-center text-green-700">
                <svg class="h-4 w-4 mr-2" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" /></svg>
                {{ submissionPlan.successSummary }}
              </li>
              <li :class="['flex items-center', renderSummaryClass]">
                <span :class="['mr-2 text-xs font-bold uppercase border rounded px-1', renderSummaryBadgeClass]">{{ renderSummaryBadge }}</span>
                {{ renderSummaryText }}
              </li>

              <li class="flex items-center text-green-700">
                <svg class="h-4 w-4 mr-2" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" /></svg>
                {{ usesZenodo ? 'Files uploaded successfully' : 'Generated files saved with this session' }}
              </li>

              <li :class="['flex items-center', usdzSummaryClass]">
                <span :class="['mr-2 text-xs font-bold uppercase border rounded px-1', usdzSummaryBadgeClass]">{{ usdzSummaryBadge }}</span>
                {{ usdzSummaryText }}
              </li>
            </ul>
          </div>

          <div class="flex flex-col sm:flex-row justify-center space-y-3 sm:space-y-0 sm:space-x-4">
            <button
              @click="router.push(`/sessions/${workflowStore.sessionId}/records`)"
              class="px-8 py-2 bg-indigo-600 text-white rounded-md font-medium hover:bg-indigo-700 transition-colors shadow-sm"
            >
              View records and results
            </button>
            <button
              @click="startNewWorkflow"
              class="px-8 py-2 border border-gray-300 text-gray-700 rounded-md font-medium hover:bg-gray-50 transition-colors"
            >
              Start New Upload
            </button>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import ReservedGpuAccess from '@/components/hpc/ReservedGpuAccess.vue'
import SubmissionOutcomes from '@/components/workflow/SubmissionOutcomes.vue'
import { isPermanentProgressError, progressRetryDelay } from '@/utils/progressMonitoring'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores/workflow'
import { useToast } from '@/composables/useToast'
import fileService from '@/services/file.service'
import pipelineService from '@/services/pipeline.service'
import submissionService from '@/services/submission.service'
import hpcLinkService from '@/services/hpcLink.service'
import StepIndicator from '@/components/workflow/StepIndicator.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import { persistWorkflowState, restoreWorkflowContext, shouldRestoreWorkflowContext } from '@/utils/workflowState'
import {
  applyTerminalProgressState,
  deriveSubmissionPlan,
  resolveRecordResolutionSelections,
} from '@/utils/submissionFlow'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()
const toast = useToast()

const PIPELINE_ID = import.meta.env.VITE_PIPELINE_ID || 'render'

const submitting = ref(false)
const processing = ref(false)
const success = ref(false)
const error = ref('')
const statusMessage = ref('Initializing pipeline...')
const isSandbox = ref(true)
const abortOnCriticalError = ref(false)
const executionTimings = ref(null)
const executionTimingSummary = computed(() => Object.entries(executionTimings.value || {}).filter(([, time]) => typeof time === 'number' && Number.isFinite(time)))
const submissionId = ref(null)
const pipelineRunId = ref(null)
const processingProgress = ref(null)
const progressPollTimer = ref(null)
const converterRuntimeWarnings = ref([])
const converterWarnings = ref([])
const pipelineWarnings = ref([])
const recordFailures = ref([])
const submissionOutcomes = ref(null)
const recoveryPlan = ref(null)
const submissionResult = ref(null)
const sessionContext = ref(null)
const submissionPlan = ref(deriveSubmissionPlan())
const submissionPlanLoading = ref(false)
const recordResolutionState = ref(null)
const recordResolutionLoading = ref(false)
const hpcPreflightState = ref('idle')
const hpcPreflightMessage = ref('HDP Component runtimes will be checked before processing starts.')
const monitorUnavailable = ref(false)
const monitoringStopped = ref(false)
let monitorFailures = 0
let monitorGeneration = 0
const handleMonitorError = (err) => {
  monitorUnavailable.value = true
  monitorFailures += 1
  if (isPermanentProgressError(err)) {
    monitoringStopped.value = true
    stopProgressPolling()
  }
}
const pendingRun = ref(null)
const nativeRunStatus = ref('')
const cancellingNativeRun = ref(false)
async function cancelNativeRun() {
  if (!pipelineRunId.value || nativeRunStatus.value !== 'pending' || cancellingNativeRun.value) return
  cancellingNativeRun.value = true
  try {
    await pipelineService.cancelPipelineRun(pipelineRunId.value)
    await pollNativeRunProgress()
  } catch (err) {
    statusMessage.value = err?.error?.message || err?.message || 'Cancellation could not be confirmed. Reconnecting to the run.'
  } finally {
    cancellingNativeRun.value = false
  }
}
let disposed = false
let nativePollInFlight = false
const workflowSaveWarning = ref('')
const pendingRunKey = () => `guided-pipeline-run:${workflowStore.sessionId}`
function rememberPendingRun() {
  try {
    if (pendingRun.value) sessionStorage.setItem(pendingRunKey(), JSON.stringify(pendingRun.value))
    else sessionStorage.removeItem(pendingRunKey())
  } catch { /* The current page still retains the operation identity. */ }
}
function clearPendingRun() { pendingRun.value = null; rememberPendingRun() }
function saveProcessingState() {
  if (disposed) return Promise.resolve()
  return persistWorkflowState(workflowStore, 'processing', { pipelineRunId: pipelineRunId.value, submissionId: submissionId.value })
    .then(() => { workflowSaveWarning.value = '' })
    .catch(() => { workflowSaveWarning.value = 'Processing is being monitored, but saving your resume state failed. Keep this page open or reconnect to this run.' })
}
async function submitPendingRun() {
  const pending = pendingRun.value
  if (!pending?.request) return
  const request = pending.request
  const options = { ...request.options, requestId: pending.runId }
  try {
    const response = request.kind === 'plan'
      ? await pipelineService.executePipelineWithPlan(request.sessionId, request.identifier, request.targets, request.isSandbox, options)
      : request.kind === 'records'
        ? await pipelineService.executePipeline(request.sessionId, request.identifier, request.targets, request.isSandbox, options)
        : await pipelineService.executePipelineOnFiles(request.sessionId, request.targets, request.isSandbox, request.identifier, options)
    const runId = String(response.data?.run_id || '').trim()
    if (!runId) throw new Error('Submission acknowledgement is unavailable.')
    pending.runId = runId
    pending.confirmed = true
  } catch (err) {
    const existing = err?.error?.details?.run_id || err?.details?.run_id || err?.response?.data?.error?.details?.run_id
    if (existing) {
      pending.runId = existing
      pending.confirmed = true
    } else {
      const code = err?.error?.code || err?.response?.data?.error?.code
      const status = err?.status || err?.response?.status
      if (['VALIDATION_ERROR', 'OPERATION_CONFLICT', 'SECURITY_ERROR', 'FORBIDDEN'].includes(code) || [400, 401, 403, 404, 409, 422].includes(status)) {
        const details = err?.error?.details || err?.response?.data?.error?.details || {}
        readinessResult.value = details.readiness || null
        readinessError.value = err?.error?.message || err?.message || 'Review the submission and check readiness again.'
        clearPendingRun()
        throw err
      }
      monitorUnavailable.value = true
      statusMessage.value = 'Submission could not be confirmed. Reconnect or retry the same request below.'
    }
  }
  rememberPendingRun()
  pipelineRunId.value = pending.runId
  processing.value = true
  startProgressPolling()
  await saveProcessingState()
}
async function retryPendingRun() {
  if (submitting.value) return
  submitting.value = true
  try { await submitPendingRun() }
  catch (err) {
    stopProgressPolling()
    processing.value = false
    error.value = err?.error?.message || err?.message || 'Submission was rejected. Review the settings and try again.'
  } finally { submitting.value = false }
}
const hpcAllocation = ref(null)
const componentRuntimeStatus = ref({})

const pipelineConfig = ref(null)
const pipelineVersion = ref(null)
const loadingPipeline = ref(true)
const readinessResult = ref(null)
const readinessError = ref('')
const readinessBusy = ref(false)
const readinessProgress = ref(null)
let readinessController
let readinessGeneration = 0
let readinessTimer
const readinessArea = (path) => ({ '/workflow/files': 'files and record decisions', '/workflow/metadata': 'metadata', '/workflow/edm-selection': 'metadata mappings', '/workflow/pipeline': 'pipeline', '/workflow/submit': 'run status' }[path?.split('?')[0]] || 'settings')
const readinessInputs = computed(() => JSON.stringify({
  session: workflowStore.sessionId,
  files: workflowStore.selectedFiles, pipeline: workflowStore.selectedPipeline,
  metadata: workflowStore.submissionMetadata, batch: workflowStore.fileMetadataMap,
  msf: workflowStore.msfPath, mapping: workflowStore.msfMapping,
  profile: workflowStore.msfProfile, parser: workflowStore.msfParseOptions,
  batchMode: workflowStore.isBatchMode, lod: workflowStore.lodMinimumViablePrefs,
  sandbox: effectiveExecutionEnvironmentIsSandbox.value, abort: abortOnCriticalError.value,
  recovery: recoveryPlan.value?.run_id,
}))

async function prepareSubmissionRequest() {
  if (recoveryPlan.value) {
    if (!recoveryPlan.value.record_ids.length) throw new Error('Resolve the record blockers before continuing this run.')
    return { kind: 'records', sessionId: recoveryPlan.value.session_id, identifier: recoveryPlan.value.pipeline_identifier,
      targets: recoveryPlan.value.record_ids, isSandbox: recoveryPlan.value.is_sandbox,
      options: { asyncExecution: true, abortOnCriticalError: abortOnCriticalError.value,
        expectedVersion: recoveryPlan.value.pipeline_version, resumeFromRunId: recoveryPlan.value.run_id } }
  }
  const selectedFiles = workflowStore.selectedFiles || []
  const sessionId = workflowStore.sessionId
  const { rerunRecordIds, executionPlan } = await refreshSubmissionPlan(sessionId, selectedFiles)
  const usePlan = workflowStore.isBatchMode
  if (usePlan && (executionPlan.unmatchedSelections.length || executionPlan.unresolvedCandidates.length)) {
    throw new Error('Review the file selection and resolve every saved record decision before processing.')
  }
  const useRecords = !usePlan && rerunRecordIds.length === selectedFiles.length && rerunRecordIds.length > 0
  return {
    kind: usePlan ? 'plan' : useRecords ? 'records' : 'files', sessionId,
    identifier: workflowStore.selectedPipeline?.identifier || PIPELINE_ID,
    targets: usePlan ? executionPlan.executionItems : useRecords ? rerunRecordIds : selectedFiles.map(file => file.absolute_path || file.path).filter(Boolean),
    isSandbox: effectiveExecutionEnvironmentIsSandbox.value,
    options: { asyncExecution: true, abortOnCriticalError: abortOnCriticalError.value, expectedVersion: pipelineVersion.value },
  }
}

async function checkReadiness() {
  readinessController?.abort()
  const controller = new AbortController()
  readinessController = controller
  const generation = ++readinessGeneration
  const checkedInputs = readinessInputs.value
  readinessBusy.value = true
  readinessResult.value = null
  readinessError.value = ''
  readinessProgress.value = null
  try {
    const prepared = await prepareSubmissionRequest()
    const response = await pipelineService.checkSubmissionReadiness(prepared.identifier, {
      session_id: prepared.sessionId, is_sandbox: prepared.isSandbox,
      abort_on_critical_error: prepared.options.abortOnCriticalError, expected_version: prepared.options.expectedVersion,
      resume_from_run_id: prepared.options.resumeFromRunId,
      [prepared.kind === 'plan' ? 'execution_items' : prepared.kind === 'records' ? 'record_ids' : 'local_file_paths']: prepared.targets,
    }, { signal: controller.signal, onProgress: progress => {
      if (!disposed && generation === readinessGeneration) readinessProgress.value = progress
    } })
    if (disposed || generation !== readinessGeneration || checkedInputs !== readinessInputs.value) return null
    const result = response.data
    if (typeof result?.ready !== 'boolean' || !Array.isArray(result.blockers) || (result.ready && !result.readiness_token)) {
      throw new Error('Readiness could not be confirmed. Check again before processing.')
    }
    readinessResult.value = result
    prepared.options.readinessToken = result.readiness_token
    return result.ready ? prepared : null
  } catch (err) {
    if (!disposed && generation === readinessGeneration) {
      readinessError.value = err?.error?.message || err?.message || 'Readiness is unavailable. Check your connection and try again.'
    }
    return null
  } finally {
    if (!disposed && generation === readinessGeneration) readinessBusy.value = false
  }
}

const activeSteps = computed(() => {
  if (!pipelineConfig.value?.steps) return []
  return pipelineConfig.value.steps.filter(s => s.enabled)
})

const usesZenodo = computed(() => activeSteps.value.some(step =>
  ['zenodo_draft', 'zenodo_upload'].includes(step.component_ref || step.id)))

const isRendererDisabled = computed(() => {
  const step = pipelineConfig.value?.steps?.find(s => s.id === 'fast_renderer')
  // Consider it disabled if explicitly disabled OR if the step is missing entirely (for safe fallback)
  // BUT: for metadata_only, the step exists but enabled=False.
  // If steps are missing (empty array), this returns undefined -> falsy.
  // We want to return TRUE if missing or disabled.
  return !step || !step.enabled
})

const isUsdzDisabled = computed(() => {
  const step = pipelineConfig.value?.steps?.find(s => s.id === 'any_to_usdz')
  return !step || !step.enabled
})

const hpcComponentKeys = computed(() => {
  const keys = []
  if (!isRendererDisabled.value) keys.push('fast_renderer')
  if (!isUsdzDisabled.value) keys.push('any_to_usdz')
  for (const step of activeSteps.value) {
    const key = step.component_ref || step.id
    if ((step.execution_profile_ref === 'hpc_singularity' || key === 'mesh_optimizer') && !keys.includes(key)) keys.push(key)
  }
  return keys
})

const componentPreflightTitle = computed(() => {
  const statuses = Object.values(componentRuntimeStatus.value || {})
  if (statuses.some((entry) => entry?.status === 'local_allowed')) {
    return 'Local workstation preflight'
  }
  return 'HPC-Link preflight'
})

const currentStepIndex = ref(0)
const isCurrentStep = (index) => currentStepIndex.value === index

const STAGE_LABELS = {
  queued: 'Queued',
  loading_project: 'Loading project',
  registering_records: 'Registering records',
  processing_record: 'Processing record',
  processing_component: 'Processing component',
  rendering_assets: 'Rendering assets',
  converting_to_usdz: 'Converting to USDZ',
  usdz_conversion_failed: 'USDZ conversion failed',
  creating_zenodo_draft: 'Creating Zenodo draft',
  zenodo_draft_created: 'Zenodo draft created',
  generating_lod_metadata: 'Generating metadata',
  uploading_to_zenodo: 'Uploading to Zenodo',
  record_completed: 'Record completed',
  executing_generic_pipeline: 'Executing pipeline',
  completed: 'Completed',
  failed: 'Failed'
}

const STAGE_TO_STEP_ID = {
  rendering_assets: 'fast_renderer',
  converting_to_usdz: 'any_to_usdz',
  usdz_conversion_failed: 'any_to_usdz',
  creating_zenodo_draft: 'zenodo_draft',
  zenodo_draft_created: 'zenodo_draft',
  generating_lod_metadata: 'lod_generation',
  uploading_to_zenodo: 'zenodo_upload',
  record_completed: 'zenodo_upload'
}

const processingFileName = computed(() => processingProgress.value?.current_file_name || '')
const zenodoDraftRecordId = computed(() => processingProgress.value?.zenodo_draft_record_id || '')
const workspaceSummaryLabel = computed(() => {
  const workspace = sessionContext.value?.workspace || {}
  if (workspace?.type === 'institution') {
    return workspace?.institution?.name
      ? `Institution (${workspace.institution.name})`
      : 'Institution'
  }
  return 'Personal'
})
const credentialSourceLabel = computed(() => {
  const source = String(sessionContext.value?.publishing_context?.effective_credential_source || 'system').trim()
  if (!source) return 'System'
  return `${source.charAt(0).toUpperCase()}${source.slice(1)}`
})
const defaultEnvironmentLabel = computed(() => (
  sessionContext.value?.publishing_context?.default_zenodo_environment || 'sandbox'
))
const sessionDefaultEnvironmentIsSandbox = computed(() => defaultEnvironmentLabel.value !== 'production')
const isBatchExecutionEnvironmentLocked = computed(() => workflowStore.isBatchMode)
const effectiveExecutionEnvironmentIsSandbox = computed(() => (
  isBatchExecutionEnvironmentLocked.value ? sessionDefaultEnvironmentIsSandbox.value : isSandbox.value
))
const publishingContextBadge = computed(() => {
  const source = credentialSourceLabel.value
  return `${source} credentials`
})
const selectedRecordResolutionPlan = computed(() => (
  resolveRecordResolutionSelections({
    selectedFiles: workflowStore.selectedFiles,
    candidates: recordResolutionState.value?.candidates || [],
  })
))
const batchResolutionSummary = computed(() => {
  if (!workflowStore.isBatchMode) return null
  const plan = selectedRecordResolutionPlan.value
  return {
    ...plan.actionCounts,
    unresolved: plan.unresolvedCandidates.length,
    unmatched: plan.unmatchedSelections.length,
    actionable: plan.executionItems.filter((item) => item.action !== 'skip').length,
  }
})
const batchResolutionBlockedReason = computed(() => {
  if (!workflowStore.isBatchMode) return ''
  if (recordResolutionLoading.value || submissionPlanLoading.value) {
    return 'Loading the saved record-resolution plan for this batch session.'
  }
  if (!recordResolutionState.value) {
    return 'Record-resolution analysis is missing for this batch session.'
  }
  if (selectedRecordResolutionPlan.value.unmatchedSelections.length > 0) {
    return 'At least one selected bundle could not be matched to a saved record-resolution candidate.'
  }
  if (selectedRecordResolutionPlan.value.unresolvedCandidates.length > 0) {
    return 'At least one selected bundle still requires a saved record-resolution decision.'
  }
  if (batchResolutionSummary.value?.actionable === 0) {
    return 'All selected bundles are currently marked as skip.'
  }
  return ''
})
const submissionPlanBadgeLabel = computed(() => {
  switch (submissionPlan.value.mode) {
    case 'record_resolution_plan':
      return 'Mixed plan'
    case 'version_records':
      return 'Version plan'
    case 'force_create_records':
      return 'Forced fresh'
    case 'skip_selection':
      return 'Skipped'
    case 'reprocess_records':
      return 'Reuse records'
    case 'mixed_selection':
      return 'Create from files'
    case 'create_records':
      return 'First submit'
    default:
      return 'Pending'
  }
})
const submissionPlanCardClass = computed(() => {
  switch (submissionPlan.value.mode) {
    case 'record_resolution_plan':
      return 'border-sky-200 bg-sky-50'
    case 'version_records':
      return 'border-indigo-200 bg-indigo-50'
    case 'force_create_records':
      return 'border-rose-200 bg-rose-50'
    case 'skip_selection':
      return 'border-slate-200 bg-slate-50'
    case 'reprocess_records':
      return 'border-emerald-200 bg-emerald-50'
    case 'mixed_selection':
      return 'border-amber-200 bg-amber-50'
    case 'create_records':
      return 'border-indigo-200 bg-indigo-50'
    default:
      return 'border-gray-200 bg-gray-50'
  }
})
const submissionPlanBadgeClass = computed(() => {
  switch (submissionPlan.value.mode) {
    case 'record_resolution_plan':
      return 'bg-white border border-sky-200 text-sky-700'
    case 'version_records':
      return 'bg-white border border-indigo-200 text-indigo-700'
    case 'force_create_records':
      return 'bg-white border border-rose-200 text-rose-700'
    case 'skip_selection':
      return 'bg-white border border-slate-200 text-slate-700'
    case 'reprocess_records':
      return 'bg-white border border-emerald-200 text-emerald-700'
    case 'mixed_selection':
      return 'bg-white border border-amber-200 text-amber-700'
    case 'create_records':
      return 'bg-white border border-indigo-200 text-indigo-700'
    default:
      return 'bg-white border border-gray-200 text-gray-700'
  }
})
const submissionPlanTextClass = computed(() => {
  switch (submissionPlan.value.mode) {
    case 'record_resolution_plan':
      return 'text-sky-900'
    case 'version_records':
      return 'text-indigo-900'
    case 'force_create_records':
      return 'text-rose-900'
    case 'skip_selection':
      return 'text-slate-700'
    case 'reprocess_records':
      return 'text-emerald-900'
    case 'mixed_selection':
      return 'text-amber-900'
    case 'create_records':
      return 'text-indigo-900'
    default:
      return 'text-gray-700'
  }
})
const hasConverterWarnings = computed(() => converterWarnings.value.length > 0 || converterRuntimeWarnings.value.length > 0)
const hasPipelineWarnings = computed(() => pipelineWarnings.value.length > 0)
const hasAnyWarnings = computed(() => hasConverterWarnings.value || hasPipelineWarnings.value)
const pipelineWarningTotalOccurrences = computed(() =>
  pipelineWarnings.value.reduce((sum, warning) => sum + (warning.occurrences || 0), 0)
)
const processingCounter = computed(() => {
  const total = Number(processingProgress.value?.total_files || 0)
  const current = Number(processingProgress.value?.current_index || 0)
  if (!total) return ''
  return `${Math.min(Math.max(current, 0), total)} / ${total}`
})
const formattedCurrentStage = computed(() => {
  const stage = processingProgress.value?.current_stage
  if (!stage) return 'Starting'
  return STAGE_LABELS[stage] || stage.replace(/_/g, ' ')
})

const stopProgressPolling = () => {
  monitorGeneration += 1
  if (progressPollTimer.value) {
    clearTimeout(progressPollTimer.value)
    progressPollTimer.value = null
  }
}

const updateCurrentStepFromProgress = (progress) => {
  const stepId = progress?.step_id || STAGE_TO_STEP_ID[progress?.current_stage]
  if (!stepId) return
  const index = activeSteps.value.findIndex(step => step.id === stepId)
  if (index >= 0) {
    currentStepIndex.value = index
  }
}

const addRuntimeConverterWarning = (message, code = null) => {
  if (!message) return
  const exists = converterRuntimeWarnings.value.some(
    item => item.message === message && item.code === code
  )
  if (!exists) {
    converterRuntimeWarnings.value.push({ message, code })
  }
}

const parseConverterWarningsFromResult = (resultPayload) => {
  const failures = Array.isArray(resultPayload?.converter_failures) ? resultPayload.converter_failures : []
  return failures.map((failure) => {
    const fileLabel = failure?.file_name || failure?.file_path || 'record'
    const errorLabel = failure?.error || 'Unknown converter error'
    const codeLabel = failure?.error_code || 'UNKNOWN'
    const message = failure?.hint
      ? `USDZ failed for ${fileLabel} (${codeLabel}): ${errorLabel}. Hint: ${failure.hint}`
      : `USDZ failed for ${fileLabel} (${codeLabel}): ${errorLabel}`
    return { message, code: failure?.error_code || null }
  })
}

const normalizeStepStatus = (stepPayload) => {
  if (!stepPayload || typeof stepPayload !== 'object') return 'n_a'

  const explicitStatus = typeof stepPayload.status === 'string' ? stepPayload.status.trim().toLowerCase() : ''
  if (explicitStatus) {
    if (explicitStatus.startsWith('skipped')) return 'skipped'
    if (explicitStatus === 'failed' || explicitStatus === 'error') return 'failed'
    if (explicitStatus === 'generated' || explicitStatus === 'completed' || explicitStatus === 'success') return 'completed'
    return explicitStatus
  }

  let hasSuccess = false
  let hasFailure = false

  const nestedResults = stepPayload.results
  if (nestedResults && typeof nestedResults === 'object') {
    Object.values(nestedResults).forEach((item) => {
      if (!item || typeof item !== 'object') return
      if (item.success === true) hasSuccess = true
      if (item.success === false) hasFailure = true
    })
  }

  const processedCount = Number(stepPayload.processed_count)
  const successCount = Number(stepPayload.success_count)
  if (Number.isFinite(processedCount) && processedCount > 0 && Number.isFinite(successCount)) {
    if (successCount <= 0) {
      hasFailure = true
    } else if (successCount < processedCount) {
      hasSuccess = true
      hasFailure = true
    } else {
      hasSuccess = true
    }
  }

  if (hasSuccess && hasFailure) return 'partial'
  if (hasFailure) return 'failed'
  if (hasSuccess) return 'completed'
  if (stepPayload.success === true) return 'completed'
  if (stepPayload.success === false) return 'failed'
  return 'n_a'
}

const aggregateStepStatus = (resultPayload, stepKey) => {
  const details = Array.isArray(resultPayload?.details) ? resultPayload.details : []
  if (details.length === 0) return 'n_a'

  const states = details
    .map(detail => normalizeStepStatus(detail?.[stepKey]))
    .filter(state => state !== 'n_a')

  if (states.length === 0) return 'n_a'
  if (states.includes('failed')) {
    return states.includes('completed') || states.includes('partial') ? 'partial' : 'failed'
  }
  if (states.includes('partial')) return 'partial'
  if (states.every(state => state === 'skipped')) return 'skipped'
  if (states.includes('completed') && states.includes('skipped')) return 'partial'
  if (states.every(state => state === 'completed')) return 'completed'
  return states[0]
}

const parsePipelineWarningsFromResult = (resultPayload) => {
  const details = Array.isArray(resultPayload?.details) ? resultPayload.details : []
  const warningMap = new Map()

  const warningGroupLabels = {
    configuration: 'Configuration',
    render: 'Rendering',
    usdz: 'USDZ Conversion',
    edm: 'EDM Metadata',
    iiif: 'IIIF Metadata',
    mets: 'METS Metadata',
    zenodo: 'Zenodo',
    general: 'General'
  }

  const warningGroupOrder = ['configuration', 'render', 'usdz', 'edm', 'iiif', 'mets', 'zenodo', 'general']

  const normalizeWarningTemplate = (message) => {
    let normalized = String(message || '').trim()
    if (!normalized) return ''
    normalized = normalized.replace(/for\s+[^;:]+(?=[;:])/gi, 'for <file>')
    normalized = normalized.replace(/\b[\w.-]+\.(glb|gltf|obj|fbx|stl|ply|dae|3ds|blend|usdz|xml|json|jpg|jpeg|png|webp|tif|tiff|mp4|mov|avi|mkv|wav|mp3|pdf|xlsx|csv)\b/gi, '<file>')
    normalized = normalized.replace(/\s+/g, ' ').trim()
    return normalized
  }

  const classifyGroup = (message, hint = null) => {
    if (hint && warningGroupLabels[hint]) return hint
    const lowered = String(message || '').toLowerCase()
    if (!lowered) return 'general'
    if (lowered.includes('metis') || lowered.includes('edm')) return 'edm'
    if (lowered.includes('iiif')) return 'iiif'
    if (lowered.includes('mets')) return 'mets'
    if (lowered.includes('usdz')) return 'usdz'
    if (lowered.includes('render') || lowered.includes('blender') || lowered.includes('cycles')) return 'render'
    if (lowered.includes('zenodo') || lowered.includes('deposition') || lowered.includes('upload')) return 'zenodo'
    if (
      lowered.includes('pipeline') ||
      lowered.includes('config') ||
      lowered.includes('coercing') ||
      lowered.includes('unsupported')
    ) {
      return 'configuration'
    }
    return 'general'
  }

  const registerWarning = ({ message, fileLabel, groupHint = null }) => {
    const cleaned = typeof message === 'string' ? message.trim() : ''
    if (!cleaned) return
    const groupKey = classifyGroup(cleaned, groupHint)
    const template = normalizeWarningTemplate(cleaned)
    const dedupeKey = `${groupKey}::${template || cleaned}`

    if (!warningMap.has(dedupeKey)) {
      warningMap.set(dedupeKey, {
        groupKey,
        groupLabel: warningGroupLabels[groupKey] || warningGroupLabels.general,
        message: template || cleaned,
        template: template || cleaned,
        occurrences: 0,
        affectedFilesSet: new Set()
      })
    }

    const entry = warningMap.get(dedupeKey)
    entry.occurrences += 1
    if (fileLabel) {
      entry.affectedFilesSet.add(fileLabel)
    }
  }

  details.forEach((detail) => {
    if (!detail || typeof detail !== 'object') return
    const fileLabel = detail.file_path || `record ${detail.record_id || 'unknown'}`

    ;['render', 'usdz', 'edm', 'iiif', 'mets', 'zenodo'].forEach((stepKey) => {
      const stepStatus = normalizeStepStatus(detail?.[stepKey])
      if (stepStatus === 'failed' || stepStatus === 'partial') {
        const statusLabel = stepStatus === 'failed' ? 'failed' : 'completed partially'
        registerWarning({
          message: `${stepKey.toUpperCase()} ${statusLabel}.`,
          fileLabel,
          groupHint: stepKey
        })
      }
    })

    const detailWarnings = Array.isArray(detail.warnings) ? detail.warnings : []
    detailWarnings.forEach((message) => {
      registerWarning({ message, fileLabel })
    })
  })

  return Array.from(warningMap.values())
    .map((entry) => {
      const affectedFiles = Array.from(entry.affectedFilesSet)
      return {
        groupKey: entry.groupKey,
        groupLabel: entry.groupLabel,
        message: entry.message,
        template: entry.template,
        occurrences: entry.occurrences,
        affectedFiles: affectedFiles.length,
        sampleFiles: affectedFiles.slice(0, 3)
      }
    })
    .sort((a, b) => {
      const groupDelta = warningGroupOrder.indexOf(a.groupKey) - warningGroupOrder.indexOf(b.groupKey)
      if (groupDelta !== 0) return groupDelta
      if (b.occurrences !== a.occurrences) return b.occurrences - a.occurrences
      return a.message.localeCompare(b.message)
    })
}

const pipelineWarningGroups = computed(() => {
  const grouped = new Map()
  pipelineWarnings.value.forEach((issue) => {
    if (!grouped.has(issue.groupKey)) {
      grouped.set(issue.groupKey, {
        groupKey: issue.groupKey,
        label: issue.groupLabel,
        totalOccurrences: 0,
        uniqueIssues: 0,
        issues: []
      })
    }
    const group = grouped.get(issue.groupKey)
    group.totalOccurrences += issue.occurrences || 0
    group.uniqueIssues += 1
    group.issues.push(issue)
  })

  const warningGroupOrder = ['configuration', 'render', 'usdz', 'edm', 'iiif', 'mets', 'zenodo', 'general']
  return Array.from(grouped.values())
    .map((group) => ({
      ...group,
      issues: group.issues.sort((a, b) => {
        if ((b.occurrences || 0) !== (a.occurrences || 0)) {
          return (b.occurrences || 0) - (a.occurrences || 0)
        }
        return a.message.localeCompare(b.message)
      })
    }))
    .sort((a, b) => {
      const groupDelta = warningGroupOrder.indexOf(a.groupKey) - warningGroupOrder.indexOf(b.groupKey)
      if (groupDelta !== 0) return groupDelta
      return b.totalOccurrences - a.totalOccurrences
    })
})

const stepStateClass = (state) => {
  if (state === 'completed') return 'text-green-700'
  if (state === 'skipped') return 'text-gray-500'
  if (state === 'failed' || state === 'partial') return 'text-amber-700'
  return 'text-gray-500'
}

const stepBadgeClass = (state) => {
  if (state === 'completed') return 'border-green-300 text-green-700'
  if (state === 'skipped') return 'border-gray-300 text-gray-500'
  if (state === 'failed' || state === 'partial') return 'border-amber-300 text-amber-700'
  return 'border-gray-300 text-gray-500'
}

const stepBadgeText = (state) => {
  if (state === 'completed') return 'Done'
  if (state === 'skipped') return 'Skipped'
  if (state === 'failed') return 'Failed'
  if (state === 'partial') return 'Partial'
  return 'n/a'
}

const renderStepState = computed(() => aggregateStepStatus(submissionResult.value, 'render'))
const usdzStepState = computed(() => aggregateStepStatus(submissionResult.value, 'usdz'))
const successfulSubmissionStepState = (state) => {
  if (state !== 'n_a') return state
  return submissionResult.value?.success === true ? 'completed' : state
}

const renderSummaryState = computed(() => isRendererDisabled.value ? 'skipped' : successfulSubmissionStepState(renderStepState.value))
const usdzSummaryState = computed(() => isUsdzDisabled.value ? 'skipped' : successfulSubmissionStepState(usdzStepState.value))

const renderSummaryClass = computed(() => stepStateClass(renderSummaryState.value))
const renderSummaryBadgeClass = computed(() => stepBadgeClass(renderSummaryState.value))
const renderSummaryBadge = computed(() => stepBadgeText(renderSummaryState.value))
const renderSummaryText = computed(() => {
  if (isRendererDisabled.value) return 'Assets rendering skipped (Low Resource Mode)'
  if (renderSummaryState.value === 'completed') return 'Assets rendered and optimized'
  if (renderSummaryState.value === 'partial') return 'Assets rendering partially completed'
  if (renderSummaryState.value === 'failed') return 'Assets rendering failed'
  if (renderSummaryState.value === 'skipped') return 'Assets rendering skipped'
  return 'Assets rendering status unavailable'
})

const usdzSummaryClass = computed(() => stepStateClass(usdzSummaryState.value))
const usdzSummaryBadgeClass = computed(() => stepBadgeClass(usdzSummaryState.value))
const usdzSummaryBadge = computed(() => stepBadgeText(usdzSummaryState.value))
const usdzSummaryText = computed(() => {
  if (isUsdzDisabled.value) return 'USDZ conversion skipped (Low Resource Mode)'
  if (usdzSummaryState.value === 'completed') return 'USDZ conversion completed successfully'
  if (usdzSummaryState.value === 'partial') return 'USDZ conversion partially completed'
  if (usdzSummaryState.value === 'failed') return 'USDZ conversion failed'
  if (usdzSummaryState.value === 'skipped') return 'USDZ conversion skipped'
  return 'USDZ conversion status unavailable'
})

const parseRecordFailuresFromResult = (resultPayload) => {
  const explicitFailures = Array.isArray(resultPayload?.failed_records) ? resultPayload.failed_records : []
  if (explicitFailures.length > 0) {
    return explicitFailures.map((failure) => {
      const fileLabel = failure?.file_path || `record ${failure?.record_id || 'unknown'}`
      const errorLabel = failure?.error || 'Unknown processing error'
      return { message: `${fileLabel}: ${errorLabel}` }
    })
  }

  const detailFailures = Array.isArray(resultPayload?.details) ? resultPayload.details : []
  return detailFailures
    .filter(item => item?.error)
    .map((failure) => {
      const fileLabel = failure?.file_path || `record ${failure?.record_id || 'unknown'}`
      return { message: `${fileLabel}: ${failure.error}` }
    })
}

const buildSubmissionErrorMessage = (payload, failures) => {
  const explicitError = payload?.error || payload?.result?.error
  if (explicitError) return explicitError
  if (failures.length > 0) return failures[0].message
  return 'Pipeline execution failed.'
}

const refreshSessionContext = async (sessionId) => {
  if (!sessionId) {
    sessionContext.value = null
    return null
  }
  try {
    const response = await fileService.getSession(sessionId, { suppressGlobalError: true })
    sessionContext.value = response.data?.session || null
    return sessionContext.value
  } catch (err) {
    console.warn('Failed to load session context for submission review:', err)
    sessionContext.value = null
    return null
  }
}

const refreshRecordResolutionState = async (sessionId) => {
  if (!sessionId || !workflowStore.isBatchMode) {
    recordResolutionState.value = null
    return null
  }
  recordResolutionLoading.value = true
  try {
    const response = await submissionService.getSessionRecordResolution(sessionId)
    recordResolutionState.value = response.data || null
    return recordResolutionState.value
  } catch (err) {
    console.warn('Failed to load record-resolution state for submission review:', err)
    recordResolutionState.value = null
    return null
  } finally {
    recordResolutionLoading.value = false
  }
}

const refreshSubmissionPlan = async (sessionId, selectedFiles) => {
  submissionPlanLoading.value = true
  try {
    if (workflowStore.isBatchMode) {
      const resolutionState = await refreshRecordResolutionState(sessionId)
      const executionPlan = resolveRecordResolutionSelections({
        selectedFiles,
        candidates: resolutionState?.candidates || [],
      })
      submissionPlan.value = deriveSubmissionPlan({
        selectedCount: Array.isArray(selectedFiles) ? selectedFiles.length : 0,
        executionItems: executionPlan.executionItems,
        unresolvedCount: executionPlan.unresolvedCandidates.length,
        unmatchedCount: executionPlan.unmatchedSelections.length,
      })
      return { rerunRecordIds: [], executionPlan }
    }

    const rerunRecordIds = await resolveRerunRecordIds(sessionId, selectedFiles)
    submissionPlan.value = deriveSubmissionPlan({
      selectedCount: Array.isArray(selectedFiles) ? selectedFiles.length : 0,
      existingRecordIds: rerunRecordIds
    })
    return { rerunRecordIds, executionPlan: null }
  } finally {
    submissionPlanLoading.value = false
  }
}

const handleCompletedProcessingPayload = (payload) => {
  submissionOutcomes.value = payload?.outcomes || null
  stopProgressPolling()
  clearPendingRun()
  executionTimings.value = payload?.timings || null
  currentStepIndex.value = activeSteps.value.length
  processing.value = false
  success.value = true
  error.value = ''
  processingProgress.value = applyTerminalProgressState(processingProgress.value, 'completed', 'Processing completed successfully.')
  submissionResult.value = payload?.result || {}
  recordFailures.value = []
  const parsedWarnings = parseConverterWarningsFromResult(payload?.result)
  converterWarnings.value = parsedWarnings.length > 0 ? parsedWarnings : [...converterRuntimeWarnings.value]
  pipelineWarnings.value = parsePipelineWarningsFromResult(payload?.result)
  if (hasAnyWarnings.value) {
    statusMessage.value = 'Processing completed with warnings.'
    toast.warning('Processing completed, but one or more processing steps reported issues.')
  } else {
    statusMessage.value = 'Processing completed successfully!'
    toast.success('Submission processed successfully!')
  }
  persistWorkflowState(workflowStore, 'completed', {
    submissionId: submissionId.value || payload?.submission_id || null,
    pipelineRunId: pipelineRunId.value || payload?.pipeline_run_id || payload?.run_id || null
  }).catch((persistErr) => {
    console.warn('Failed to persist completed submission state:', persistErr)
  })
}

const handleFailedSubmissionPayload = (payload) => {
  submissionOutcomes.value = payload?.outcomes || null
  stopProgressPolling()
  clearPendingRun()
  processing.value = false
  success.value = false
  readinessResult.value = null
  readinessError.value = ''
  executionTimings.value = payload?.timings || null
  submissionResult.value = payload?.result || null
  const failures = parseRecordFailuresFromResult(payload?.result)
  recordFailures.value = failures
  const message = buildSubmissionErrorMessage(payload, failures)
  error.value = message
  statusMessage.value = message
  processingProgress.value = applyTerminalProgressState(processingProgress.value, 'failed', message)
  persistWorkflowState(workflowStore, 'failed', {
    submissionId: submissionId.value || payload?.submission_id || null,
    pipelineRunId: pipelineRunId.value || payload?.pipeline_run_id || payload?.run_id || null
  }).catch((persistErr) => {
    console.warn('Failed to persist failed submission state:', persistErr)
  })
  toast.error(message)
}

const applyProgressUpdate = (progress) => {
  if (!progress) return
  processingProgress.value = progress
  if (progress.status_message) {
    statusMessage.value = progress.status_message
  }
  if (progress.current_stage === 'usdz_conversion_failed') {
    const warningMessage = progress.warning_message || progress.status_message || 'USDZ conversion failed.'
    console.error('[USDZ] Conversion did not work properly:', {
      warningMessage,
      warningCode: progress.warning_code,
      currentFile: progress.current_file_name
    })
    addRuntimeConverterWarning(warningMessage, progress.warning_code || null)
  }
  updateCurrentStepFromProgress(progress)
}

const pollSubmissionProgress = async () => {
  if (!submissionId.value || !processing.value) return

  try {
    const response = await submissionService.getSubmissionProgress(submissionId.value)
    const payload = response.data || {}
    monitorUnavailable.value = false
    monitorFailures = 0

    if (payload.progress) {
      applyProgressUpdate(payload.progress)
    }

    const resultPayload = payload.result || {}

    if (payload.status === 'completed') {
      if (resultPayload?.success === false) {
        handleFailedSubmissionPayload(payload)
        return
      }
      handleCompletedProcessingPayload(payload)
      return
    }

    if (payload.status === 'failed') {
      handleFailedSubmissionPayload(payload)
    }
  } catch (pollErr) {
    if (disposed) return
    handleMonitorError(pollErr)
    console.warn('Submission progress poll failed:', pollErr)
  }
}

const pollNativeRunProgress = async () => {
  if (!pipelineRunId.value || !processing.value || disposed || nativePollInFlight) return
  nativePollInFlight = true
  const requestedRunId = pipelineRunId.value

  try {
    const response = await pipelineService.getPipelineRun(pipelineRunId.value)
    if (disposed || requestedRunId !== pipelineRunId.value) return
    monitorUnavailable.value = false
    monitorFailures = 0
    const runPayload = response.data?.run || {}
    nativeRunStatus.value = runPayload.status || ''
    if (runPayload.run_id && pendingRun.value) {
      pendingRun.value.confirmed = true
      rememberPendingRun()
    }
    const resultPayload = runPayload.result || {}

    if (resultPayload.progress) {
      applyProgressUpdate(resultPayload.progress)
    } else if (runPayload.status === 'pending') {
      statusMessage.value = 'Pipeline job queued...'
    } else if (runPayload.status === 'running' && !processingProgress.value) {
      statusMessage.value = 'Pipeline execution in progress...'
    }

    if (runPayload.status === 'completed') {
      if (resultPayload?.success === false) {
        handleFailedSubmissionPayload({
          ...runPayload,
          result: resultPayload,
          run_id: runPayload.run_id
        })
        return
      }

      handleCompletedProcessingPayload({
        ...runPayload,
        result: resultPayload,
        run_id: runPayload.run_id
      })
      return
    }

    if (runPayload.status === 'failed') {
      handleFailedSubmissionPayload({
        ...runPayload,
        result: resultPayload,
        run_id: runPayload.run_id
      })
    }
  } catch (pollErr) {
    if (disposed || requestedRunId !== pipelineRunId.value) return
    handleMonitorError(pollErr)
    console.warn('Native pipeline run poll failed:', pollErr)
  } finally {
    nativePollInFlight = false
  }
}

const startProgressPolling = () => {
  stopProgressPolling()
  if (disposed) return
  monitoringStopped.value = false
  const poller = pipelineRunId.value ? pollNativeRunProgress : pollSubmissionProgress
  const generation = monitorGeneration
  const tick = async () => {
    if (generation !== monitorGeneration) return
    await poller()
    if (generation === monitorGeneration && !disposed && processing.value && !monitoringStopped.value) {
      progressPollTimer.value = setTimeout(tick, progressRetryDelay(monitorFailures))
    }
  }
  tick()
}

watch(readinessInputs, () => {
  readinessController?.abort()
  readinessGeneration++
  readinessResult.value = null
  readinessBusy.value = false
  clearTimeout(readinessTimer)
  if (!loadingPipeline.value && !processing.value && !success.value && !pendingRun.value) {
    readinessTimer = setTimeout(checkReadiness, 250)
  }
})

async function loadRecovery(runId) {
  loadingPipeline.value = true
  stopProgressPolling()
  success.value = false
  processing.value = false
  error.value = ''
  try {
    const [planResponse, runResponse] = await Promise.all([pipelineService.getPipelineRecovery(runId), pipelineService.getPipelineRun(runId)])
    const plan = planResponse.data
    const run = runResponse.data.run
    recoveryPlan.value = plan
    workflowStore.sessionId = plan.session_id
    workflowStore.isBatchMode = false
    workflowStore.setSelectedFiles(plan.records.filter(record => record.eligible).map(record => ({ local_record_id: record.record_id, absolute_path: record.file_path, name: record.file_path.split('/').pop() })))
    workflowStore.setSelectedPipeline({ identifier: plan.pipeline_identifier, name: run.pipeline_config.name })
    pipelineConfig.value = run.pipeline_config
    pipelineVersion.value = plan.pipeline_version
    isSandbox.value = plan.is_sandbox
    await refreshSessionContext(plan.session_id)
    try { pendingRun.value = JSON.parse(sessionStorage.getItem(pendingRunKey()) || 'null') } catch { pendingRun.value = null }
    if (pendingRun.value?.request?.options?.resumeFromRunId === runId) {
      pipelineRunId.value = pendingRun.value.runId
      processing.value = true
      startProgressPolling()
    }
  } catch (err) {
    error.value = err?.error?.message || err?.message || 'The recovery plan is unavailable. Review this run from Session Records.'
  } finally {
    loadingPipeline.value = false
    if (!error.value && !processing.value) await checkReadiness()
  }
}

watch(() => route.query.recoverRunId, (value, previous) => {
  if (value && value !== previous) loadRecovery(String(value))
})

onMounted(async () => {
  if (route.query.recoverRunId) { await loadRecovery(String(route.query.recoverRunId)); return }
  loadingPipeline.value = true
  try {
    const resumeSessionId = Number.parseInt(route.query.sessionId, 10)
    if (workflowStore.sessionId && (!resumeSessionId || resumeSessionId === workflowStore.sessionId)) {
      try { pendingRun.value = JSON.parse(sessionStorage.getItem(pendingRunKey()) || 'null') } catch { pendingRun.value = null }
      const savedRunId = String(route.query.runId || pendingRun.value?.runId || '').trim()
      if (savedRunId) {
        if (pendingRun.value?.runId !== savedRunId) pendingRun.value = null
        pipelineRunId.value = savedRunId
        processing.value = true
        statusMessage.value = 'Reconnecting to native pipeline execution...'
        startProgressPolling()
        await saveProcessingState()
        return
      }
      pendingRun.value = null
    }
    let restoredWorkflowState = null
    if (shouldRestoreWorkflowContext(workflowStore, resumeSessionId, {
      force: route.query.resume === 'workflow',
      requireUploadedFiles: true,
      requireSelectedFiles: true,
      requireSelectedPipeline: true,
      requireBatchMetadata: true
    })) {
      const restoredContext = await restoreWorkflowContext(workflowStore, resumeSessionId)
      restoredWorkflowState = restoredContext?.state || null
    }

    if (!workflowStore.sessionId) {
      toast.error('Your workflow session is missing. Please start again from upload.')
      router.replace('/workflow/upload')
      return
    }

    if (!Array.isArray(workflowStore.selectedFiles) || workflowStore.selectedFiles.length === 0) {
      toast.error('Select files before opening the submission screen.')
      workflowStore.goToStep(3)
      router.replace('/workflow/files')
      return
    }

    if (!workflowStore.selectedPipeline?.identifier && !workflowStore.selectedPipeline?.id) {
      toast.error('Choose a pipeline before reviewing the submission.')
      workflowStore.goToStep(6)
      router.replace('/workflow/pipeline')
      return
    }

    await Promise.all([
      refreshSessionContext(workflowStore.sessionId),
      refreshSubmissionPlan(workflowStore.sessionId, workflowStore.selectedFiles)
    ])
    isSandbox.value = (sessionContext.value?.publishing_context?.default_zenodo_environment || 'sandbox') !== 'production'

    const pipelineId = workflowStore.selectedPipeline?.identifier || PIPELINE_ID

    // Keep the selected outcome explicit if a pipeline becomes unavailable.
    const pipelinesRes = await pipelineService.listPipelines()
    const availablePipelines = pipelinesRes.data?.pipelines || []

    const match = availablePipelines.find(p => p.identifier === pipelineId)
    if (!match) {
      throw new Error('The selected pipeline is unavailable. Choose an available pipeline before processing.')
    }

    const res = await pipelineService.getPipeline(pipelineId)
    pipelineVersion.value = res.data.pipeline?.version || res.data.pipeline?.active_version || null
    const fullPipeline = res.data.pipeline?.config || res.data.pipeline

    pipelineConfig.value = fullPipeline

    try { pendingRun.value = JSON.parse(sessionStorage.getItem(pendingRunKey()) || 'null') } catch { pendingRun.value = null }
    const resumeRunId = String(route.query.runId || pendingRun.value?.runId || restoredWorkflowState?.pipeline_run_id || '').trim()
    if (pendingRun.value && pendingRun.value.runId !== resumeRunId) pendingRun.value = null
    const resumeSubmissionId = Number.parseInt(
      route.query.submissionId ?? restoredWorkflowState?.submission_id,
      10
    )

    if (resumeRunId) {
      pipelineRunId.value = resumeRunId
      submissionId.value = Number.isInteger(resumeSubmissionId) && resumeSubmissionId > 0 ? resumeSubmissionId : null
      processing.value = true
      success.value = false
      error.value = ''
      statusMessage.value = 'Reconnecting to native pipeline execution...'
      startProgressPolling()
      await saveProcessingState()
    } else if (Number.isInteger(resumeSubmissionId) && resumeSubmissionId > 0) {
      submissionId.value = resumeSubmissionId
      pipelineRunId.value = null
      processing.value = true
      success.value = false
      error.value = ''
      statusMessage.value = 'Reconnecting to submission processing...'
      startProgressPolling()
      await saveProcessingState()
    } else if (workflowStore.sessionId) {
      await persistWorkflowState(workflowStore, 'submit')
    }

  } catch (e) {
    console.error("Failed to load pipeline info", e)
    error.value = "Failed to load pipeline configuration. " + (e.message || "")
  } finally {
    loadingPipeline.value = false
    if (!disposed && !processing.value && !success.value && !error.value) await checkReadiness()
  }
})

const handleBack = () => {
  if (!processing.value) {
    workflowStore.prevStep()
    persistWorkflowState(workflowStore, 'pipeline').catch((persistErr) => {
      console.warn('Failed to persist pipeline workflow state:', persistErr)
    })
    router.push('/workflow/pipeline')
    error.value = ''
    success.value = false
  }
}

const normalizeMatchValue = (value) => String(value || '').trim().replaceAll('\\', '/').toLowerCase()

const buildSelectedFileMatchKeys = (file) => {
  const keys = new Set()
  const fileId = Number.parseInt(file?.file_id ?? file?.id, 10)
  const absolutePath = normalizeMatchValue(file?.absolute_path || file?.path)
  const relativePath = normalizeMatchValue(file?.relative_path)
  const filename = normalizeMatchValue(file?.filename || file?.name)

  if (Number.isInteger(fileId) && fileId > 0) {
    keys.add(`id:${fileId}`)
  }
  if (absolutePath) {
    keys.add(`path:${absolutePath}`)
    keys.add(`name:${absolutePath.split('/').pop()}`)
  }
  if (relativePath) {
    keys.add(`path:${relativePath}`)
    keys.add(`name:${relativePath.split('/').pop()}`)
  }
  if (filename) {
    keys.add(`name:${filename}`)
  }
  return [...keys]
}

const buildRecordMatchKeys = (record) => {
  const keys = new Set()
  const sourceFileId = Number.parseInt(record?.source_file_id, 10)
  const sourceFilePath = normalizeMatchValue(record?.source_file_path)
  const sourceFileName = normalizeMatchValue(record?.source_file_name)
  const mainFile = Array.isArray(record?.files)
    ? record.files.find((item) => String(item?.file_purpose || '').toLowerCase() === 'main') || record.files[0]
    : null
  const mainFilePath = normalizeMatchValue(mainFile?.absolute_path || mainFile?.mapped_file_path)
  const mainFileName = normalizeMatchValue(mainFile?.filename)

  if (Number.isInteger(sourceFileId) && sourceFileId > 0) {
    keys.add(`id:${sourceFileId}`)
  }
  for (const pathKey of [sourceFilePath, mainFilePath]) {
    if (!pathKey) continue
    keys.add(`path:${pathKey}`)
    keys.add(`name:${pathKey.split('/').pop()}`)
  }
  for (const nameKey of [sourceFileName, mainFileName]) {
    if (nameKey) {
      keys.add(`name:${nameKey}`)
    }
  }
  return [...keys]
}

const choosePreferredRerunRecord = (records = []) => {
  return [...records].sort((left, right) => {
    const processedDelta = Number(Boolean(right?.processed_in_latest_submission)) - Number(Boolean(left?.processed_in_latest_submission))
    if (processedDelta !== 0) return processedDelta
    const selectedDelta = Number(Boolean(right?.selected_for_submission)) - Number(Boolean(left?.selected_for_submission))
    if (selectedDelta !== 0) return selectedDelta
    return Number(right?.local_record_id || 0) - Number(left?.local_record_id || 0)
  })[0]
}

const resolveRerunRecordIds = async (sessionId, selectedFiles) => {
  try {
    const response = await submissionService.getSessionRecords(sessionId)
    const records = Array.isArray(response.data?.records) ? response.data.records : []
    if (records.length === 0) return []

    const recordsByKey = new Map()
    records.forEach((record) => {
      if (record?.canonical_submit_flow === false) return
      buildRecordMatchKeys(record).forEach((key) => {
        if (!recordsByKey.has(key)) {
          recordsByKey.set(key, [])
        }
        recordsByKey.get(key).push(record)
      })
    })

    const resolvedRecordIds = []
    const seenRecordIds = new Set()
    for (const selectedFile of selectedFiles) {
      const keys = buildSelectedFileMatchKeys(selectedFile)
      const matching = (prefix) => [...new Map(keys.filter(key => key.startsWith(prefix))
        .flatMap(key => recordsByKey.get(key) || [])
        .map(record => [record.local_record_id, record])).values()]
      let candidates = matching('id:')
      if (!candidates.length) candidates = matching('path:')
      if (!candidates.length) {
        candidates = matching('name:')
        const sourcePaths = new Set(candidates.map(record => normalizeMatchValue(record.source_file_path)))
        if (sourcePaths.size > 1) throw new Error('Existing records have ambiguous filenames. Review the file selection using exact source paths.')
      }

      const chosenRecord = choosePreferredRerunRecord(candidates)
      const chosenRecordId = Number.parseInt(chosenRecord?.local_record_id, 10)
      if (!Number.isInteger(chosenRecordId) || seenRecordIds.has(chosenRecordId)) {
        return []
      }
      seenRecordIds.add(chosenRecordId)
      resolvedRecordIds.push(chosenRecordId)
    }

    return resolvedRecordIds
  } catch (err) {
    if (err?.message?.includes('ambiguous filenames')) throw err
    throw new Error('Could not check existing records. Check your connection and try readiness again.')
  }
}

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms))

const waitForHpcAllocation = async (allocationId) => {
  let attempt = 0

  while (true) {
    const response = await hpcLinkService.getAllocation(allocationId)
    const allocation = response.data?.allocation || null
    hpcAllocation.value = allocation
    const status = allocation?.status || 'queued'

    if (status === 'running') {
      return allocation
    }
    if (['failed', 'released', 'expired', 'cancelled'].includes(status)) {
      throw new Error(allocation?.last_error || `HPC-Link allocation ${status}.`)
    }

    attempt += 1
    hpcPreflightMessage.value = status === 'queued'
      ? 'Waiting for an HPC allocation slot...'
      : 'Allocating HPC resources...'
    await sleep(3000)
  }
}

const ensureHpcAllocationAndPreflight = async (sessionId) => {
  const components = hpcComponentKeys.value
  if (components.length === 0) {
    hpcPreflightState.value = 'idle'
    hpcPreflightMessage.value = 'No compute-backed HDP Component steps are enabled.'
    return
  }

  hpcPreflightState.value = 'checking'
  hpcPreflightMessage.value = 'Checking HDP Component runtime availability...'

  const statusResponse = await hpcLinkService.getStatus({ purpose: 'workflow', session_id: sessionId })
  const hpcStatus = statusResponse.data || {}
  const runtimeByComponent = hpcStatus.component_runtime || {}
  componentRuntimeStatus.value = runtimeByComponent
  const selectedRuntime = components.map((componentKey) => runtimeByComponent[componentKey]).filter(Boolean)

  const unavailableRuntime = selectedRuntime.find((entry) => entry.status === 'unavailable')
  if (unavailableRuntime) {
    throw new Error(unavailableRuntime.message || `${unavailableRuntime.label || 'Component'} runtime is unavailable.`)
  }

  const localReady = selectedRuntime.length === components.length && selectedRuntime.every((entry) => entry.status === 'local_allowed' || entry.status === 'disabled')
  if (localReady) {
    hpcPreflightState.value = 'ready'
    hpcPreflightMessage.value = `Local workstation execution is ready for ${components.join(', ')}.`
    return
  }

  const activeHpcRuntime = Boolean(hpcStatus.active_hpc_allocation || hpcStatus.activeAllocation)
    || selectedRuntime.some((entry) => entry.active_hpc_allocation)
  if (activeHpcRuntime) {
    hpcPreflightState.value = 'ready'
    hpcPreflightMessage.value = `An active HPC-Link allocation is available for ${components.join(', ')}.`
    return
  }

  const allocationRequired = selectedRuntime.length === 0 || selectedRuntime.some((entry) => entry.allocation_required || entry.status === 'hpc_required')
  if (!allocationRequired) {
    hpcPreflightState.value = 'ready'
    hpcPreflightMessage.value = 'Compute-backed HDP Component runtime is ready.'
    return
  }

  if (!hpcStatus.available) {
    const message = selectedRuntime.find((entry) => entry.message)?.message
    throw new Error(message || 'HPC-Link is not available. Server/VPS deployments require an HPC allocation for compute-backed HDP Component steps.')
  }
  if (!hpcStatus.can_allocate) {
    throw new Error(hpcStatus.permission_reason || 'Your account cannot allocate HPC-Link resources.')
  }

  hpcPreflightMessage.value = 'Requesting reusable HPC allocation...'
  const allocationResponse = await hpcLinkService.requestAllocation({
    purpose: 'workflow',
    session_id: sessionId
  })
  const requestedAllocation = allocationResponse.data?.allocation || null
  const allocationId = requestedAllocation?.allocation_id
  if (!allocationId) {
    throw new Error('HPC-Link allocation response did not include an allocation ID.')
  }

  hpcAllocation.value = requestedAllocation
  const activeAllocation = requestedAllocation.status === 'running'
    ? requestedAllocation
    : await waitForHpcAllocation(allocationId)

  hpcPreflightMessage.value = 'Validating HDP Component runtimes on the allocated node...'
  const preflightResponse = await hpcLinkService.preflightAllocation(activeAllocation.allocation_id, components)
  const preflight = preflightResponse.data?.preflight || {}
  hpcAllocation.value = preflightResponse.data?.allocation || activeAllocation
  if (preflight.success === false) {
    throw new Error(preflight.error || 'HPC-Link component preflight failed.')
  }

  hpcPreflightState.value = 'ready'
  hpcPreflightMessage.value = `HPC-Link is ready for ${components.join(', ')}.`
}

const onReservedGpuChanged = (allocation) => {
  hpcAllocation.value = allocation
  hpcPreflightState.value = 'idle'
  hpcPreflightMessage.value = 'HDP Component runtimes will be checked before processing starts.'
  checkReadiness()
}

const handleSubmit = async () => {
  if (loadingPipeline.value || submitting.value || processing.value) return
  if (pendingRun.value) { await retryPendingRun(); return }
  submitting.value = true
  processing.value = false
  success.value = false
  error.value = ''
  submissionId.value = null
  pipelineRunId.value = null
  processingProgress.value = null
  currentStepIndex.value = 0
  converterRuntimeWarnings.value = []
  converterWarnings.value = []
  pipelineWarnings.value = []
  recordFailures.value = []
  submissionResult.value = null
  hpcPreflightState.value = 'idle'
  hpcPreflightMessage.value = 'HDP Component runtimes will be checked before processing starts.'
  componentRuntimeStatus.value = {}
  statusMessage.value = 'Preparing files for processing...'

  try {
    const prepared = await checkReadiness()
    if (!prepared) return
    // Local blockers are resolved before any allocation request.
    await ensureHpcAllocationAndPreflight(prepared.sessionId)
    processing.value = true
    statusMessage.value = 'Processing the checked submission…'
    pendingRun.value = {
      runId: crypto.randomUUID(), confirmed: false,
      request: JSON.parse(JSON.stringify(prepared)),
    }
    rememberPendingRun()
    await submitPendingRun()

  } catch (err) {
    console.error('Pipeline execution failed:', err)
    stopProgressPolling()
    processing.value = false
    hpcPreflightState.value = hpcPreflightState.value === 'checking' ? 'failed' : hpcPreflightState.value
    error.value = err?.error?.message || err.response?.data?.error?.message || err.message || 'Pipeline execution failed.'
    if (hpcPreflightState.value === 'failed') {
      hpcPreflightMessage.value = error.value
    }
    toast.error(error.value)
  } finally {
    submitting.value = false
  }
}

const startNewWorkflow = () => {
  stopProgressPolling()
  clearPendingRun()
  workflowStore.resetWorkflow()
  router.push('/workflow/upload')
}

onBeforeUnmount(() => {
  disposed = true
  readinessGeneration++
  clearTimeout(readinessTimer)
  readinessController?.abort()
  stopProgressPolling()
})
</script>
