<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-7xl mx-auto px-4">
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">MSF Analysis</h1>
        <p class="mt-2 text-gray-600">Step 2 of 7: Investigate MSF quality, LOD impact, and direct repair options.</p>
      </div>

      <StepIndicator
        :current-step="2"
        current-label="Resolve blockers or confirm the minimum-viable fallback policy"
        :current-hint="analysisStepHint"
      />

      <div v-if="!workflowStore.sessionId || !workflowStore.isBatchMode" class="bg-white shadow rounded-lg p-6">
        <p class="text-sm text-gray-600">
          This step applies only to MSF-driven batch workflows.
        </p>
        <div class="mt-6">
          <button
            type="button"
            class="px-6 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700"
            @click="router.push('/workflow/upload')"
          >
            Return to Upload Setup
          </button>
        </div>
      </div>

      <div v-else class="space-y-6">
        <div class="bg-white shadow rounded-lg p-6">
          <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
            <div>
              <h2 class="text-xl font-semibold text-gray-900">Session MSF Report</h2>
              <p class="mt-1 text-sm text-gray-600">
                Problems are linked to affected LOD outputs and can be repaired directly where supported.
              </p>
              <p v-if="analysis?.msf_path" class="mt-3 text-xs font-mono text-gray-500 break-all">
                {{ analysis.msf_path }}
              </p>
            </div>
            <div class="flex flex-wrap gap-3">
              <button
                type="button"
                class="px-4 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50"
                :disabled="loading"
                @click="runAnalysis()"
              >
                Refresh Active Analysis
              </button>
              <button
                type="button"
                class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50"
                :disabled="loading || applying || selectedFixIds.length === 0"
                @click="applySelectedFixes"
              >
                {{ applying ? 'Applying Fixes...' : `Apply Selected Fixes (${selectedFixIds.length})` }}
              </button>
            </div>
          </div>

          <div v-if="error" class="mt-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {{ error }}
          </div>
          <div v-if="success" class="mt-4 rounded-md border border-green-200 bg-green-50 p-4 text-sm text-green-700">
            {{ success }}
          </div>

          <div v-if="loading" class="py-16 text-center">
            <div class="inline-block animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600"></div>
            <p class="mt-4 text-sm text-gray-500">Analyzing MSF and LOD impact...</p>
          </div>

          <div v-else-if="analysis" class="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <div class="space-y-6">
              <div class="grid grid-cols-2 gap-4 lg:grid-cols-6">
                <div class="rounded-lg border border-gray-200 bg-gray-50 p-4">
                  <p class="text-xs uppercase tracking-wide text-gray-500">Rows</p>
                  <p class="mt-1 text-2xl font-semibold text-gray-900">{{ analysis.summary?.rows_total || 0 }}</p>
                </div>
                <div class="rounded-lg border border-gray-200 bg-red-50 p-4">
                  <p class="text-xs uppercase tracking-wide text-red-600">Errors</p>
                  <p class="mt-1 text-2xl font-semibold text-red-700">{{ analysis.summary?.error_count || 0 }}</p>
                </div>
                <div class="rounded-lg border border-gray-200 bg-amber-50 p-4">
                  <p class="text-xs uppercase tracking-wide text-amber-600">Warnings</p>
                  <p class="mt-1 text-2xl font-semibold text-amber-700">{{ analysis.summary?.warning_count || 0 }}</p>
                </div>
                <div class="rounded-lg border border-gray-200 bg-gray-50 p-4">
                  <p class="text-xs uppercase tracking-wide text-gray-500">Matched Files</p>
                  <p class="mt-1 text-2xl font-semibold text-gray-900">{{ analysis.validator?.checks?.reference_availability?.matched_count || 0 }}</p>
                </div>
                <div class="rounded-lg border border-gray-200 bg-gray-50 p-4">
                  <p class="text-xs uppercase tracking-wide text-gray-500">Missing References</p>
                  <p class="mt-1 text-2xl font-semibold text-gray-900">{{ analysis.validator?.checks?.reference_availability?.missing_count || 0 }}</p>
                </div>
                <div class="rounded-lg border border-gray-200 bg-gray-50 p-4">
                  <p class="text-xs uppercase tracking-wide text-gray-500">Sample Row</p>
                  <p class="mt-1 text-2xl font-semibold text-gray-900">{{ analysis.summary?.sample_row_number || 'N/A' }}</p>
                </div>
              </div>

              <section class="rounded-2xl border border-gray-200 bg-white p-5">
                <div class="flex items-start gap-4">
                  <div class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-indigo-600 text-sm font-bold text-white">1</div>
                  <div class="min-w-0 flex-1">
                    <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                      <div>
                        <h3 class="text-lg font-semibold text-gray-900">Fix scan setup</h3>
                        <p class="mt-1 text-sm text-gray-600">
                          Confirm the MSF source and scan target first. This keeps the downstream issue list relevant and prevents the batch run from starting with avoidable ambiguity.
                        </p>
                      </div>
                      <router-link
                        v-if="workflowStore.sessionId"
                        :to="`/uploads/${workflowStore.sessionId}`"
                        class="text-sm font-medium text-indigo-700 hover:text-indigo-900"
                      >
                        {{ requiresScanStart ? 'Open persistent workflow monitor' : 'Open persistent upload monitor' }}
                      </router-link>
                    </div>

                    <div
                      v-if="requiresScanStart"
                      class="mt-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4"
                    >
                      <p class="text-sm font-semibold text-indigo-950">Guided repair before scan</p>
                      <p class="mt-1 text-sm text-indigo-900">
                        The real directory scan has not started yet. Apply fixes here first, then start processing from this page.
                      </p>
                      <p v-if="workflowState.target_directory" class="mt-2 text-xs font-mono text-indigo-900/80 break-all">
                        Target directory: {{ workflowState.target_directory }}
                      </p>
                    </div>

                    <div v-if="scanRunning" class="mt-4 rounded-lg border border-indigo-200 bg-white p-4">
                      <div class="flex items-center justify-between gap-4">
                        <div>
                          <p class="text-sm font-medium text-gray-900">Local scan in progress</p>
                          <p class="mt-1 text-sm text-gray-600">{{ scanStatusMessage || 'Preparing processing pipeline...' }}</p>
                        </div>
                        <span class="text-sm font-semibold text-indigo-700">{{ scanProgressPercent }}%</span>
                      </div>
                      <div class="mt-3 h-2 rounded-full bg-indigo-100">
                        <div class="h-2 rounded-full bg-indigo-600 transition-all duration-300" :style="{ width: `${scanProgressPercent}%` }"></div>
                      </div>
                    </div>

                    <div v-if="requiresScanStart" class="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-4">
                      <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div>
                          <p class="text-sm font-semibold text-gray-900">Current setup</p>
                          <p class="mt-1 text-sm text-gray-600">
                            Adjust the target directory or MSF here, then rerun analysis before moving on.
                          </p>
                        </div>
                        <button
                          type="button"
                          class="px-4 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 disabled:opacity-50"
                          :disabled="setupLoading || loading || applying || scanRunning"
                          @click="refreshLocalContext"
                        >
                          {{ setupLoading ? 'Refreshing...' : 'Refresh Setup Options' }}
                        </button>
                      </div>

                      <div v-if="setupLoading" class="mt-4 text-sm text-gray-500">
                        Loading local MSF and directory options...
                      </div>

                      <div v-else class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
                        <div>
                          <label class="block text-sm font-medium text-gray-700 mb-1">Target directory</label>
                          <div class="rounded-xl border border-gray-200 bg-white p-3">
                            <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                              <input
                                v-model="directorySearchQuery"
                                type="search"
                                placeholder="Filter nested directories"
                                class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                              >
                              <span class="text-xs text-gray-500">
                                {{ filteredLocalSubdirectories.length }} / {{ availableLocalSubdirectories.length }}
                              </span>
                            </div>
                            <p v-if="isDirectorySearchTruncated" class="mt-2 text-xs text-amber-700">
                              Showing the first {{ visibleLocalSubdirectories.length }} matches. Refine the filter to narrow the list.
                            </p>
                            <div class="mt-3 max-h-52 space-y-2 overflow-y-auto pr-1">
                              <button
                                type="button"
                                class="w-full rounded-lg border px-3 py-2 text-left transition"
                                :class="!localSetup.directoryPath ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100' : 'border-gray-200 hover:border-gray-300'"
                                @click="selectAnalysisDirectory('')"
                              >
                                <p class="text-sm font-medium text-gray-900">Root directory</p>
                                <p class="mt-1 text-xs font-mono text-gray-500 break-all">{{ localInputRoot || '/data/local_input' }}</p>
                              </button>
                              <button
                                v-for="subdir in visibleLocalSubdirectories"
                                :key="`analysis-subdir-${subdir.relative_path}`"
                                type="button"
                                class="w-full rounded-lg border px-3 py-2 text-left transition"
                                :class="localSetup.directoryPath === subdir.relative_path ? 'border-indigo-500 bg-indigo-50 ring-2 ring-indigo-100' : 'border-gray-200 hover:border-gray-300'"
                                @click="selectAnalysisDirectory(subdir.relative_path)"
                              >
                                <div class="flex items-start justify-between gap-3">
                                  <div class="min-w-0">
                                    <p class="text-sm font-medium text-gray-900 break-all">{{ subdir.relative_path }}</p>
                                    <p class="mt-1 text-xs text-gray-500">
                                      Depth {{ subdir.depth }} · {{ subdir.file_count }} recursive file{{ subdir.file_count === 1 ? '' : 's' }}
                                    </p>
                                  </div>
                                  <span class="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-700">
                                    {{ subdir.file_count }}
                                  </span>
                                </div>
                              </button>
                            </div>
                          </div>
                        </div>

                        <div>
                          <label class="block text-sm font-medium text-gray-700 mb-1">MSF file</label>
                          <select
                            v-model="localSetup.msfPath"
                            class="block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"
                          >
                            <option
                              v-for="file in msfSelectionOptions"
                              :key="`analysis-msf-${file.value}`"
                              :value="file.value"
                            >
                              {{ file.label }}
                            </option>
                          </select>
                          <p class="mt-2 text-xs text-gray-500">
                            Refresh Analysis always uses the active analysis MSF shown below. Choose a different MSF here only when you want to switch away from the current repaired copy.
                          </p>
                        </div>
                      </div>

                      <dl class="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
                        <div class="rounded-md border border-green-200 bg-green-50 p-3">
                          <dt class="text-xs font-semibold uppercase tracking-wide text-green-700">
                            {{ workflowState.active_msf_kind === 'repaired_copy' ? 'Active repaired MSF' : 'Active analysis MSF' }}
                          </dt>
                          <dd class="mt-1 text-sm text-green-900 break-all">{{ activeAnalysisMsfPath || 'Unavailable' }}</dd>
                        </div>
                        <div class="rounded-md border border-gray-200 bg-white p-3">
                          <dt class="text-xs font-semibold uppercase tracking-wide text-gray-500">Original workflow MSF</dt>
                          <dd class="mt-1 text-sm text-gray-700 break-all">{{ originalAnalysisMsfPath || 'Unavailable' }}</dd>
                        </div>
                      </dl>

                      <div
                        v-if="isUsingRepairedMsf"
                        class="mt-3 rounded-md border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900"
                      >
                        Refresh Analysis will keep using the repaired session copy until you explicitly switch back to the original MSF and rerun the setup update.
                      </div>

                      <div v-if="showCsvHeaderToggle" class="mt-4 rounded-md border border-blue-200 bg-blue-50 p-3">
                        <label class="inline-flex items-center gap-2 text-sm text-blue-900">
                          <input
                            v-model="localSetup.useFirstRowAsHeader"
                            type="checkbox"
                            class="rounded border-blue-300 text-indigo-600 focus:ring-indigo-500"
                          >
                          Use first row as headers?
                        </label>
                        <p class="mt-1 text-xs text-blue-700">
                          Disable this when the CSV contains only data rows and no header row.
                        </p>
                      </div>

                      <div class="mt-4 flex flex-wrap gap-3">
                        <button
                          type="button"
                          class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50"
                          :disabled="setupSaving || loading || applying || scanRunning || !localSetup.msfPath"
                          @click="applySetupChanges"
                        >
                          {{ setupSaving ? 'Updating...' : 'Update Setup & Re-run Analysis' }}
                        </button>
                        <p class="text-xs text-gray-500 self-center">
                          Changing the MSF or CSV parsing resets temporary repair assumptions and reruns the analysis from the current source file.
                        </p>
                      </div>
                    </div>

                      <div v-else class="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-4">
                      <p class="text-sm font-semibold text-gray-900">Current batch context</p>
                      <p class="mt-1 text-sm text-gray-600">
                        This session is already beyond the pre-scan setup stage. Use the diagnostics below to decide whether you should continue, go back, or adjust the upstream MSF/template inputs.
                      </p>
                      <dl class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                        <div>
                          <dt class="text-xs font-semibold uppercase tracking-wide text-gray-500">Active analysis MSF</dt>
                          <dd class="mt-1 text-sm text-gray-700 break-all">{{ activeAnalysisMsfPath || 'Unavailable' }}</dd>
                        </div>
                        <div>
                          <dt class="text-xs font-semibold uppercase tracking-wide text-gray-500">Original workflow MSF</dt>
                          <dd class="mt-1 text-sm text-gray-700 break-all">{{ originalAnalysisMsfPath || 'Unavailable' }}</dd>
                        </div>
                        <div>
                          <dt class="text-xs font-semibold uppercase tracking-wide text-gray-500">Filename column</dt>
                          <dd class="mt-1 text-sm text-gray-700">{{ analysis.filename_column || 'Not detected' }}</dd>
                        </div>
                      </dl>
                    </div>
                  </div>
                </div>
              </section>

              <section class="rounded-2xl border border-red-200 bg-red-50 p-5">
                <div class="flex items-start gap-4">
                  <div class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-red-600 text-sm font-bold text-white">2</div>
                  <div class="min-w-0 flex-1">
                    <h3 class="text-lg font-semibold text-gray-900">Review critical blockers</h3>
                    <p class="mt-1 text-sm text-gray-700">
                      Start with issues that would stop the scan or produce invalid LOD output. Click an item to jump to the affected preview cells.
                    </p>

                    <div v-if="criticalIssues.length === 0" class="mt-4 rounded-lg border border-green-200 bg-white p-4 text-sm text-green-700">
                      No critical blockers are currently detected in the sampled analysis.
                    </div>

                    <div v-else class="mt-4 space-y-3">
                      <button
                        v-for="issue in criticalIssues"
                        :key="`critical-${issue.id}`"
                        type="button"
                        class="w-full rounded-xl border bg-white px-4 py-4 text-left transition"
                        :class="selectedIssueId === issue.id ? 'border-red-400 ring-2 ring-red-100' : 'border-red-200 hover:border-red-300'"
                        @click="focusIssue(issue)"
                      >
                        <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                          <div>
                            <div class="flex flex-wrap items-center gap-2">
                              <span class="rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold uppercase text-red-700">error</span>
                              <p class="text-sm font-semibold text-gray-900">{{ issue.title }}</p>
                            </div>
                            <p class="mt-2 text-sm text-gray-700">{{ issue.leads_to }}</p>
                          </div>
                          <span class="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700">
                            {{ issue.locations?.length || 0 }} sample location{{ issue.locations?.length === 1 ? '' : 's' }}
                          </span>
                        </div>
                      </button>
                    </div>
                  </div>
                </div>
              </section>

              <section class="rounded-2xl border border-gray-200 bg-white p-5">
                <div class="flex items-start gap-4">
                  <div class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-gray-900 text-sm font-bold text-white">3</div>
                  <div class="min-w-0 flex-1">
                    <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                      <div>
                        <h3 class="text-lg font-semibold text-gray-900">Review all detected problems</h3>
                        <span class="text-xs text-gray-500">{{ filteredIssues.length }} shown of {{ issues.length }} total</span>
                      </div>
                      <div class="flex flex-wrap gap-2">
                        <input
                          v-model="issueSearch"
                          type="search"
                          placeholder="Search issues"
                          class="rounded-md border-gray-300 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                        >
                        <select
                          v-model="issueSeverityFilter"
                          class="rounded-md border-gray-300 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                        >
                          <option value="all">All severities</option>
                          <option value="error">Errors</option>
                          <option value="warning">Warnings</option>
                        </select>
                        <select
                          v-model="issueLodFilter"
                          class="rounded-md border-gray-300 text-sm shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
                        >
                          <option value="all">All LODs</option>
                          <option value="edm">EDM</option>
                          <option value="iiif">IIIF</option>
                          <option value="mets">METS</option>
                        </select>
                        <button
                          type="button"
                          class="px-3 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50"
                          @click="exportIssues"
                        >
                          Export Issues CSV
                        </button>
                      </div>
                    </div>

                    <div v-if="filteredIssues.length === 0" class="mt-4 rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-700">
                      No issues match the current filters.
                    </div>

                    <div class="mt-4 space-y-4">
                      <article
                        v-for="issue in pagedIssues"
                        :key="issue.id"
                        :ref="element => registerIssueCard(issue.id, element)"
                        class="rounded-xl border p-4 transition"
                        :class="[
                          issue.severity === 'error' ? 'border-red-200 bg-red-50' : 'border-amber-200 bg-amber-50',
                          selectedIssueId === issue.id ? 'ring-2 ring-indigo-200' : ''
                        ]"
                      >
                        <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                          <div>
                            <div class="flex items-center gap-2 flex-wrap">
                              <span :class="issue.severity === 'error' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'" class="px-2 py-0.5 rounded-full text-[11px] font-semibold uppercase">
                                {{ issue.severity }}
                              </span>
                              <h4 class="text-sm font-semibold text-gray-900">{{ issue.title }}</h4>
                            </div>
                            <p class="mt-2 text-sm text-gray-700">{{ issue.description }}</p>
                          </div>
                          <div class="flex gap-1 flex-wrap">
                            <span v-for="lod in issue.affected_lods || []" :key="`${issue.id}-${lod}`" class="px-2 py-0.5 rounded-full text-[11px] font-medium bg-white border border-gray-200 text-gray-700 uppercase">
                              {{ lod }}
                            </span>
                          </div>
                        </div>

                        <div class="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3 text-xs">
                          <div class="rounded-lg bg-white/80 p-3 border border-white">
                            <p class="font-semibold text-gray-900">Why</p>
                            <p class="mt-1 text-gray-600">{{ issue.why }}</p>
                          </div>
                          <div class="rounded-lg bg-white/80 p-3 border border-white">
                            <p class="font-semibold text-gray-900">Leads To</p>
                            <p class="mt-1 text-gray-600">{{ issue.leads_to }}</p>
                          </div>
                          <div class="rounded-lg bg-white/80 p-3 border border-white">
                            <p class="font-semibold text-gray-900">Suggested Fix</p>
                            <p class="mt-1 text-gray-600">{{ issue.suggested_fix }}</p>
                          </div>
                        </div>

                        <div class="mt-3 flex flex-wrap gap-2">
                          <button
                            type="button"
                            class="px-3 py-1.5 text-xs font-medium text-indigo-700 bg-white border border-indigo-200 rounded-md hover:bg-indigo-50"
                            @click="focusIssue(issue)"
                          >
                            Highlight in preview
                          </button>
                          <button
                            v-if="issue.recommendation_ids?.length"
                            type="button"
                            class="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
                            @click="selectRecommendationsForIssue(issue)"
                          >
                            Select suggested fix
                          </button>
                        </div>

                        <div v-if="issue.locations?.length" class="mt-3">
                          <p class="text-xs font-semibold text-gray-900 mb-2">Example Locations</p>
                          <div class="flex flex-wrap gap-2">
                            <button
                              v-for="location in issue.locations.slice(0, 6)"
                              :key="`${issue.id}-${location.row_number}-${location.column}`"
                              type="button"
                              class="px-2.5 py-1 rounded-md bg-white text-xs border border-gray-200 text-gray-700 hover:border-indigo-300 hover:text-indigo-700"
                              @click="focusLocation(issue, location)"
                            >
                              Row {{ location.row_number }}{{ location.column ? `, ${location.column}` : '' }}
                            </button>
                          </div>
                        </div>

                        <div v-if="issue.context?.conflicts?.length" class="mt-3 rounded-lg border border-white bg-white/80 p-3">
                          <p class="text-xs font-semibold text-gray-900">Conflicting File Paths</p>
                          <div
                            v-for="conflict in issue.context.conflicts.slice(0, 6)"
                            :key="`${issue.id}-${conflict.basename}`"
                            class="mt-2 rounded-md border border-gray-200 bg-white p-3"
                          >
                            <p class="text-xs font-semibold text-gray-900">{{ conflict.basename }}</p>
                            <ul class="mt-1 space-y-1 text-xs text-gray-600">
                              <li v-for="path in conflict.paths" :key="`${conflict.basename}-${path}`">{{ path }}</li>
                            </ul>
                            <div v-if="conflict.suggested_directories?.length" class="mt-2 flex flex-wrap gap-2">
                              <button
                                v-for="suggested in conflict.suggested_directories"
                                :key="`${conflict.basename}-${suggested}`"
                                type="button"
                                class="px-2.5 py-1 text-xs font-medium text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-md hover:bg-indigo-100 disabled:opacity-50"
                                :disabled="!requiresScanStart || setupSaving || scanRunning"
                                @click="applySuggestedDirectory(suggested)"
                              >
                                Try directory: {{ suggested }}
                              </button>
                            </div>
                          </div>
                        </div>
                      </article>
                    </div>

                    <div v-if="filteredIssues.length > issuePageSize" class="mt-4 flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
                      <p class="text-xs text-gray-600">
                        Page {{ issuePage }} of {{ totalIssuePages }}
                      </p>
                      <div class="flex gap-2">
                        <button
                          type="button"
                          class="px-3 py-1.5 text-sm font-medium text-gray-700 border border-gray-300 rounded-md hover:bg-white disabled:opacity-50"
                          :disabled="issuePage <= 1"
                          @click="issuePage -= 1"
                        >
                          Previous
                        </button>
                        <button
                          type="button"
                          class="px-3 py-1.5 text-sm font-medium text-gray-700 border border-gray-300 rounded-md hover:bg-white disabled:opacity-50"
                          :disabled="issuePage >= totalIssuePages"
                          @click="issuePage += 1"
                        >
                          Next
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              <section class="rounded-2xl border border-gray-200 bg-white p-5">
                <div class="flex items-start gap-4">
                  <div class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-gray-900 text-sm font-bold text-white">4</div>
                  <div class="min-w-0 flex-1">
                    <h3 class="text-lg font-semibold text-gray-900">Inspect highlighted sample cells</h3>
                    <p class="mt-1 text-sm text-gray-600">
                      Click an issue to focus its cells, or click a highlighted cell to inspect the linked issue. Red cells indicate blockers; amber cells indicate warnings.
                    </p>

                    <div class="mt-4 rounded-xl border border-gray-200 overflow-hidden">
                      <div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-200 text-sm">
                          <thead class="bg-gray-50">
                            <tr>
                              <th class="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">Row</th>
                              <th v-for="column in previewColumns" :key="column" class="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase">
                                {{ column }}
                              </th>
                            </tr>
                          </thead>
                          <tbody class="divide-y divide-gray-100">
                            <tr v-for="row in previewRows" :key="`preview-${row.__row_number}`" class="bg-white">
                              <td class="px-3 py-2 text-xs font-semibold text-gray-500 whitespace-nowrap">{{ row.__row_number }}</td>
                              <td
                                v-for="column in previewColumns"
                                :key="`${row.__row_number}-${column}`"
                                :ref="element => registerPreviewCell(row.__row_number, column, element)"
                                class="px-3 py-2 align-top transition"
                                :class="cellClass(row.__row_number, column)"
                                :title="cellMessage(row.__row_number, column)"
                                @click="focusCell(row.__row_number, column)"
                              >
                                <div class="max-w-[220px] truncate">
                                  {{ row[column] || '—' }}
                                </div>
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <div class="mt-4 flex flex-wrap gap-3 text-xs">
                      <span class="inline-flex items-center gap-2 rounded-full bg-red-50 px-3 py-1 text-red-700">
                        <span class="h-2.5 w-2.5 rounded-full bg-red-500"></span>
                        Error-linked cell
                      </span>
                      <span class="inline-flex items-center gap-2 rounded-full bg-amber-50 px-3 py-1 text-amber-700">
                        <span class="h-2.5 w-2.5 rounded-full bg-amber-500"></span>
                        Warning-linked cell
                      </span>
                      <span class="inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1 text-indigo-700">
                        <span class="h-2.5 w-2.5 rounded-full bg-indigo-500"></span>
                        Current focus
                      </span>
                    </div>

                    <div v-if="selectedIssue || activeCellDetails" class="mt-4 rounded-xl border border-indigo-200 bg-indigo-50 p-4">
                      <p class="text-sm font-semibold text-indigo-950">Focused explanation</p>
                      <p class="mt-1 text-sm text-indigo-900">
                        {{ activeCellDetails?.message || selectedIssue?.description }}
                      </p>
                      <p v-if="selectedIssue?.leads_to" class="mt-2 text-xs text-indigo-900/80">
                        Leads to: {{ selectedIssue.leads_to }}
                      </p>
                    </div>
                  </div>
                </div>
              </section>

              <section class="rounded-2xl border border-gray-200 bg-white p-5">
                <div class="flex items-start gap-4">
                  <div class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-gray-900 text-sm font-bold text-white">5</div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center justify-between">
                      <div>
                        <h3 class="text-lg font-semibold text-gray-900">Inspect sampled LOD output</h3>
                        <p class="mt-1 text-sm text-gray-600">
                          Confirm how the current MSF state affects EDM, IIIF, and METS generation before moving to file review.
                        </p>
                      </div>
                      <div class="flex gap-2">
                        <button
                          v-for="standard in ['edm', 'iiif', 'mets']"
                          :key="`tab-${standard}`"
                          type="button"
                          class="px-3 py-1.5 rounded-md text-sm font-medium"
                          :class="activeStandard === standard ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'"
                          @click="activeStandard = standard"
                        >
                          {{ standard.toUpperCase() }}
                        </button>
                      </div>
                    </div>

                    <div v-if="activeSample" class="mt-4 space-y-4">
                      <div class="flex flex-wrap gap-3">
                        <span :class="activeSample.valid ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'" class="px-2.5 py-1 rounded-full text-xs font-semibold uppercase">
                          {{ activeSample.valid ? 'Valid' : 'Invalid' }}
                        </span>
                        <span :class="activeSample.minimum_viable_applied ? 'bg-amber-100 text-amber-800' : 'bg-gray-100 text-gray-700'" class="px-2.5 py-1 rounded-full text-xs font-semibold uppercase">
                          {{ activeSample.minimum_viable_applied ? 'Minimum viable applied' : 'Template output used as-is' }}
                        </span>
                      </div>

                      <div v-if="activeSample.errors?.length" class="rounded-lg border border-red-200 bg-red-50 p-3">
                        <p class="text-xs font-semibold text-red-700 uppercase">Validation Errors</p>
                        <ul class="mt-2 space-y-1 text-sm text-red-700">
                          <li v-for="(message, index) in activeSample.errors.slice(0, 5)" :key="`err-${index}`">{{ message }}</li>
                        </ul>
                      </div>

                      <div v-if="activeSample.warnings?.length" class="rounded-lg border border-amber-200 bg-amber-50 p-3">
                        <p class="text-xs font-semibold text-amber-700 uppercase">Warnings</p>
                        <ul class="mt-2 space-y-1 text-sm text-amber-700">
                          <li v-for="(message, index) in activeSample.warnings.slice(0, 5)" :key="`warn-${index}`">{{ message }}</li>
                        </ul>
                      </div>

                      <pre class="bg-gray-950 text-green-300 rounded-lg p-4 overflow-x-auto text-xs max-h-[420px]">{{ activeSampleContent }}</pre>
                    </div>
                  </div>
                </div>
              </section>
            </div>

            <aside class="space-y-4 xl:sticky xl:top-6 xl:self-start">
              <div class="rounded-2xl border border-gray-200 bg-white p-4">
                <h3 class="text-base font-semibold text-gray-900">Workflow summary</h3>
                <ul class="mt-4 space-y-3">
                  <li
                    v-for="item in analysisChecklist"
                    :key="item.label"
                    class="flex items-start gap-3"
                  >
                    <span
                      class="mt-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold"
                      :class="item.complete ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'"
                    >
                      {{ item.complete ? '✓' : '!' }}
                    </span>
                    <div>
                      <p class="text-sm font-medium text-gray-900">{{ item.label }}</p>
                      <p class="mt-0.5 text-xs text-gray-600">{{ item.detail }}</p>
                    </div>
                  </li>
                </ul>
              </div>

              <div class="rounded-2xl border border-gray-200 bg-gray-50 p-4">
                <div class="flex items-center justify-between">
                  <h3 class="text-base font-semibold text-gray-900">Recommended fixes</h3>
                  <div class="flex gap-2">
                    <button type="button" class="text-xs font-medium text-indigo-700 hover:text-indigo-900" @click="selectAllFixes">All</button>
                    <button type="button" class="text-xs font-medium text-gray-600 hover:text-gray-900" @click="clearSelectedFixes">None</button>
                  </div>
                </div>
                <div v-if="fixSummaries.length === 0" class="mt-3 text-sm text-gray-500">
                  No automatic fixes available for the current analysis.
                </div>
                <div v-else class="mt-4 space-y-3">
                  <label
                    v-for="fix in fixSummaries"
                    :key="fix.id"
                    class="flex items-start gap-3 rounded-lg border border-gray-200 bg-white p-3"
                  >
                    <input
                      v-model="selectedFixIds"
                      type="checkbox"
                      :value="fix.id"
                      class="mt-1 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                    />
                    <div class="min-w-0">
                      <p class="text-sm font-medium text-gray-900">{{ fix.label }}</p>
                      <p class="mt-1 text-xs text-gray-600">{{ fix.description }}</p>
                      <p class="mt-2 text-[11px] text-gray-500">
                        Expected effect: {{ fix.issueCount }} linked issue{{ fix.issueCount === 1 ? '' : 's' }}, {{ fix.rowCount }} sampled row{{ fix.rowCount === 1 ? '' : 's' }}, {{ fix.operationCount }} operation{{ fix.operationCount === 1 ? '' : 's' }}.
                      </p>
                      <p v-if="fix.previewTitles.length" class="mt-1 text-[11px] text-gray-500">
                        Helps with: {{ fix.previewTitles.join(', ') }}
                      </p>
                    </div>
                  </label>
                </div>
              </div>

              <div class="rounded-2xl border border-indigo-200 bg-indigo-50 p-4">
                <h3 class="text-base font-semibold text-gray-900">Minimum-viable LOD output</h3>
                <p class="mt-1 text-sm text-gray-600">
                  If source data stays incomplete, these toggles allow placeholders, filename-derived labels, and defaults to keep the output minimally valid.
                </p>
                <div class="mt-4 space-y-3">
                  <label
                    v-for="option in analysis.minimum_viable_options || []"
                    :key="option.standard"
                    class="flex items-start justify-between gap-3 rounded-lg border border-indigo-100 bg-white p-3"
                  >
                    <div>
                      <p class="text-sm font-medium text-gray-900">{{ option.label }}</p>
                      <p class="mt-1 text-xs text-gray-600">{{ option.description }}</p>
                      <p v-if="option.required" class="mt-1 text-[11px] font-medium text-amber-700">
                        Currently required by the sampled output.
                      </p>
                    </div>
                    <input
                      v-model="minimumViablePrefs[option.standard]"
                      type="checkbox"
                      class="mt-1 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                    />
                  </label>
                </div>
              </div>

              <div v-if="selectedIssue" class="rounded-2xl border border-gray-200 bg-white p-4">
                <h3 class="text-base font-semibold text-gray-900">Focused issue</h3>
                <p class="mt-3 text-sm font-medium text-gray-900">{{ selectedIssue.title }}</p>
                <p class="mt-1 text-sm text-gray-600">{{ selectedIssue.description }}</p>
                <p class="mt-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Why it matters</p>
                <p class="mt-1 text-sm text-gray-600">{{ selectedIssue.leads_to }}</p>
              </div>
            </aside>
          </div>
        </div>

        <div class="flex justify-between">
          <button
            type="button"
            class="px-6 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50"
            :disabled="scanRunning"
            @click="handleBack"
          >
            ← Back
          </button>
          <button
            type="button"
            class="px-6 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
            :disabled="loading || applying || scanRunning"
            @click="handleNext"
          >
            {{ nextButtonLabel }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StepIndicator from '@/components/workflow/StepIndicator.vue'
import { useWorkflowStore } from '@/stores/workflow'
import api from '@/services/api'
import msfService from '@/services/msf.service'
import { persistWorkflowState } from '@/utils/workflowState'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()

const loading = ref(false)
const applying = ref(false)
const error = ref('')
const success = ref('')
const analysis = ref(null)
const activeStandard = ref('edm')
const selectedFixIds = ref([])
const minimumViablePrefs = ref({ ...workflowStore.lodMinimumViablePrefs })
const selectedIssueId = ref('')
const selectedCellKey = ref('')
const scanRunning = ref(false)
const scanProgressPercent = ref(0)
const scanStatusMessage = ref('')
const setupLoading = ref(false)
const setupSaving = ref(false)
const availableMsfFiles = ref([])
const availableLocalSubdirectories = ref([])
const localInputRoot = ref('')
const directorySearchQuery = ref('')
const localSetup = ref({
  directoryPath: '',
  msfPath: '',
  useFirstRowAsHeader: true
})
const issueSearch = ref('')
const issueSeverityFilter = ref('all')
const issueLodFilter = ref('all')
const issuePage = ref(1)
const issuePageSize = 10
const DIRECTORY_RESULTS_LIMIT = 250
const issueCardElements = new Map()
const previewCellElements = new Map()

const issues = computed(() => analysis.value?.issues || [])
const recommendedFixes = computed(() => analysis.value?.recommended_fixes || [])
const previewColumns = computed(() => analysis.value?.preview?.columns || [])
const previewRows = computed(() => analysis.value?.preview?.preview_rows || [])
const highlightMap = computed(() => {
  const map = new Map()
  ;(analysis.value?.highlight_cells || []).forEach(item => {
    map.set(`${item.row_number}::${item.column}`, item)
  })
  return map
})
const activeSample = computed(() => analysis.value?.lod_samples?.[activeStandard.value] || null)
const activeSampleContent = computed(() => {
  if (!activeSample.value) return ''
  return activeSample.value.xml || activeSample.value.json || ''
})
const workflowState = computed(() => analysis.value?.workflow_state || {})
const activeAnalysisMsfPath = computed(() => workflowState.value.active_msf_path || analysis.value?.msf_path || '')
const originalAnalysisMsfPath = computed(() => workflowState.value.original_msf_path || workflowState.value.source_msf_path || activeAnalysisMsfPath.value)
const isUsingRepairedMsf = computed(() => {
  return Boolean(
    activeAnalysisMsfPath.value
    && originalAnalysisMsfPath.value
    && activeAnalysisMsfPath.value !== originalAnalysisMsfPath.value
  )
})
const requiresScanStart = computed(() => !!workflowState.value.requires_scan_start)
const showCsvHeaderToggle = computed(() => localSetup.value.msfPath.toLowerCase().endsWith('.csv'))
const analysisStepHint = computed(() => {
  if (requiresScanStart.value) {
    return 'Confirm the scan setup, review blockers, apply repairs, then start the real scan from this page.'
  }
  return 'Use the issue list and sampled outputs to confirm that the MSF is safe to carry into file review.'
})
const nextButtonLabel = computed(() => {
  if (scanRunning.value) return 'Starting Scan...'
  if (requiresScanStart.value) return 'Start Scan & Continue'
  return 'Continue to File Review →'
})
const criticalIssues = computed(() => issues.value.filter(issue => issue.severity === 'error'))
const selectedIssue = computed(() => issues.value.find(issue => issue.id === selectedIssueId.value) || null)
const filteredLocalSubdirectories = computed(() => {
  const query = directorySearchQuery.value.trim().toLowerCase()
  const tokens = query.split(/\s+/).filter(Boolean)
  if (!tokens.length) {
    return availableLocalSubdirectories.value
  }
  return availableLocalSubdirectories.value.filter(entry => {
    const haystack = `${entry?.relative_path || ''} ${entry?.name || ''}`.toLowerCase()
    return tokens.every(token => haystack.includes(token))
  })
})
const visibleLocalSubdirectories = computed(() => filteredLocalSubdirectories.value.slice(0, DIRECTORY_RESULTS_LIMIT))
const isDirectorySearchTruncated = computed(() => filteredLocalSubdirectories.value.length > DIRECTORY_RESULTS_LIMIT)
const msfSelectionOptions = computed(() => {
  const options = []
  const seen = new Set()
  const pushOption = (value, label) => {
    const normalizedValue = String(value || '').trim()
    if (!normalizedValue || seen.has(normalizedValue)) return
    seen.add(normalizedValue)
    options.push({ value: normalizedValue, label })
  }

  if (activeAnalysisMsfPath.value) {
    pushOption(
      activeAnalysisMsfPath.value,
      isUsingRepairedMsf.value
        ? `Active repaired MSF (${activeAnalysisMsfPath.value})`
        : `Active analysis MSF (${activeAnalysisMsfPath.value})`,
    )
  }
  if (originalAnalysisMsfPath.value) {
    pushOption(
      originalAnalysisMsfPath.value,
      `Original workflow MSF (${originalAnalysisMsfPath.value})`,
    )
  }
  availableMsfFiles.value.forEach((file) => {
    const fullPath = file.full_path || file.path
    pushOption(fullPath, `${file.name} (${file.path})`)
  })
  return options
})
const activeCellDetails = computed(() => {
  if (!selectedCellKey.value) return null
  const [rowNumber, column] = selectedCellKey.value.split('::')
  return highlightMap.value.get(`${rowNumber}::${column}`) || null
})
const analysisChecklist = computed(() => [
  {
    label: 'Scan setup confirmed',
    complete: !requiresScanStart.value || (!!localSetup.value.msfPath && !setupSaving.value),
    detail: requiresScanStart.value
      ? 'The MSF and target directory can still be changed from this page.'
      : 'The scan has already started or completed for this session.',
  },
  {
    label: 'Critical blockers reviewed',
    complete: criticalIssues.value.length === 0 || !!selectedIssue.value,
    detail: criticalIssues.value.length
      ? `${criticalIssues.value.length} blocking issue(s) need attention.`
      : 'No blocking issues are currently visible in the sampled analysis.',
  },
  {
    label: 'Repair plan selected',
    complete: recommendedFixes.value.length === 0 || selectedFixIds.value.length > 0,
    detail: recommendedFixes.value.length
      ? `${selectedFixIds.value.length} fix(es) selected for application.`
      : 'No automatic repair actions are available.',
  },
  {
    label: 'Fallback policy reviewed',
    complete: Object.values(minimumViablePrefs.value || {}).some(Boolean),
    detail: 'Minimum-viable EDM, IIIF, and METS generation can stay enabled for incomplete source data.',
  },
])
const fixSummaries = computed(() => {
  return recommendedFixes.value.map(fix => {
    const linkedIssues = issues.value.filter(issue => (issue.recommendation_ids || []).includes(fix.id))
    const rowCount = linkedIssues.reduce((total, issue) => total + new Set((issue.locations || []).map(location => location.row_number)).size, 0)
    return {
      ...fix,
      issueCount: linkedIssues.length,
      rowCount,
      operationCount: Array.isArray(fix.operations) ? fix.operations.length : 0,
      previewTitles: linkedIssues.slice(0, 2).map(issue => issue.title),
    }
  })
})
const filteredIssues = computed(() => {
  const search = issueSearch.value.trim().toLowerCase()
  return issues.value.filter(issue => {
    if (issueSeverityFilter.value !== 'all' && issue.severity !== issueSeverityFilter.value) {
      return false
    }
    if (issueLodFilter.value !== 'all' && !(issue.affected_lods || []).includes(issueLodFilter.value)) {
      return false
    }
    if (!search) {
      return true
    }
    const haystack = [
      issue.title,
      issue.description,
      issue.why,
      issue.leads_to,
      issue.suggested_fix,
      ...(issue.affected_lods || []),
    ]
      .join(' ')
      .toLowerCase()
    return haystack.includes(search)
  })
})
const totalIssuePages = computed(() => Math.max(1, Math.ceil(filteredIssues.value.length / issuePageSize)))
const pagedIssues = computed(() => {
  const start = (issuePage.value - 1) * issuePageSize
  return filteredIssues.value.slice(start, start + issuePageSize)
})

const buildCellKey = (rowNumber, column) => `${rowNumber}::${column}`

const relativeDirectoryPath = (absolutePath) => {
  const root = localInputRoot.value
  if (!absolutePath || !root) return ''
  if (absolutePath === root) return ''
  if (!absolutePath.startsWith(root)) return ''
  return absolutePath.slice(root.length).replace(/^[/\\]+/, '')
}

const syncAnalysisWithStore = () => {
  if (analysis.value?.msf_profile) {
    workflowStore.setMsfProfile(analysis.value.msf_profile)
    if (analysis.value.msf_profile.parse_options) {
      workflowStore.setMsfParseOptions(analysis.value.msf_profile.parse_options)
    }
  }
  const parseOptions = analysis.value?.msf_profile?.parse_options || {}
  localSetup.value = {
    directoryPath: relativeDirectoryPath(workflowState.value.target_directory || ''),
    msfPath: activeAnalysisMsfPath.value || localSetup.value.msfPath || '',
    useFirstRowAsHeader: parseOptions.use_first_row_as_header !== false
  }
}

const loadLocalContext = async () => {
  if (!requiresScanStart.value) return
  setupLoading.value = true
  try {
    const response = await api.get('/sessions/local-msf', { suppressGlobalError: true })
    availableMsfFiles.value = response.data?.msf_files || []
    availableLocalSubdirectories.value = response.data?.subdirectories || []
    localInputRoot.value = response.data?.input_root || ''
    syncAnalysisWithStore()
  } catch (err) {
    console.error('Failed to load local workflow setup context:', err)
  } finally {
    setupLoading.value = false
  }
}

const refreshLocalContext = async () => {
  await loadLocalContext()
}

const runAnalysis = async (payload = {}) => {
  if (!workflowStore.sessionId) return
  loading.value = true
  error.value = ''
  success.value = ''
  try {
    const response = await msfService.analyzeWorkflowSessionMsf(workflowStore.sessionId, payload)
    analysis.value = response.data?.analysis || null
    selectedFixIds.value = (analysis.value?.recommended_fixes || []).map(item => item.id)
    syncAnalysisWithStore()
    if (requiresScanStart.value) {
      await loadLocalContext()
    }
    if (response.data?.apply_result?.applied) {
      const appliedFixes = response.data.apply_result.selected_fix_ids || []
      success.value = `Applied ${appliedFixes.length} fix${appliedFixes.length === 1 ? '' : 'es'} and switched analysis to ${response.data.apply_result.patched_msf_path}. Refresh Analysis will continue using this active MSF until you switch it explicitly.`
    }
  } catch (err) {
    console.error('Failed to analyze MSF workflow state:', err)
    error.value = err?.error?.message || err?.message || 'Failed to analyze the session MSF.'
  } finally {
    loading.value = false
    applying.value = false
    setupSaving.value = false
  }
}

const applySelectedFixes = async () => {
  if (!selectedFixIds.value.length) return
  applying.value = true
  await runAnalysis({
    apply_selected_fixes: true,
    selected_fix_ids: selectedFixIds.value
  })
}

const registerIssueCard = (issueId, element) => {
  if (!issueId) return
  if (element) {
    issueCardElements.set(issueId, element)
  } else {
    issueCardElements.delete(issueId)
  }
}

const registerPreviewCell = (rowNumber, column, element) => {
  const key = buildCellKey(rowNumber, column)
  if (element) {
    previewCellElements.set(key, element)
  } else {
    previewCellElements.delete(key)
  }
}

const scrollToElement = async (element) => {
  if (!element) return
  await nextTick()
  element.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

const focusIssue = async (issue) => {
  if (!issue?.id) return
  selectedIssueId.value = issue.id
  const firstLocation = issue.locations?.[0]
  if (firstLocation?.column) {
    await focusLocation(issue, firstLocation)
    return
  }
  selectedCellKey.value = ''
  await scrollToElement(issueCardElements.get(issue.id))
}

const focusLocation = async (issue, location) => {
  if (!issue?.id || !location?.column) return
  selectedIssueId.value = issue.id
  const key = buildCellKey(location.row_number, location.column)
  selectedCellKey.value = key
  await scrollToElement(previewCellElements.get(key))
}

const focusCell = async (rowNumber, column) => {
  const key = buildCellKey(rowNumber, column)
  selectedCellKey.value = key
  const highlight = highlightMap.value.get(key)
  if (highlight?.issue_id) {
    selectedIssueId.value = highlight.issue_id
    await scrollToElement(issueCardElements.get(highlight.issue_id))
  }
}

const selectRecommendationsForIssue = (issue) => {
  const nextIds = new Set(selectedFixIds.value)
  ;(issue?.recommendation_ids || []).forEach(id => nextIds.add(id))
  selectedFixIds.value = Array.from(nextIds)
}

const selectAllFixes = () => {
  selectedFixIds.value = recommendedFixes.value.map(item => item.id)
}

const clearSelectedFixes = () => {
  selectedFixIds.value = []
}

const cellClass = (rowNumber, column) => {
  const key = buildCellKey(rowNumber, column)
  const item = highlightMap.value.get(key)
  const classes = ['text-gray-700']
  if (!item) {
    if (selectedCellKey.value === key) {
      classes.push('ring-2', 'ring-indigo-300')
    }
    return classes.join(' ')
  }
  classes.push('cursor-pointer')
  if (item.severity === 'error') {
    classes.push('bg-red-100', 'text-red-900', 'border', 'border-red-200')
  } else {
    classes.push('bg-amber-100', 'text-amber-900', 'border', 'border-amber-200')
  }
  if (selectedCellKey.value === key || item.issue_id === selectedIssueId.value) {
    classes.push('ring-2', 'ring-indigo-300')
  }
  return classes.join(' ')
}

const cellMessage = (rowNumber, column) => {
  return highlightMap.value.get(`${rowNumber}::${column}`)?.message || ''
}

const handleBack = () => {
  workflowStore.goToStep(1)
  router.push('/workflow/upload')
}

const applySetupChanges = async () => {
  if (!workflowStore.sessionId) return
  setupSaving.value = true
  const payload = {
    msf_path: localSetup.value.msfPath,
    directory_path: localSetup.value.directoryPath,
    recursive: true
  }
  if (showCsvHeaderToggle.value) {
    payload.use_first_row_as_header = localSetup.value.useFirstRowAsHeader
  }
  await runAnalysis({
    ...payload
  })
}

const applySuggestedDirectory = async (directory) => {
  localSetup.value.directoryPath = directory || ''
  await applySetupChanges()
}

const selectAnalysisDirectory = (directory) => {
  localSetup.value.directoryPath = directory || ''
}

const exportIssues = () => {
  const rows = filteredIssues.value.map(issue => ({
    severity: issue.severity || '',
    title: issue.title || '',
    affected_lods: (issue.affected_lods || []).join('|'),
    why: issue.why || '',
    leads_to: issue.leads_to || '',
    suggested_fix: issue.suggested_fix || '',
    example_locations: (issue.locations || [])
      .map(location => `Row ${location.row_number}${location.column ? `:${location.column}` : ''}`)
      .join(' | '),
  }))
  const header = ['severity', 'title', 'affected_lods', 'why', 'leads_to', 'suggested_fix', 'example_locations']
  const csv = [
    header.join(','),
    ...rows.map(row =>
      header
        .map(key => `"${String(row[key] || '').replace(/"/g, '""')}"`)
        .join(',')
    ),
  ].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `msf_analysis_issues_session_${workflowStore.sessionId || 'unknown'}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

const pollTaskUntilCoordinatorDone = async (taskId) => {
  if (!taskId) return
  while (true) {
    const response = await api.get(`/sessions/tasks/${taskId}`, { suppressGlobalError: true })
    const taskData = response.data || {}
    const state = taskData.state
    if (state === 'SUCCESS' || state === 'coordinator_completed') {
      if (taskData.status === 'failed') {
        throw new Error(taskData.error || 'The local scan coordinator failed.')
      }
      return
    }
    if (state === 'FAILURE') {
      throw new Error(taskData.error || 'The local scan coordinator failed.')
    }
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
}

const pollUploadProgressUntilComplete = async (sessionId) => {
  while (true) {
    const response = await api.get(`/sessions/${sessionId}/progress`, { suppressGlobalError: true })
    const payload = response.data || {}
    const uploadProgress = payload.upload_progress || {}
    const currentStage = uploadProgress.current_stage || payload.current_stage
    const percent = uploadProgress.percent ?? payload.percent ?? 0

    scanProgressPercent.value = percent
    scanStatusMessage.value = uploadProgress.status_message || 'Processing files...'

    if (currentStage === 'failed') {
      throw new Error(uploadProgress.status_message || 'Local scan failed.')
    }
    if (percent >= 100) {
      const failedCount = uploadProgress.failed_count ?? payload.failed ?? 0
      if (failedCount > 0) {
        throw new Error(`${failedCount} file(s) failed during local processing.`)
      }
      return
    }
    await new Promise(resolve => setTimeout(resolve, 1000))
  }
}

const startLocalScanAndContinue = async () => {
  if (!workflowStore.sessionId) return
  scanRunning.value = true
  scanProgressPercent.value = 0
  scanStatusMessage.value = 'Queueing local directory scan...'
  error.value = ''
  success.value = ''

  try {
    const response = await msfService.startLocalWorkflowScan(workflowStore.sessionId)
    const taskId = response.data?.task_id || null
    success.value = 'Local scan started. You can leave this page and reopen the persistent upload monitor at any time.'
    await pollTaskUntilCoordinatorDone(taskId)
    await pollUploadProgressUntilComplete(workflowStore.sessionId)
    workflowStore.setLodMinimumViablePrefs(minimumViablePrefs.value)
    workflowStore.goToStep(3)
    await persistWorkflowState(workflowStore, 'files')
    router.push('/workflow/files')
  } catch (err) {
    console.error('Failed to start local workflow scan:', err)
    const details = err?.error?.details
    if (details?.blockers?.length) {
      error.value = `The scan cannot start yet: ${details.blockers.join(' ')}`
    } else {
      error.value = err?.error?.message || err?.message || 'Failed to start the local scan.'
    }
    await runAnalysis()
  } finally {
    scanRunning.value = false
  }
}

const handleNext = async () => {
  workflowStore.setLodMinimumViablePrefs(minimumViablePrefs.value)
  if (requiresScanStart.value) {
    await startLocalScanAndContinue()
    return
  }
  workflowStore.goToStep(3)
  await persistWorkflowState(workflowStore, 'files')
  router.push('/workflow/files')
}

onMounted(async () => {
  if (!workflowStore.sessionId && route.query.sessionId) {
    workflowStore.setSessionId(Number(route.query.sessionId))
    workflowStore.setBatchMode(true)
    workflowStore.goToStep(2)
  }
  if (workflowStore.sessionId) {
    try {
      await persistWorkflowState(workflowStore, 'msf_analysis')
    } catch (err) {
      console.warn('Failed to persist MSF analysis workflow state:', err)
    }
  }
  if (workflowStore.sessionId && workflowStore.isBatchMode) {
    runAnalysis()
  }
})

watch(issues, (nextIssues) => {
  if (!nextIssues.length) {
    selectedIssueId.value = ''
    selectedCellKey.value = ''
    return
  }
  const stillValid = nextIssues.some(issue => issue.id === selectedIssueId.value)
  if (!stillValid) {
    selectedIssueId.value = (nextIssues.find(issue => issue.severity === 'error') || nextIssues[0])?.id || ''
  }
}, { immediate: true })

watch([issueSearch, issueSeverityFilter, issueLodFilter], () => {
  issuePage.value = 1
})

watch(totalIssuePages, (nextTotal) => {
  if (issuePage.value > nextTotal) {
    issuePage.value = nextTotal
  }
})
</script>
