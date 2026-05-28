<template>
  <div class="space-y-6">
    <section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-700">Zenodo Account Retrieval</p>
          <h2 class="mt-2 text-2xl font-semibold text-slate-900">Retrieve account records into persistent .hdpc collections</h2>
          <p class="mt-2 max-w-3xl text-sm text-slate-600">
            Harvest published records and drafts from an accessible Zenodo key, group shard sessions as one collection, and resume or incrementally sync long-running inventories.
          </p>
        </div>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Retrieved</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">{{ progress.retrieved_records || summary.retrieved_records || 0 }}</p>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Shards</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">{{ collection.shard_count || shards.length }}</p>
          </div>
          <div class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Rate Waits</p>
            <p class="mt-1 text-2xl font-semibold text-amber-800">{{ progress.rate_limited_waits || summary.rate_limited_waits || 0 }}</p>
          </div>
          <div class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">State</p>
            <p class="mt-1 text-sm font-semibold uppercase text-emerald-800">{{ currentJob?.state || 'Ready' }}</p>
          </div>
        </div>
      </div>
    </section>

    <section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div class="space-y-6">
        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Start Retrieval</h3>
              <p class="mt-1 text-xs text-slate-500">Scope is fixed to published records and drafts. Results are stored as one logical collection backed by manifest plus shard sessions.</p>
            </div>
            <button
              type="button"
              data-testid="zenodo-retrieval-start"
              class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="launching || !selectedCredentialId"
              @click="launchRetrieval"
            >
              {{ launching ? 'Queueing...' : 'Start Retrieval' }}
            </button>
            <button
              type="button"
              data-testid="zenodo-retrieval-preflight"
              class="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="preflighting || !selectedCredentialId"
              @click="runPreflight"
            >
              {{ preflighting ? 'Checking...' : 'Preflight' }}
            </button>
          </div>

          <div class="mt-5 grid gap-4 lg:grid-cols-4">
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Zenodo Key
              <select v-model="selectedCredentialId" data-testid="zenodo-retrieval-credential" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900">
                <option value="">Select a credential</option>
                <option v-for="credential in credentials" :key="credential.id" :value="String(credential.id)">
                  {{ credential.name }} · {{ formatEnvironment(credential.environment) }} · {{ credential.source === 'shared' ? 'Shared' : 'Mine' }}
                </option>
              </select>
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Record Limit
              <input
                v-model="maxRecords"
                data-testid="zenodo-retrieval-max-records"
                type="number"
                min="1"
                :max="maxRecordsCeiling || undefined"
                placeholder="No limit"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900"
              />
              <span class="mt-1 block text-[11px] font-normal normal-case tracking-normal text-slate-500">Leave blank to retrieve every accessible record.</span>
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Mode
              <select v-model="retrievalMode" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900">
                <option value="full">Full inventory</option>
                <option value="historical_backfill">Historical backfill</option>
              </select>
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Execution
              <select v-model="executionTarget" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900">
                <option value="celery_local">WebHDP worker</option>
                <option value="hpc_link">HPC-Link preflight</option>
              </select>
            </label>
          </div>

          <div class="mt-4 grid gap-4 lg:grid-cols-4">
            <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Scope</p>
              <p class="mt-1 text-sm font-medium text-slate-900">Published records + drafts</p>
              <p class="mt-1 text-xs text-slate-500">Uses authenticated depositions with all versions and adaptive date-window splitting.</p>
            </div>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Created After
              <input v-model="startDate" type="date" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Created Before
              <input v-model="endDate" type="date" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <div class="grid grid-cols-3 gap-2">
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Days
                <input v-model="initialWindowDays" type="number" min="1" max="366" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
              </label>
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Retries
                <input v-model="requestRetries" type="number" min="0" max="10" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
              </label>
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Timeout
                <input v-model="requestTimeoutSeconds" type="number" min="5" max="180" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
              </label>
            </div>
          </div>

          <div v-if="preflightReport" data-testid="zenodo-retrieval-preflight-report" class="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Preflight</p>
                <p class="mt-1 text-sm font-semibold" :class="preflightReport.queueable ? 'text-emerald-700' : 'text-amber-800'">
                  {{ preflightReport.queueable ? 'Ready to queue' : 'Review required before queueing' }}
                </p>
              </div>
              <p class="text-xs text-slate-500">{{ preflightReport.coverage?.matching_collection_count || 0 }} matching prior collections</p>
            </div>
            <div class="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-3">
              <p><span class="font-semibold text-slate-800">Execution:</span> {{ preflightReport.execution_target }}</p>
              <p><span class="font-semibold text-slate-800">Proxy:</span> {{ preflightReport.runtime_options?.proxy_policy || 'default' }}</p>
              <p><span class="font-semibold text-slate-800">Window:</span> {{ preflightReport.date_window?.start || 'beginning' }} to {{ preflightReport.date_window?.end || 'now' }}</p>
            </div>
            <ul v-if="preflightReport.warnings?.length" class="mt-3 space-y-1 text-xs text-amber-900">
              <li v-for="warning in preflightReport.warnings" :key="warning">{{ warning }}</li>
            </ul>
            <ul v-if="preflightReport.checks?.length" class="mt-3 grid gap-1 text-xs text-slate-600 md:grid-cols-2">
              <li v-for="check in preflightReport.checks" :key="check.key">{{ check.status }} · {{ check.label }}</li>
            </ul>
          </div>

          <div class="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
            <label class="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
              <input v-model="incremental" type="checkbox" class="mt-1 rounded border-slate-300 text-indigo-600" />
              <span>
                <span class="block font-semibold text-slate-900">Only retrieve new records since the latest matching collection</span>
                <span class="mt-1 block text-xs text-slate-500">Uses the latest successful retrieval for the same credential/environment, with overlap for indexing delay.</span>
              </span>
            </label>
            <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Overlap Hours
              <input
                v-model="incrementalOverlapHours"
                type="number"
                min="0"
                max="168"
                class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900"
              />
            </label>
          </div>

          <div v-if="incremental && recentCollections.length" class="mt-3 rounded-xl border border-indigo-100 bg-indigo-50 p-3 text-xs text-indigo-900">
            Latest collection candidate: {{ recentCollections[0]?.record_count || 0 }} records, latest created {{ recentCollections[0]?.latest_created || 'unknown' }}.
          </div>

          <div v-if="!credentials.length && !loadingContext" class="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            Add or accept a Zenodo key in Account Configuration before starting a retrieval.
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Coverage</h3>
              <p class="mt-1 text-xs text-slate-500">Successful retrievals are reusable inventory collections. Gaps and overlaps are detected from stored collection bounds.</p>
            </div>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="loadCoverage">
              Refresh Coverage
            </button>
          </div>
          <div class="mt-4 grid gap-3 text-sm md:grid-cols-4">
            <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Collections</p>
              <p class="mt-1 font-semibold text-slate-900">{{ coverage.collection_count || 0 }}</p>
            </div>
            <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Earliest</p>
              <p class="mt-1 font-semibold text-slate-900">{{ formatShortDate(coverage.earliest_created) }}</p>
            </div>
            <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Latest</p>
              <p class="mt-1 font-semibold text-slate-900">{{ formatShortDate(coverage.latest_created) }}</p>
            </div>
            <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Gaps</p>
              <p class="mt-1 font-semibold text-slate-900">{{ coverage.gaps?.length || 0 }}</p>
            </div>
          </div>
          <div v-if="coverage.gaps?.length" class="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <p v-for="gap in coverage.gaps" :key="`${gap.after_retrieval_id}-${gap.before_retrieval_id}`">
              Gap from {{ formatShortDate(gap.start) }} to {{ formatShortDate(gap.end) }}.
            </p>
          </div>
          <div v-if="coverage.timeline?.length" class="mt-4 divide-y divide-slate-100">
            <div v-for="item in coverage.timeline" :key="item.retrieval_id" class="flex flex-col gap-2 py-3 md:flex-row md:items-center md:justify-between">
              <div>
                <p class="text-sm font-semibold text-slate-900">{{ item.retrieval_mode || item.sync_mode || 'full' }} · {{ item.record_count || 0 }} records</p>
                <p class="mt-1 text-xs text-slate-500">{{ formatShortDate(item.earliest_created) }} to {{ formatShortDate(item.latest_created || item.latest_modified) }} · {{ item.retrieval_id }}</p>
              </div>
              <button type="button" class="w-fit rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="backfillBefore(item)">
                Backfill Before
              </button>
            </div>
          </div>
          <p v-else class="mt-4 text-sm text-slate-500">No completed retrieval collections yet.</p>
        </section>

        <section v-if="currentJob" data-testid="zenodo-retrieval-current-job" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Current Retrieval</h3>
              <p class="mt-1 break-all text-xs text-slate-500">{{ currentJob.retrieval_id }}</p>
              <p class="mt-2 text-sm text-slate-600">{{ currentJob.status || 'Waiting for updates...' }}</p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="!canPause" @click="pauseJob">Pause</button>
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="!canResume" @click="resumeJob">Resume</button>
              <button type="button" class="rounded-lg border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50" :disabled="!canCancel" @click="cancelJob">Cancel</button>
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="compacting || currentJob.state !== 'SUCCESS'" @click="compactJob">Compact</button>
              <button type="button" class="rounded-lg border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50" :disabled="deleting" @click="deleteJob">Delete Files</button>
            </div>
          </div>
          <div v-if="currentJob.stale" class="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            This job has not reported a heartbeat recently. Resume the same retrieval after confirming no worker is still running.
          </div>
          <div class="mt-4 h-3 overflow-hidden rounded-full bg-slate-100">
            <div class="h-full rounded-full bg-indigo-600 transition-all duration-300" :style="{ width: `${progress.percent || 0}%` }"></div>
          </div>
          <div class="mt-4 grid grid-cols-2 gap-3 text-sm md:grid-cols-6">
            <div><p class="text-slate-500">Windows</p><p class="font-semibold text-slate-900">{{ progress.processed_windows || 0 }} / {{ (progress.processed_windows || 0) + (progress.pending_windows || 0) }}</p></div>
            <div><p class="text-slate-500">Pending</p><p class="font-semibold text-slate-900">{{ progress.pending_windows || 0 }}</p></div>
            <div><p class="text-slate-500">Published</p><p class="font-semibold text-slate-900">{{ summary.published_records || 0 }}</p></div>
            <div><p class="text-slate-500">Drafts</p><p class="font-semibold text-slate-900">{{ summary.draft_records || 0 }}</p></div>
            <div><p class="text-slate-500">Environment</p><p class="font-semibold capitalize text-slate-900">{{ currentJob.environment }}</p></div>
            <div><p class="text-slate-500">Limit</p><p class="font-semibold text-slate-900">{{ progress.max_records || summary.max_records || 'None' }}</p></div>
            <div><p class="text-slate-500">Window</p><p class="font-semibold text-slate-900">{{ formatJobWindow(currentJob) }}</p></div>
            <div><p class="text-slate-500">Mode</p><p class="font-semibold capitalize text-slate-900">{{ collection.sync_mode || currentJob.options?.sync_mode || 'full' }}</p></div>
            <div><p class="text-slate-500">Duplicates</p><p class="font-semibold text-slate-900">{{ progress.duplicate_records_skipped || summary.duplicate_records_skipped || 0 }}</p></div>
            <div><p class="text-slate-500">Splits</p><p class="font-semibold text-slate-900">{{ progress.split_windows || summary.split_windows || 0 }}</p></div>
            <div><p class="text-slate-500">Deferred</p><p class="font-semibold text-slate-900">{{ progress.deferred_windows || summary.deferred_windows || 0 }}</p></div>
            <div><p class="text-slate-500">Wait</p><p class="font-semibold text-slate-900">{{ formatDuration(progress.wait_seconds || summary.wait_seconds) }}</p></div>
            <div><p class="text-slate-500">Records/hour</p><p class="font-semibold text-slate-900">{{ progress.records_per_hour || 0 }}</p></div>
            <div><p class="text-slate-500">Pages/hour</p><p class="font-semibold text-slate-900">{{ progress.pages_per_hour || 0 }}</p></div>
            <div><p class="text-slate-500">ETA</p><p class="font-semibold text-slate-900">{{ formatDuration(progress.eta_seconds) }} <span class="text-xs font-normal text-slate-500">{{ progress.eta_confidence || '' }}</span></p></div>
            <div><p class="text-slate-500">Latest</p><p class="font-semibold text-slate-900">{{ formatShortDate(collection.latest_created || progress.latest_created) }}</p></div>
          </div>
          <p class="mt-3 text-xs text-slate-500">
            ETA uses current effective throughput and can rise during dense windows, retries, duplicate skips, or Zenodo rate-limit waits.
          </p>
          <div class="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div class="flex items-center justify-between gap-3">
              <div>
                <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Diagnostics</p>
                <p class="mt-1 text-sm font-semibold text-slate-900">{{ diagnostics.process_health?.status || 'unknown' }} · heartbeat {{ formatDuration(diagnostics.heartbeat_age_seconds) }}</p>
              </div>
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-white" @click="loadDiagnostics">
                Refresh
              </button>
            </div>
            <div class="mt-3 grid gap-2 text-xs text-slate-600 md:grid-cols-3">
              <p>Target: {{ diagnostics.execution_target || currentJob.runtime?.execution_target || 'celery_local' }}</p>
              <p>Task/PID: {{ diagnostics.process_health?.task_id || currentJob.task_id || 'N/A' }} / {{ diagnostics.process_health?.pid || 'N/A' }}</p>
              <p>Proxy: {{ diagnostics.runtime?.proxy_policy || currentJob.runtime?.proxy_policy || 'default' }}</p>
              <p>Shard root: {{ diagnostics.runtime?.shard_root || currentJob.runtime?.shard_root || 'N/A' }}</p>
              <p>Script: {{ diagnostics.runtime?.script_version || currentJob.runtime?.script_version || 'unknown' }}</p>
              <p>Current page: {{ diagnostics.window?.page || progress.current_page || 'N/A' }}</p>
            </div>
            <div v-if="diagnostics.log_tail?.length" class="mt-3 rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
              <p v-for="line in diagnostics.log_tail" :key="line" class="truncate">{{ line }}</p>
            </div>
          </div>
          <div class="mt-4 flex flex-wrap gap-2">
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="downloadExport('manifest')">Manifest</button>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="downloadExport('csv')">CSV Index</button>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="downloadExport('archive')">Shard Archive</button>
          </div>
          <div class="mt-4 grid gap-3 lg:grid-cols-2">
            <label class="flex items-center gap-2 text-sm text-slate-700">
              <input v-model="keepOriginalShards" type="checkbox" class="rounded border-slate-300 text-indigo-600" />
              Keep original shards
            </label>
            <label class="flex items-center gap-2 text-sm text-slate-700">
              <input v-model="keepCompactedShards" type="checkbox" class="rounded border-slate-300 text-indigo-600" />
              Keep compacted shards
            </label>
            <button type="button" class="w-fit rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="saveRetention">
              Save Retention
            </button>
          </div>
          <div class="mt-4 grid gap-3 border-t border-slate-100 pt-4 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
            <label class="flex items-center gap-2 text-sm text-slate-700">
              <input v-model="scheduleEnabled" type="checkbox" class="rounded border-slate-300 text-indigo-600" />
              Schedule incremental sync
            </label>
            <select v-model="scheduleFrequency" class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900">
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
            <div class="flex gap-2">
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" :disabled="currentJob.state !== 'SUCCESS'" @click="saveSchedule">Save</button>
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" :disabled="currentJob.state !== 'SUCCESS'" @click="runScheduleNow">Run</button>
            </div>
          </div>
        </section>

        <section v-if="currentJob" data-testid="zenodo-retrieval-search" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Collection Search</h3>
              <p class="mt-1 text-xs text-slate-500">Search across all retrieval shards as one collection.</p>
            </div>
            <div class="flex flex-col gap-2 sm:flex-row">
              <input v-model="recordSearch" data-testid="zenodo-retrieval-search-input" type="search" placeholder="Title, DOI, record ID" class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900" />
              <select v-model="recordStatus" class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900">
                <option value="">All statuses</option>
                <option value="published">Published</option>
                <option value="draft">Draft</option>
              </select>
              <button type="button" data-testid="zenodo-retrieval-search-submit" class="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white" @click="searchRecords">Search</button>
            </div>
          </div>
          <div v-if="recordResults.length" data-testid="zenodo-retrieval-search-results" class="mt-4 divide-y divide-slate-100">
            <div v-for="record in recordResults" :key="`${record.session_id}-${record.local_record_id}`" class="py-3">
              <p class="text-sm font-semibold text-slate-900">{{ record.title }}</p>
              <p class="mt-1 text-xs text-slate-500">{{ record.status }} · {{ record.zenodo_record_id || 'no record id' }} · {{ record.doi || 'no DOI' }}</p>
            </div>
          </div>
          <p v-else class="mt-4 text-sm text-slate-500">{{ recordSearchMessage }}</p>
        </section>

        <section v-if="currentJob" data-testid="zenodo-retrieval-detectors" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Collection Detectors</h3>
              <p class="mt-1 text-xs text-slate-500">Run saved searches against local shards only, then export candidates for review or community migration.</p>
            </div>
            <div class="flex flex-col gap-2 sm:flex-row">
              <select v-model="selectedDetector" data-testid="zenodo-retrieval-detector-select" class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900">
                <option v-for="detector in detectorPresets" :key="detector.id" :value="detector.id">{{ detector.label }}</option>
              </select>
              <input v-model="targetCommunity" data-testid="zenodo-retrieval-target-community" type="text" class="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900" placeholder="Target community" />
              <button type="button" data-testid="zenodo-retrieval-detector-run" class="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white" @click="runDetector">Run</button>
            </div>
          </div>
          <div v-if="detectorResult" data-testid="zenodo-retrieval-detector-results" class="mt-4">
            <div class="flex flex-wrap items-center gap-2">
              <p class="text-sm font-semibold text-slate-900">{{ detectorResult.total || 0 }} candidates</p>
              <p v-if="detectorResult.source" class="text-xs font-medium text-slate-500">{{ detectorResult.source }}</p>
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="downloadDetectorExport">
                Export CSV
              </button>
              <router-link to="/tools/community-migration" class="rounded-lg border border-indigo-200 px-3 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-50">
                Community Migration
              </router-link>
            </div>
            <div class="mt-3 divide-y divide-slate-100">
              <div v-for="candidate in detectorCandidates" :key="`${candidate.session_id}-${candidate.local_record_id}`" class="py-3">
                <p class="text-sm font-semibold text-slate-900">{{ candidate.title }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ candidate.reason }} · {{ candidate.zenodo_record_id || 'no record id' }}</p>
              </div>
            </div>
          </div>
          <p v-else class="mt-4 text-sm text-slate-500">No detector has been run for this collection yet.</p>
        </section>

        <section data-testid="zenodo-retrieval-shards" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Generated Shards</h3>
              <p class="mt-1 text-xs text-slate-500">Each shard is a completed explorer-only session with its own .hdpc file.</p>
            </div>
            <router-link to="/records/explorer" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
              Cross-Session Explorer
            </router-link>
          </div>
          <div v-if="!shards.length" class="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">
            No retrieval shards have been created yet.
          </div>
          <div v-else class="mt-4 divide-y divide-slate-100">
            <div v-for="shard in shards" :key="`${currentJob.retrieval_id}-${shard.shard_index}`" class="flex flex-col gap-3 py-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p class="text-sm font-semibold text-slate-900">Shard {{ shard.shard_index }} · Session #{{ shard.session_id }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ shard.record_count }} records · {{ shard.window?.status || 'mixed' }} · {{ formatWindow(shard.window) }}</p>
              </div>
              <div class="flex flex-wrap gap-2">
                <router-link :to="`/sessions/${shard.session_id}/records`" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                  Open Records
                </router-link>
              </div>
            </div>
          </div>
        </section>
      </div>

      <aside class="space-y-6 xl:sticky xl:top-24 xl:self-start">
        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <h3 class="text-sm font-semibold text-slate-900">Recent Jobs</h3>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="loadJobs">
              Refresh
            </button>
          </div>
          <div v-if="historyLoading" class="mt-4 text-sm text-slate-500">Loading retrieval history...</div>
          <div v-else-if="jobs.length === 0" class="mt-4 text-sm text-slate-500">No account retrievals yet.</div>
          <div v-else class="mt-4 space-y-3">
            <button
              v-for="job in jobs"
              :key="job.retrieval_id"
              type="button"
              class="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-left transition hover:bg-white"
              @click="restoreJob(job)"
            >
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-semibold text-slate-900">{{ job.state || 'PENDING' }}</p>
                <span class="text-xs text-slate-500">{{ job.summary?.retrieved_records || 0 }} records</span>
              </div>
              <p class="mt-1 truncate text-xs text-slate-500">{{ job.retrieval_id }}</p>
              <p class="mt-1 text-xs text-slate-500">{{ formatDate(job.updated_at || job.created_at) }}</p>
            </button>
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
const credentials = ref([])
const selectedCredentialId = ref('')
const maxRecords = ref('')
const maxRecordsCeiling = ref(null)
const startDate = ref('')
const endDate = ref('')
const retrievalMode = ref('full')
const executionTarget = ref('celery_local')
const initialWindowDays = ref(31)
const requestRetries = ref(2)
const requestTimeoutSeconds = ref(30)
const incremental = ref(false)
const incrementalOverlapHours = ref(24)
const recentCollections = ref([])
const coverage = ref({ timeline: [], gaps: [], overlaps: [], collection_count: 0 })
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
const recordSearch = ref('')
const recordStatus = ref('')
const recordResults = ref([])
const recordSearchMessage = ref('Run a search to inspect retrieval records across shards.')
const selectedDetector = ref('community_migration_candidates')
const targetCommunity = ref('3dbigdataspace')
const detectorResult = ref(null)
const keepOriginalShards = ref(true)
const keepCompactedShards = ref(true)
const scheduleEnabled = ref(false)
const scheduleFrequency = ref('weekly')
let pollTimer = null

const progress = computed(() => currentJob.value?.progress || {})
const summary = computed(() => currentJob.value?.summary || {})
const collection = computed(() => currentJob.value?.collection || {})
const shards = computed(() => currentJob.value?.manifest?.shards || [])
const diagnostics = computed(() => currentJob.value?.diagnostics || {})
const detectorCandidates = computed(() => detectorResult.value?.candidates || [])
const terminalStates = ['SUCCESS', 'FAILURE', 'CANCELLED']
const canPause = computed(() => currentJob.value && !terminalStates.includes(currentJob.value.state) && currentJob.value.state !== 'PAUSED')
const canResume = computed(() => currentJob.value?.state === 'PAUSED')
const canCancel = computed(() => currentJob.value && !terminalStates.includes(currentJob.value.state))

const formatEnvironment = (value) => String(value || '').replace('production', 'Production').replace('sandbox', 'Sandbox')
const formatDate = (value) => {
  if (!value) return 'N/A'
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  } catch {
    return value
  }
}
const formatShortDate = (value) => value ? String(value).slice(0, 10) : 'N/A'
const formatDuration = (seconds) => {
  if (!seconds && seconds !== 0) return 'N/A'
  const value = Number(seconds)
  if (!Number.isFinite(value)) return 'N/A'
  if (value < 60) return `${Math.round(value)}s`
  if (value < 3600) return `${Math.round(value / 60)}m`
  return `${Math.round(value / 3600)}h`
}
const formatWindow = (window) => {
  if (!window) return 'N/A'
  return `${window.start || '?'} to ${window.end || '?'}`
}
const formatJobWindow = (job) => {
  const options = job?.options || {}
  const start = options.start_datetime?.slice(0, 10)
  const end = options.end_datetime?.slice(0, 10)
  if (!start && !end) return 'All time'
  return `${start || '...'} to ${end || '...'}`
}

const loadContext = async () => {
  loadingContext.value = true
  try {
    const response = await toolsService.getZenodoAccountRetrievalContext()
    credentials.value = response.data?.credentials || []
    const activeProduction = response.data?.active?.production
    const firstCredential = activeProduction || credentials.value[0]
    selectedCredentialId.value = firstCredential?.id ? String(firstCredential.id) : ''
    maxRecordsCeiling.value = response.data?.defaults?.max_records_ceiling || null
    retrievalMode.value = response.data?.defaults?.retrieval_mode || 'full'
    executionTarget.value = response.data?.defaults?.execution_target || 'celery_local'
    initialWindowDays.value = response.data?.defaults?.initial_window_days || 31
    requestRetries.value = response.data?.defaults?.request_retries ?? 2
    requestTimeoutSeconds.value = response.data?.defaults?.request_timeout_seconds || 30
    incrementalOverlapHours.value = response.data?.defaults?.incremental_overlap_hours || 24
    recentCollections.value = response.data?.recent_collections || []
    coverage.value = response.data?.coverage || { timeline: [], gaps: [], overlaps: [], collection_count: 0 }
    detectorPresets.value = response.data?.detectors?.length ? response.data.detectors : detectorPresets.value
  } catch (err) {
    console.error('Failed to load Zenodo account retrieval context', err)
    toast.error(err.error?.message || err.message || 'Failed to load retrieval context')
  } finally {
    loadingContext.value = false
  }
}

const loadCoverage = async () => {
  try {
    const params = {}
    if (selectedCredentialId.value) params.credential_id = Number(selectedCredentialId.value)
    const credential = credentials.value.find((item) => String(item.id) === String(selectedCredentialId.value))
    if (credential?.environment) params.environment = credential.environment
    const response = await toolsService.getZenodoAccountRetrievalCoverage(params)
    coverage.value = response.data?.coverage || coverage.value
  } catch (err) {
    console.error('Failed to load Zenodo account retrieval coverage', err)
    toast.error(err.error?.message || err.message || 'Failed to load retrieval coverage')
  }
}

const loadJobs = async () => {
  historyLoading.value = true
  try {
    const response = await toolsService.listZenodoAccountRetrievalJobs({ limit: 12 })
    jobs.value = response.data?.jobs || []
    if (!currentJob.value && jobs.value.length) {
      currentJob.value = jobs.value[0]
    }
  } catch (err) {
    console.error('Failed to load Zenodo account retrieval jobs', err)
  } finally {
    historyLoading.value = false
  }
}

const pollJob = async () => {
  if (!currentJob.value?.retrieval_id) return
  try {
    const response = await toolsService.getZenodoAccountRetrievalJob(currentJob.value.retrieval_id)
    currentJob.value = response.data || currentJob.value
    if (terminalStates.includes(currentJob.value.state) || currentJob.value.state === 'PAUSED') {
      clearPoll()
      await loadJobs()
    }
  } catch (err) {
    console.error('Failed to poll Zenodo account retrieval job', err)
    clearPoll()
  }
}

const loadDiagnostics = async () => {
  if (!currentJob.value?.retrieval_id) return
  try {
    const response = await toolsService.getZenodoAccountRetrievalDiagnostics(currentJob.value.retrieval_id)
    currentJob.value = {
      ...currentJob.value,
      diagnostics: response.data?.diagnostics || currentJob.value.diagnostics,
    }
  } catch (err) {
    console.error('Failed to load Zenodo retrieval diagnostics', err)
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

const launchRetrieval = async () => {
  launching.value = true
  try {
    const payload = buildRetrievalPayload()
    if (payload.execution_target !== 'celery_local') {
      toast.error('Draco is currently preflight-only from this page')
      return
    }
    if (String(maxRecords.value || '').trim()) {
      payload.max_records = Number(maxRecords.value)
    }
    const response = await toolsService.launchZenodoAccountRetrieval(payload)
    currentJob.value = {
      retrieval_id: response.data?.retrieval_id,
      task_id: response.data?.task_id,
      state: 'PENDING',
      status: 'Queued Zenodo account retrieval',
      environment: response.data?.environment,
      progress: { percent: 0, max_records: response.data?.max_records || null },
      summary: { max_records: response.data?.max_records || null },
      manifest: { shards: [] },
      options: {
        start_datetime: response.data?.date_window?.start || null,
        end_datetime: response.data?.date_window?.end || null,
        retrieval_mode: response.data?.retrieval_mode || 'full',
        sync_mode: response.data?.sync_mode || 'full',
        parent_retrieval_id: response.data?.parent_retrieval_id || null,
      },
      runtime: {
        execution_target: response.data?.execution_target || 'celery_local',
      },
      preflight: response.data?.preflight || null,
      collection: {
        retrieval_mode: response.data?.retrieval_mode || 'full',
        sync_mode: response.data?.sync_mode || 'full',
        parent_retrieval_id: response.data?.parent_retrieval_id || null,
      },
    }
    toast.success('Zenodo account retrieval queued')
    await pollJob()
    startPoll()
    await loadJobs()
  } catch (err) {
    console.error('Failed to queue Zenodo account retrieval', err)
    toast.error(err.error?.message || err.message || 'Failed to queue retrieval')
  } finally {
    launching.value = false
  }
}

const buildRetrievalPayload = () => {
  const payload = {
    credential_id: Number(selectedCredentialId.value),
    retrieval_mode: incremental.value ? 'incremental' : retrievalMode.value,
    execution_target: executionTarget.value,
    initial_window_days: Number(initialWindowDays.value || 31),
    request_retries: Number(requestRetries.value ?? 2),
    request_timeout_seconds: Number(requestTimeoutSeconds.value || 30),
  }
  if (String(maxRecords.value || '').trim()) payload.max_records = Number(maxRecords.value)
  if (startDate.value) payload.start_date = startDate.value
  if (endDate.value) payload.end_date = endDate.value
  if (incremental.value) {
    payload.sync_mode = 'incremental'
    payload.incremental_overlap_hours = Number(incrementalOverlapHours.value || 24)
  }
  return payload
}

const backfillBefore = (collectionItem) => {
  incremental.value = false
  retrievalMode.value = 'historical_backfill'
  executionTarget.value = 'celery_local'
  if (collectionItem?.earliest_created) {
    endDate.value = String(collectionItem.earliest_created).slice(0, 10)
  }
  preflightReport.value = null
  toast.success('Historical backfill defaults applied')
}

const runPreflight = async () => {
  preflighting.value = true
  try {
    const response = await toolsService.preflightZenodoAccountRetrieval(buildRetrievalPayload())
    preflightReport.value = response.data?.preflight || null
    if (preflightReport.value?.queueable) {
      toast.success('Retrieval preflight passed')
    } else {
      toast.warning('Retrieval preflight needs review')
    }
  } catch (err) {
    console.error('Failed to preflight Zenodo account retrieval', err)
    toast.error(err.error?.message || err.message || 'Failed to preflight retrieval')
  } finally {
    preflighting.value = false
  }
}

const compactJob = async () => {
  if (!currentJob.value?.retrieval_id) return
  compacting.value = true
  try {
    const response = await toolsService.compactZenodoAccountRetrieval(currentJob.value.retrieval_id, { target_records_per_shard: 5000 })
    currentJob.value = response.data?.job || currentJob.value
    toast.success('Retrieval collection compacted')
  } catch (err) {
    console.error('Failed to compact retrieval', err)
    toast.error(err.error?.message || err.message || 'Failed to compact retrieval')
  } finally {
    compacting.value = false
  }
}

const searchRecords = async () => {
  if (!currentJob.value?.retrieval_id) return
  const response = await toolsService.searchZenodoAccountRetrievalRecords(currentJob.value.retrieval_id, {
    q: recordSearch.value || undefined,
    status: recordStatus.value || undefined,
    limit: 25,
  })
  recordResults.value = response.data?.records || []
  recordSearchMessage.value = recordResults.value.length ? '' : 'No records matched.'
}

const runDetector = async () => {
  if (!currentJob.value?.retrieval_id) return
  const response = await toolsService.runZenodoAccountRetrievalDetector(currentJob.value.retrieval_id, {
    detector: selectedDetector.value,
    target_community: targetCommunity.value || undefined,
    limit: 25,
  })
  detectorResult.value = response.data || null
}

const detectorExportUrl = () => {
  if (!currentJob.value?.retrieval_id) return '#'
  const params = new URLSearchParams({
    detector: selectedDetector.value,
    target_community: targetCommunity.value || '',
  })
  return `/api/v1/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(currentJob.value.retrieval_id)}/detectors/export?${params.toString()}`
}

const downloadDetectorExport = async () => {
  if (!currentJob.value?.retrieval_id) return
  const token = sessionStorage.getItem('token') || localStorage.getItem('token')
  const response = await window.fetch(detectorExportUrl(), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) {
    toast.error('Detector export failed')
    return
  }
  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `zenodo-retrieval-${currentJob.value.retrieval_id}-${selectedDetector.value}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

const saveRetention = async () => {
  if (!currentJob.value?.retrieval_id) return
  const response = await toolsService.updateZenodoAccountRetrievalRetention(currentJob.value.retrieval_id, {
    keep_original_shards: keepOriginalShards.value,
    keep_compacted_shards: keepCompactedShards.value,
  })
  currentJob.value = response.data || currentJob.value
  toast.success('Retention policy saved')
}

const saveSchedule = async () => {
  if (!currentJob.value?.retrieval_id) return
  const response = await toolsService.updateZenodoAccountRetrievalSchedule(currentJob.value.retrieval_id, {
    enabled: scheduleEnabled.value,
    frequency: scheduleFrequency.value,
    incremental_overlap_hours: Number(incrementalOverlapHours.value || 24),
  })
  currentJob.value = response.data || currentJob.value
  toast.success('Incremental schedule saved')
}

const runScheduleNow = async () => {
  if (!currentJob.value?.retrieval_id) return
  const response = await toolsService.runZenodoAccountRetrievalScheduleNow(currentJob.value.retrieval_id)
  currentJob.value = response.data || currentJob.value
  toast.success('Scheduled incremental retrieval queued')
  startPoll()
  await loadJobs()
}

const exportUrl = (format) => {
  if (!currentJob.value?.retrieval_id) return '#'
  return `/api/v1/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(currentJob.value.retrieval_id)}/export/${format}`
}

const downloadExport = async (format) => {
  if (!currentJob.value?.retrieval_id) return
  const token = sessionStorage.getItem('token') || localStorage.getItem('token')
  const response = await window.fetch(exportUrl(format), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) {
    toast.error('Export failed')
    return
  }
  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  const extension = format === 'archive' ? 'zip' : format === 'csv' ? 'csv' : 'json'
  link.href = url
  link.download = `zenodo-retrieval-${currentJob.value.retrieval_id}.${extension}`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

const pauseJob = async () => {
  if (!currentJob.value?.retrieval_id) return
  await toolsService.pauseZenodoAccountRetrieval(currentJob.value.retrieval_id)
  toast.success('Pause requested')
  await pollJob()
}

const resumeJob = async () => {
  if (!currentJob.value?.retrieval_id) return
  const response = await toolsService.resumeZenodoAccountRetrieval(currentJob.value.retrieval_id)
  currentJob.value = response.data || currentJob.value
  toast.success('Retrieval resumed')
  startPoll()
}

const cancelJob = async () => {
  if (!currentJob.value?.retrieval_id) return
  await toolsService.cancelZenodoAccountRetrieval(currentJob.value.retrieval_id)
  toast.success('Cancel requested')
  await pollJob()
}

const deleteJob = async () => {
  if (!currentJob.value?.retrieval_id) return
  deleting.value = true
  try {
    await toolsService.deleteZenodoAccountRetrieval(currentJob.value.retrieval_id)
    toast.success('Retrieval files deleted')
    currentJob.value = null
    await loadJobs()
  } catch (err) {
    console.error('Failed to delete Zenodo account retrieval', err)
    toast.error(err.error?.message || err.message || 'Failed to delete retrieval files')
  } finally {
    deleting.value = false
  }
}

const restoreJob = async (job) => {
  currentJob.value = job
  await pollJob()
  if (currentJob.value && !terminalStates.includes(currentJob.value.state) && currentJob.value.state !== 'PAUSED') {
    startPoll()
  }
}

onMounted(async () => {
  await Promise.all([loadContext(), loadJobs()])
  await loadCoverage()
  if (currentJob.value && !terminalStates.includes(currentJob.value.state) && currentJob.value.state !== 'PAUSED') {
    startPoll()
  }
})

onBeforeUnmount(clearPoll)
</script>
