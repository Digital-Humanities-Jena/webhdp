<template>
  <div class="space-y-6">
    <section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">Zenodo Community Moderation</p>
          <h2 class="mt-2 text-2xl font-semibold text-slate-900">Community Moderation Panel</h2>
          <p class="mt-2 max-w-3xl text-sm text-slate-600">
            Use Review Mode for selected visible requests, or Sweep Mode for an authoritative submitted-request queue.
          </p>
          <p class="mt-3 text-xs text-slate-500">
            Resolved community:
            <span class="font-semibold text-slate-700">{{ resolvedCommunityLabel }}</span>
            <span v-if="resolutionSourceLabel" class="ml-2 rounded-full border border-slate-300 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
              {{ resolutionSourceLabel }}
            </span>
          </p>
        </div>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Review Open</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">{{ summary.open_requests_total || 0 }}</p>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Filtered</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">{{ summary.requests_filtered || 0 }}</p>
          </div>
          <div class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Selected</p>
            <p class="mt-1 text-2xl font-semibold text-emerald-800">{{ selectedCount }}</p>
          </div>
          <div class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Submitted</p>
            <p class="mt-1 text-2xl font-semibold text-amber-800">{{ sweepPlan?.summary?.planned_requests ?? '-' }}</p>
          </div>
        </div>
      </div>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-2 shadow-sm">
      <div class="grid gap-2 sm:grid-cols-2">
        <button
          type="button"
          :class="activeMode === 'review' ? 'bg-cyan-600 text-white' : 'bg-white text-slate-700 hover:bg-slate-50'"
          class="rounded-xl px-4 py-3 text-sm font-semibold transition"
          @click="activeMode = 'review'"
        >
          Review Mode
        </button>
        <button
          type="button"
          :class="activeMode === 'sweep' ? 'bg-cyan-600 text-white' : 'bg-white text-slate-700 hover:bg-slate-50'"
          class="rounded-xl px-4 py-3 text-sm font-semibold transition"
          @click="activeMode = 'sweep'"
        >
          Sweep Mode
        </button>
      </div>
    </section>

    <section v-if="activeMode === 'review'" class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div class="space-y-6">
        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Review Filters</h3>
              <p class="mt-1 text-xs text-slate-500">The Review list is a bounded browser for selected-request batches.</p>
            </div>
            <div class="flex gap-2">
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50" :disabled="loading" @click="resetFilters">
                Reset
              </button>
              <button type="button" class="rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60" :disabled="loading" @click="applyFilters">
                Apply Filters
              </button>
            </div>
          </div>

          <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <select v-model="filters.institution_id" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" @change="handleInstitutionChange">
              <option value="">No institution context</option>
              <option v-for="institution in institutionOptions" :key="institution.id" :value="String(institution.id)">
                {{ institution.name }}
              </option>
            </select>
            <input :value="filters.community_identifier" type="text" placeholder="Community identifier" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" @input="handleCommunityIdentifierInput($event.target.value)" />
            <input v-model="filters.q" type="text" placeholder="Search request id, title, topic, users" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <select v-model="filters.request_type" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
              <option value="">All request types</option>
              <option v-for="requestType in requestTypes" :key="requestType" :value="requestType">{{ requestType }}</option>
            </select>
            <select v-model.number="filters.per_page" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
              <option :value="10">10 / page</option>
              <option :value="25">25 / page</option>
              <option :value="50">50 / page</option>
            </select>
            <label class="text-xs font-medium uppercase tracking-wide text-slate-500">
              Created From
              <input v-model="filters.created_from" type="datetime-local" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-medium uppercase tracking-wide text-slate-500">
              Created To
              <input v-model="filters.created_to" type="datetime-local" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-medium uppercase tracking-wide text-slate-500">
              Updated From
              <input v-model="filters.updated_from" type="datetime-local" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-medium uppercase tracking-wide text-slate-500">
              Updated To
              <input v-model="filters.updated_to" type="datetime-local" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
          </div>

          <div class="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div class="flex flex-wrap items-center gap-2">
              <span v-if="selectedInstitutionLabel" class="rounded-full border border-slate-300 bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700">
                {{ selectedInstitutionLabel }}
              </span>
              <span v-if="moderationContext.candidate_default_communities?.length" class="text-xs text-slate-500">
                Candidate defaults:
              </span>
              <button
                v-for="candidate in moderationContext.candidate_default_communities || []"
                :key="candidate"
                type="button"
                class="rounded-full border border-cyan-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-cyan-700 hover:bg-cyan-50"
                @click="selectModerationCandidate(candidate)"
              >
                {{ candidate }}
              </button>
            </div>
            <p v-if="moderationContext.primary_submission_community" class="mt-2 text-xs text-slate-500">
              Primary submission fallback: <span class="font-semibold text-slate-700">{{ moderationContext.primary_submission_community }}</span>
            </p>
            <p v-if="institutionsLoading" class="mt-2 text-xs text-slate-500">Loading institution context...</p>
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Selection</h3>
              <p class="mt-1 text-xs text-slate-500">Select current page, all filtered results, or clear the current selection.</p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="selectCurrentPage">
                Select Current Page
              </button>
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="selectAllFiltered">
                Select Filtered Results
              </button>
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="clearSelection">
                Clear Selection
              </button>
            </div>
          </div>
          <div class="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
            <span>{{ selectedCount }} selected</span>
            <span v-if="selectedOutsideCurrentFiltersCount > 0">{{ selectedOutsideCurrentFiltersCount }} selected outside current filters</span>
            <span>{{ allFilteredRequestIds.length }} filtered requests available</span>
          </div>
        </section>

        <LoadingSpinner v-if="loading" size="lg" text="Loading community moderation queue..." />

        <section v-else-if="error" class="rounded-2xl border border-rose-200 bg-white p-6 shadow-sm">
          <Alert v-model="showError" variant="error" :message="error" :dismissible="false" />
        </section>

        <section v-else class="space-y-5">
          <div v-if="requests.length === 0" class="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500 shadow-sm">
            No open requests match the current filters.
          </div>

          <article
            v-for="item in requests"
            :key="item.request_id"
            class="grid gap-4 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm lg:grid-cols-[auto_minmax(0,1.3fr)_minmax(0,0.8fr)_auto]"
          >
            <div class="pt-1">
              <input :checked="isSelected(item)" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500" @change="toggleRequest(item)" />
            </div>

            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <p class="text-sm font-semibold text-slate-900">{{ item.title || 'Untitled request' }}</p>
                <span class="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-cyan-700">{{ item.type || 'unknown' }}</span>
                <span :class="item.is_actionable ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'" class="rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide">
                  {{ item.is_actionable ? 'Actionable' : 'Blocked' }}
                </span>
              </div>
              <p class="mt-1 text-xs text-slate-500">
                Request {{ item.number || 'N/A' }} - {{ item.request_id }} - Topic {{ item.topic_record || 'N/A' }}
              </p>
              <p class="mt-2 text-sm text-slate-600">
                Created by {{ item.created_by?.user || 'unknown' }} - Receiver {{ item.receiver?.user || 'unknown' }}
              </p>
            </div>

            <div class="min-w-0">
              <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Created / Updated</p>
              <p class="mt-1 text-sm text-slate-700">{{ formatDate(item.created) }}</p>
              <p class="text-xs text-slate-500">{{ formatDate(item.updated) }}</p>
              <p class="mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Status</p>
              <p class="mt-1 text-sm text-slate-700">{{ item.status || 'unknown' }}</p>
            </div>

            <div class="flex items-start justify-end">
              <a v-if="item.links?.self" :href="item.links.self" target="_blank" rel="noopener noreferrer" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                Open API
              </a>
            </div>
          </article>

          <div v-if="pagination.total_pages > 1" class="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
            <p class="text-sm text-slate-600">Page {{ pagination.page }} of {{ pagination.total_pages }}</p>
            <div class="flex gap-2">
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="!pagination.has_previous || loading" @click="changePage(pagination.page - 1)">
                Previous
              </button>
              <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="!pagination.has_next || loading" @click="changePage(pagination.page + 1)">
                Next
              </button>
            </div>
          </div>
        </section>
      </div>

      <aside class="space-y-6 xl:sticky xl:top-24 xl:self-start">
        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 class="text-sm font-semibold text-slate-900">Review Action</h3>
          <div class="mt-4 space-y-4">
            <div>
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">Batch Action</label>
              <select v-model="action.action" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
                <option value="accept">Accept</option>
                <option value="decline">Decline</option>
              </select>
            </div>

            <div>
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">Shared Note (Optional)</label>
              <textarea v-model="action.note" rows="4" placeholder="Apply one moderation note to all selected requests..." class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>

            <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Preview</p>
              <div class="mt-3 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p class="text-slate-500">Actionable</p>
                  <p class="text-xl font-semibold text-emerald-700">{{ previewSummary.actionable }}</p>
                </div>
                <div>
                  <p class="text-slate-500">Selected</p>
                  <p class="text-xl font-semibold text-slate-900">{{ selectedCount }}</p>
                </div>
              </div>
            </div>

            <button type="button" class="w-full rounded-xl bg-cyan-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60" :disabled="!canLaunchAction || launching" @click="launchAction">
              {{ launching ? 'Queueing...' : 'Queue Moderation Batch' }}
            </button>
          </div>
        </section>

        <ReviewTaskPanels
          :history-loading="historyLoading"
          :history-items="historyItems"
          :task-state="taskState"
          :task-progress="taskProgress"
          :task-results="taskResults"
          @refresh-history="loadHistory"
          @restore-task="restoreTask"
          @download-results="downloadResults"
        />
      </aside>
    </section>

    <section v-else class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div class="space-y-6">
        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Sweep Plan</h3>
              <p class="mt-1 text-xs text-slate-500">Sweep Mode uses Zenodo server-side submitted status and repeated page 1 processing.</p>
            </div>
            <button type="button" class="rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60" :disabled="planningSweep" @click="planSweep">
              {{ planningSweep ? 'Planning...' : 'Plan Sweep' }}
            </button>
          </div>

          <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <select v-model="filters.institution_id" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" @change="handleInstitutionChange">
              <option value="">No institution context</option>
              <option v-for="institution in institutionOptions" :key="institution.id" :value="String(institution.id)">
                {{ institution.name }}
              </option>
            </select>
            <input :value="filters.community_identifier" type="text" placeholder="Community identifier" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" @input="handleCommunityIdentifierInput($event.target.value)" />
            <select v-model="sweepForm.action" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
              <option value="accept">Accept submitted requests</option>
              <option value="decline">Decline submitted requests</option>
            </select>
            <input v-model="sweepForm.request_type" type="text" placeholder="Request type filter (optional)" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <input v-model.number="sweepForm.page_size" type="number" min="1" max="100" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <input v-model.number="sweepForm.max_requests" type="number" min="1" placeholder="Max requests (optional)" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>

          <textarea v-model="sweepForm.note" rows="3" placeholder="Optional moderation note for every request in the sweep" class="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />

          <Alert v-if="sweepError" v-model="showSweepError" class="mt-4" variant="error" :message="sweepError" :dismissible="false" />

          <div v-if="sweepPlan" class="mt-5 space-y-4">
            <div class="grid gap-3 sm:grid-cols-4">
              <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Submitted</p>
                <p class="mt-1 text-2xl font-semibold text-slate-900">{{ sweepPlan.summary?.total_matching || 0 }}</p>
              </div>
              <div class="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Planned</p>
                <p class="mt-1 text-2xl font-semibold text-emerald-800">{{ sweepPlan.summary?.planned_requests || 0 }}</p>
              </div>
              <div class="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Preview OK</p>
                <p class="mt-1 text-2xl font-semibold text-amber-800">{{ sweepPlan.summary?.preview_actionable_count || 0 }}</p>
              </div>
              <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">API Key</p>
                <p class="mt-1 text-sm font-semibold text-slate-900">{{ sweepPlan.api_key_context?.configured ? 'Configured' : 'Missing' }}</p>
              </div>
            </div>

            <div class="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p class="text-xs font-semibold uppercase tracking-wide text-amber-800">Required Confirmation</p>
              <p class="mt-2 break-words font-mono text-sm text-amber-950">{{ sweepPlan.confirmation_text }}</p>
              <input v-model="sweepConfirmation" type="text" placeholder="Type the confirmation phrase exactly" class="mt-3 w-full rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm" />
              <button type="button" class="mt-3 w-full rounded-xl bg-rose-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60" :disabled="!canLaunchSweep || launchingSweep" @click="launchSweep">
                {{ launchingSweep ? 'Queueing...' : 'Queue Sweep' }}
              </button>
            </div>

            <section class="space-y-3">
              <h3 class="text-sm font-semibold text-slate-900">Preview</h3>
              <article v-for="item in sweepPlan.preview || []" :key="item.request_id" class="rounded-xl border border-slate-200 bg-white p-4">
                <div class="flex flex-wrap items-center gap-2">
                  <p class="text-sm font-semibold text-slate-900">{{ item.title || 'Untitled request' }}</p>
                  <span class="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-cyan-700">{{ item.type || 'unknown' }}</span>
                  <span class="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-600">{{ item.status || 'unknown' }}</span>
                </div>
                <p class="mt-1 text-xs text-slate-500">Request {{ item.number || 'N/A' }} - {{ item.request_id }} - Topic {{ item.topic_record || 'N/A' }}</p>
              </article>
            </section>
          </div>
        </section>
      </div>

      <aside class="space-y-6 xl:sticky xl:top-24 xl:self-start">
        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <h3 class="text-sm font-semibold text-slate-900">Recent Sweeps</h3>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="loadSweeps">
              Refresh
            </button>
          </div>
          <div v-if="sweepsLoading" class="mt-4 text-sm text-slate-500">Loading recent sweeps...</div>
          <div v-else-if="sweepJobs.length === 0" class="mt-4 text-sm text-slate-500">No sweeps recorded yet.</div>
          <div v-else class="mt-4 space-y-3">
            <article v-for="job in sweepJobs" :key="job.job_id" class="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-semibold text-slate-900">{{ sweepTitle(job) }}</p>
                <span class="rounded-full border border-slate-300 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-700">{{ job.state }}</span>
              </div>
              <p class="mt-1 text-xs text-slate-500">{{ job.updated_at ? formatDate(job.updated_at) : 'Unknown update time' }}</p>
              <p class="mt-2 text-xs text-slate-600">
                {{ job.summary?.processed || 0 }} / {{ job.progress?.total_requests || job.summary?.planned_requests || 0 }} processed -
                {{ job.summary?.accepted || 0 }} accepted -
                {{ job.summary?.declined || 0 }} declined -
                {{ job.summary?.failed || 0 }} failed
              </p>
              <button type="button" class="mt-3 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-white" @click="restoreSweep(job)">
                Open
              </button>
            </article>
          </div>
        </section>

        <section v-if="sweepJob" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <h3 class="text-sm font-semibold text-slate-900">Sweep Progress</h3>
            <span class="rounded-full border border-slate-300 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700">{{ sweepJob.state }}</span>
          </div>
          <p class="mt-2 text-sm text-slate-600">{{ sweepJob.phase || 'Waiting for updates' }}</p>
          <div class="mt-4 h-2.5 overflow-hidden rounded-full bg-slate-100">
            <div class="h-full rounded-full bg-cyan-600 transition-all duration-300" :style="{ width: `${sweepProgress.percent || 0}%` }"></div>
          </div>
          <div class="mt-4 grid grid-cols-2 gap-3 text-sm">
            <div><p class="text-slate-500">Processed</p><p class="font-semibold text-slate-900">{{ sweepProgress.processed || 0 }} / {{ sweepProgress.total_requests || 0 }}</p></div>
            <div><p class="text-slate-500">Remaining</p><p class="font-semibold text-slate-900">{{ sweepProgress.submitted_remaining ?? 0 }}</p></div>
            <div><p class="text-slate-500">Accepted</p><p class="font-semibold text-emerald-700">{{ sweepProgress.accepted || 0 }}</p></div>
            <div><p class="text-slate-500">Declined</p><p class="font-semibold text-amber-700">{{ sweepProgress.declined || 0 }}</p></div>
            <div><p class="text-slate-500">Failed</p><p class="font-semibold text-rose-700">{{ sweepProgress.failed || 0 }}</p></div>
            <div><p class="text-slate-500">Rate waits</p><p class="font-semibold text-amber-700">{{ sweepProgress.rate_limit_waits || 0 }}</p></div>
          </div>
          <div class="mt-4 flex flex-wrap gap-2">
            <button type="button" class="rounded-lg border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50" :disabled="!canCancelSweep" @click="cancelSweep">
              Cancel
            </button>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="downloadSweepJson">
              Export JSON
            </button>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="downloadSweepCsv">
              Export CSV
            </button>
          </div>
        </section>

        <section v-if="sweepEvents.length" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 class="text-sm font-semibold text-slate-900">Latest Events</h3>
          <div class="mt-4 max-h-[420px] space-y-3 overflow-auto">
            <article v-for="event in sweepEvents.slice().reverse()" :key="event.id || `${event.request_id}-${event.created_at}`" class="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-semibold text-slate-900">{{ event.title || event.request_id || event.event }}</p>
                <span :class="resultStatusClass(event.status || event.event)" class="rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide">{{ event.event }}</span>
              </div>
              <p class="mt-1 text-xs text-slate-500">{{ event.request_id || 'system' }} - {{ event.request_type || 'n/a' }}</p>
              <p class="mt-2 text-xs text-slate-600">{{ event.message || 'No message returned.' }}</p>
            </article>
          </div>
        </section>
      </aside>
    </section>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref } from 'vue'
import Alert from '@/components/ui/Alert.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import { useToast } from '@/composables/useToast'
import institutionService from '@/services/institution.service'
import toolsService from '@/services/tools.service'

const ReviewTaskPanels = defineComponent({
  props: {
    historyLoading: Boolean,
    historyItems: { type: Array, default: () => [] },
    taskState: { type: Object, default: null },
    taskProgress: { type: Object, default: () => ({}) },
    taskResults: { type: Array, default: () => [] },
  },
  emits: ['refresh-history', 'restore-task', 'download-results'],
  setup(props, { emit }) {
    const format = (value) => {
      if (!value) return 'N/A'
      const parsed = new Date(value)
      return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString()
    }
    const statusClass = (status) => {
      if (status === 'accepted') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
      if (status === 'declined') return 'border-amber-200 bg-amber-50 text-amber-700'
      return 'border-rose-200 bg-rose-50 text-rose-700'
    }
    const title = (item) => `${item.action === 'decline' ? 'Decline' : 'Accept'} - ${item.community_identifier || 'community'}`

    return () => h('div', { class: 'space-y-6' }, [
      h('section', { class: 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm' }, [
        h('div', { class: 'flex items-center justify-between gap-3' }, [
          h('h3', { class: 'text-sm font-semibold text-slate-900' }, 'Recent Review Runs'),
          h('button', { type: 'button', class: 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50', onClick: () => emit('refresh-history') }, 'Refresh'),
        ]),
        props.historyLoading
          ? h('div', { class: 'mt-4 text-sm text-slate-500' }, 'Loading recent moderation runs...')
          : props.historyItems.length === 0
            ? h('div', { class: 'mt-4 text-sm text-slate-500' }, 'No moderation runs recorded yet.')
            : h('div', { class: 'mt-4 space-y-3' }, props.historyItems.map((item) => h('article', { key: item.task_id, class: 'rounded-xl border border-slate-200 bg-slate-50 p-3' }, [
              h('div', { class: 'flex items-center justify-between gap-2' }, [
                h('p', { class: 'text-sm font-semibold text-slate-900' }, title(item)),
                h('span', { class: 'rounded-full border border-slate-300 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-700' }, item.state),
              ]),
              h('p', { class: 'mt-1 text-xs text-slate-500' }, format(item.created_at)),
              h('p', { class: 'mt-2 text-xs text-slate-600' }, `${item.summary?.processed || 0} / ${item.summary?.total_requests || item.selected_count || 0} processed - ${item.summary?.accepted || 0} accepted - ${item.summary?.declined || 0} declined - ${item.summary?.failed || 0} failed`),
              h('button', { type: 'button', class: 'mt-3 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-white', onClick: () => emit('restore-task', item) }, 'Open'),
            ]))),
      ]),
      props.taskState && h('section', { class: 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm' }, [
        h('div', { class: 'flex items-center justify-between gap-3' }, [
          h('h3', { class: 'text-sm font-semibold text-slate-900' }, 'Task Progress'),
          h('span', { class: 'rounded-full border border-slate-300 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700' }, props.taskState.state),
        ]),
        h('p', { class: 'mt-2 text-sm text-slate-600' }, props.taskState.status || 'Waiting for updates'),
        h('div', { class: 'mt-4 h-2.5 overflow-hidden rounded-full bg-slate-100' }, [
          h('div', { class: 'h-full rounded-full bg-cyan-600 transition-all duration-300', style: { width: `${props.taskProgress.percent || 0}%` } }),
        ]),
        h('div', { class: 'mt-4 grid grid-cols-2 gap-3 text-sm' }, [
          h('div', [h('p', { class: 'text-slate-500' }, 'Processed'), h('p', { class: 'font-semibold text-slate-900' }, `${props.taskProgress.processed || 0} / ${props.taskProgress.total_requests || 0}`)]),
          h('div', [h('p', { class: 'text-slate-500' }, 'Accepted'), h('p', { class: 'font-semibold text-emerald-700' }, props.taskProgress.accepted || 0)]),
          h('div', [h('p', { class: 'text-slate-500' }, 'Declined'), h('p', { class: 'font-semibold text-amber-700' }, props.taskProgress.declined || 0)]),
          h('div', [h('p', { class: 'text-slate-500' }, 'Failed'), h('p', { class: 'font-semibold text-rose-700' }, props.taskProgress.failed || 0)]),
        ]),
      ]),
      props.taskResults.length > 0 && h('section', { class: 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm' }, [
        h('div', { class: 'flex items-center justify-between gap-3' }, [
          h('h3', { class: 'text-sm font-semibold text-slate-900' }, 'Latest Results'),
          h('button', { type: 'button', class: 'rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50', onClick: () => emit('download-results') }, 'Export JSON'),
        ]),
        h('div', { class: 'mt-4 max-h-[420px] space-y-3 overflow-auto' }, props.taskResults.slice().reverse().map((result) => h('article', { key: `${result.request_id}-${result.status}`, class: 'rounded-xl border border-slate-200 bg-slate-50 p-3' }, [
          h('div', { class: 'flex items-center justify-between gap-2' }, [
            h('p', { class: 'text-sm font-semibold text-slate-900' }, result.title || 'Untitled request'),
            h('span', { class: `rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${statusClass(result.status)}` }, result.status),
          ]),
          h('p', { class: 'mt-1 text-xs text-slate-500' }, `${result.request_id} - ${result.type || 'unknown'}`),
          h('p', { class: 'mt-2 text-xs text-slate-600' }, result.message || 'No message returned.'),
        ]))),
      ]),
    ])
  },
})

const toast = useToast()
const activeMode = ref('review')
const loading = ref(true)
const launching = ref(false)
const payload = ref(null)
const error = ref('')
const institutionsLoading = ref(false)
const institutions = ref([])
const historyLoading = ref(false)
const historyItems = ref([])
const taskId = ref('')
const taskState = ref(null)
const pollHandle = ref(null)
const sweepPollHandle = ref(null)
const selection = ref(new Set())
const requestCatalog = ref(new Map())
const manualCommunityOverride = ref(false)

const planningSweep = ref(false)
const launchingSweep = ref(false)
const sweepsLoading = ref(false)
const sweepError = ref('')
const sweepPlan = ref(null)
const sweepConfirmation = ref('')
const sweepJob = ref(null)
const sweepJobs = ref([])

const filters = ref({
  institution_id: '',
  community_identifier: '',
  q: '',
  request_type: '',
  created_from: '',
  created_to: '',
  updated_from: '',
  updated_to: '',
  page: 1,
  per_page: 25,
})

const action = ref({
  action: 'accept',
  note: '',
})

const sweepForm = ref({
  action: 'accept',
  request_type: '',
  status_filter: 'submitted',
  note: '',
  page_size: 100,
  max_requests: '',
})

const showError = computed(() => !!error.value)
const showSweepError = computed(() => !!sweepError.value)
const summary = computed(() => payload.value?.summary || {})
const pagination = computed(() => payload.value?.pagination || { page: 1, total_pages: 1 })
const requests = computed(() => payload.value?.requests || [])
const allFilteredRequestIds = computed(() => payload.value?.all_filtered_request_ids || [])
const allFilteredRequestsPreview = computed(() => payload.value?.all_filtered_requests_preview || [])
const requestTypes = computed(() => payload.value?.summary?.request_types || [])
const moderationContext = computed(() => payload.value?.moderation_context || {})
const institutionOptions = computed(() => institutions.value || [])
const selectedCount = computed(() => selection.value.size)
const resolvedCommunity = computed(() => payload.value?.community || sweepPlan.value?.community || {})
const selectedInstitutionLabel = computed(() => moderationContext.value?.institution?.name || '')
const resolutionSourceLabel = computed(() => {
  const source = String(moderationContext.value?.resolution_source || '').trim()
  if (!source) return ''
  if (source === 'institution_moderation_default') return 'Institution default'
  if (source === 'institution_primary_submission') return 'Primary fallback'
  if (source === 'global_override') return 'Global fallback'
  if (source === 'explicit') return 'Manual override'
  return source
})
const resolvedCommunityLabel = computed(() => {
  const resolvedIdentifier = moderationContext.value?.community_identifier || ''
  const title = resolvedCommunity.value?.title || ''
  const slug = resolvedCommunity.value?.slug || resolvedIdentifier || filters.value.community_identifier || ''
  return [title, slug && title !== slug ? `(${slug})` : ''].filter(Boolean).join(' ') || 'Unknown'
})
const selectedRequests = computed(() => {
  const results = []
  for (const id of selection.value) {
    const item = requestCatalog.value.get(id)
    if (item) results.push(item)
  }
  return results
})
const filteredRequestIdSet = computed(() => new Set(allFilteredRequestIds.value))
const selectedVisibleCount = computed(() => {
  let count = 0
  for (const id of selection.value) {
    if (filteredRequestIdSet.value.has(id)) count += 1
  }
  return count
})
const selectedOutsideCurrentFiltersCount = computed(() => Math.max(0, selectedCount.value - selectedVisibleCount.value))
const previewSummary = computed(() => ({
  actionable: selectedRequests.value.filter((item) => item?.is_actionable).length,
}))
const taskProgress = computed(() => taskState.value?.progress || taskState.value?.result?.progress || {})
const taskResults = computed(() => taskState.value?.result?.results || [])
const canLaunchAction = computed(() => selectedCount.value > 0 && previewSummary.value.actionable > 0)
const canLaunchSweep = computed(() => (
  !!sweepPlan.value
  && Number(sweepPlan.value?.summary?.planned_requests || 0) > 0
  && sweepConfirmation.value === sweepPlan.value.confirmation_text
))
const sweepProgress = computed(() => sweepJob.value?.progress || {})
const sweepEvents = computed(() => sweepJob.value?.events || [])
const canCancelSweep = computed(() => sweepJob.value && !['SUCCESS', 'FAILURE', 'CANCELLED'].includes(String(sweepJob.value.state || '').toUpperCase()))

const indexRequests = (items = []) => {
  const next = new Map(requestCatalog.value)
  for (const item of items) {
    if (!item?.request_id) continue
    next.set(item.request_id, item)
  }
  requestCatalog.value = next
}

const isSelected = (item) => selection.value.has(item.request_id)

const toggleRequest = (item) => {
  indexRequests([item])
  const next = new Set(selection.value)
  if (next.has(item.request_id)) next.delete(item.request_id)
  else next.add(item.request_id)
  selection.value = next
}

const selectCurrentPage = () => {
  indexRequests(requests.value)
  selection.value = new Set([...selection.value, ...requests.value.map((item) => item.request_id)])
}

const selectAllFiltered = () => {
  indexRequests(allFilteredRequestsPreview.value)
  selection.value = new Set(allFilteredRequestIds.value)
}

const clearSelection = () => {
  selection.value = new Set()
  requestCatalog.value = new Map()
}

const formatDate = (value) => {
  if (!value) return 'N/A'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString()
}

const resultStatusClass = (status) => {
  if (['accepted', 'accept', 'declined', 'decline'].includes(status)) {
    return status === 'declined' || status === 'decline'
      ? 'border-amber-200 bg-amber-50 text-amber-700'
      : 'border-emerald-200 bg-emerald-50 text-emerald-700'
  }
  if (status === 'waited' || status === 'rate_limit_wait') return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-rose-200 bg-rose-50 text-rose-700'
}

const normalizedParams = () => ({
  institution_id: filters.value.institution_id || undefined,
  community_identifier: filters.value.community_identifier || undefined,
  q: filters.value.q || undefined,
  request_type: filters.value.request_type || undefined,
  created_from: filters.value.created_from ? new Date(filters.value.created_from).toISOString() : undefined,
  created_to: filters.value.created_to ? new Date(filters.value.created_to).toISOString() : undefined,
  updated_from: filters.value.updated_from ? new Date(filters.value.updated_from).toISOString() : undefined,
  updated_to: filters.value.updated_to ? new Date(filters.value.updated_to).toISOString() : undefined,
  page: filters.value.page,
  per_page: filters.value.per_page,
})

const sweepPayload = () => ({
  institution_id: filters.value.institution_id || undefined,
  community_identifier: filters.value.community_identifier || undefined,
  action: sweepForm.value.action,
  status_filter: 'submitted',
  request_type: sweepForm.value.request_type || undefined,
  note: sweepForm.value.note || undefined,
  page_size: sweepForm.value.page_size || 100,
  max_requests: sweepForm.value.max_requests || undefined,
})

const applyResolvedCommunityIdentifier = (responseData) => {
  const resolvedIdentifier = responseData?.moderation_context?.community_identifier || responseData?.community?.slug || ''
  if (!resolvedIdentifier) return
  if (!manualCommunityOverride.value || !filters.value.community_identifier) {
    filters.value.community_identifier = resolvedIdentifier
  }
}

const loadInstitutions = async () => {
  institutionsLoading.value = true
  try {
    const response = await institutionService.listInstitutions({ all: true })
    institutions.value = response.data?.institutions || []
  } catch (err) {
    console.error('Failed to load moderation institutions', err)
  } finally {
    institutionsLoading.value = false
  }
}

const loadRequests = async () => {
  loading.value = true
  error.value = ''
  try {
    const response = await toolsService.getCommunityModerationRequests(normalizedParams())
    payload.value = response.data
    indexRequests([...(response.data?.requests || []), ...(response.data?.all_filtered_requests_preview || [])])
    applyResolvedCommunityIdentifier(response.data)
  } catch (err) {
    console.error('Failed to load community moderation queue', err)
    error.value = err.error?.message || err.message || 'Failed to load community moderation queue.'
  } finally {
    loading.value = false
  }
}

const loadHistory = async () => {
  historyLoading.value = true
  try {
    const response = await toolsService.getCommunityModerationHistory({ limit: 12 })
    historyItems.value = response.data?.tasks || []
  } catch (err) {
    console.error('Failed to load community moderation history', err)
  } finally {
    historyLoading.value = false
  }
}

const loadSweeps = async () => {
  sweepsLoading.value = true
  try {
    const response = await toolsService.listCommunityModerationSweeps({ limit: 12 })
    sweepJobs.value = response.data?.jobs || []
  } catch (err) {
    console.error('Failed to load community moderation sweeps', err)
  } finally {
    sweepsLoading.value = false
  }
}

const applyFilters = async () => {
  filters.value.page = 1
  await loadRequests()
}

const resetFilters = async () => {
  manualCommunityOverride.value = false
  filters.value = {
    institution_id: moderationContext.value?.institution_id ? String(moderationContext.value.institution_id) : '',
    community_identifier: moderationContext.value?.community_identifier || resolvedCommunity.value?.slug || '',
    q: '',
    request_type: '',
    created_from: '',
    created_to: '',
    updated_from: '',
    updated_to: '',
    page: 1,
    per_page: 25,
  }
  await loadRequests()
}

const changePage = async (page) => {
  filters.value.page = page
  await loadRequests()
}

const stopPolling = () => {
  if (pollHandle.value) {
    clearInterval(pollHandle.value)
    pollHandle.value = null
  }
}

const stopSweepPolling = () => {
  if (sweepPollHandle.value) {
    clearInterval(sweepPollHandle.value)
    sweepPollHandle.value = null
  }
}

const reconcileTaskResultsIntoCatalog = (results = []) => {
  const next = new Map(requestCatalog.value)
  for (const result of results) {
    if (!result?.request_id) continue
    const existing = next.get(result.request_id)
    if (!existing) continue
    next.set(result.request_id, {
      ...existing,
      status: result.updated_request?.status || existing.status,
      updated: result.updated_request?.updated || existing.updated,
      is_open: false,
      is_actionable: false,
    })
  }
  requestCatalog.value = next
}

const pollTask = async () => {
  if (!taskId.value) return
  try {
    const response = await toolsService.getCommunityModerationTask(taskId.value)
    taskState.value = response.data
    reconcileTaskResultsIntoCatalog(response.data?.result?.results || [])
    if (['SUCCESS', 'FAILURE'].includes(response.data?.state)) {
      stopPolling()
      await loadHistory()
      if (response.data?.state === 'SUCCESS') await loadRequests()
    }
  } catch (err) {
    console.error('Failed to poll community moderation task', err)
  }
}

const pollSweep = async () => {
  if (!sweepJob.value?.job_id) return
  try {
    const response = await toolsService.getCommunityModerationSweep(sweepJob.value.job_id, { event_limit: 50 })
    sweepJob.value = response.data
    if (['SUCCESS', 'FAILURE', 'CANCELLED'].includes(String(response.data?.state || '').toUpperCase())) {
      stopSweepPolling()
      await loadSweeps()
      await loadRequests()
    }
  } catch (err) {
    console.error('Failed to poll community moderation sweep', err)
  }
}

const launchAction = async () => {
  launching.value = true
  try {
    const response = await toolsService.launchCommunityModerationBatch({
      action: action.value.action,
      institution_id: filters.value.institution_id || undefined,
      community_identifier: filters.value.community_identifier,
      note: action.value.note || undefined,
      request_ids: Array.from(selection.value),
    })
    taskId.value = response.data?.task_id || ''
    taskState.value = {
      state: 'PENDING',
      status: 'Queued community moderation batch',
      progress: { total_requests: selectedCount.value, processed: 0, percent: 0 },
      result: null,
    }
    toast.success('Community moderation batch queued')
    await loadHistory()
    stopPolling()
    await pollTask()
    pollHandle.value = setInterval(pollTask, 2500)
  } catch (err) {
    console.error('Failed to queue community moderation batch', err)
    toast.error(err.error?.message || err.message || 'Failed to queue community moderation batch')
  } finally {
    launching.value = false
  }
}

const planSweep = async () => {
  planningSweep.value = true
  sweepError.value = ''
  sweepPlan.value = null
  sweepConfirmation.value = ''
  try {
    const response = await toolsService.planCommunityModerationSweep(sweepPayload())
    sweepPlan.value = response.data
    applyResolvedCommunityIdentifier(response.data)
    toast.success('Community moderation sweep plan built')
  } catch (err) {
    console.error('Failed to plan community moderation sweep', err)
    sweepError.value = err.error?.message || err.message || 'Failed to plan community moderation sweep'
  } finally {
    planningSweep.value = false
  }
}

const launchSweep = async () => {
  launchingSweep.value = true
  sweepError.value = ''
  try {
    const response = await toolsService.launchCommunityModerationSweep({
      ...sweepPayload(),
      plan_checksum: sweepPlan.value?.plan_checksum,
      confirmation_text: sweepConfirmation.value,
    })
    sweepJob.value = response.data
    toast.success('Community moderation sweep queued')
    await loadSweeps()
    stopSweepPolling()
    await pollSweep()
    sweepPollHandle.value = setInterval(pollSweep, 2500)
  } catch (err) {
    console.error('Failed to queue community moderation sweep', err)
    sweepError.value = err.error?.message || err.message || 'Failed to queue community moderation sweep'
    toast.error(sweepError.value)
  } finally {
    launchingSweep.value = false
  }
}

const cancelSweep = async () => {
  if (!sweepJob.value?.job_id) return
  try {
    const response = await toolsService.cancelCommunityModerationSweep(sweepJob.value.job_id)
    sweepJob.value = response.data
    toast.success('Community moderation sweep cancellation requested')
    await loadSweeps()
  } catch (err) {
    toast.error(err.error?.message || err.message || 'Failed to cancel community moderation sweep')
  }
}

const handleCommunityIdentifierInput = (value) => {
  manualCommunityOverride.value = true
  filters.value.community_identifier = value
  sweepPlan.value = null
  sweepConfirmation.value = ''
}

const selectModerationCandidate = (candidate) => {
  manualCommunityOverride.value = true
  filters.value.community_identifier = candidate
  sweepPlan.value = null
  sweepConfirmation.value = ''
}

const handleInstitutionChange = async () => {
  manualCommunityOverride.value = false
  filters.value.page = 1
  sweepPlan.value = null
  sweepConfirmation.value = ''
  await loadRequests()
}

const downloadBlob = (content, filename, type) => {
  const blob = content instanceof Blob ? content : new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const downloadResults = () => {
  downloadBlob(JSON.stringify(taskState.value?.result || {}, null, 2), `community_moderation_${taskId.value || 'results'}.json`, 'application/json')
}

const downloadSweepJson = async () => {
  if (!sweepJob.value?.job_id) return
  const response = await toolsService.exportCommunityModerationSweep(sweepJob.value.job_id, 'json')
  downloadBlob(JSON.stringify(response.data || response, null, 2), `community_moderation_sweep_${sweepJob.value.job_id}.json`, 'application/json')
}

const downloadSweepCsv = async () => {
  if (!sweepJob.value?.job_id) return
  const response = await toolsService.exportCommunityModerationSweep(sweepJob.value.job_id, 'csv')
  downloadBlob(response, `community_moderation_sweep_${sweepJob.value.job_id}.csv`, 'text/csv')
}

const restoreTask = async (item) => {
  taskId.value = item?.task_id || ''
  taskState.value = {
    state: item?.state || 'PENDING',
    status: item?.status || 'Pending...',
    progress: item?.progress || null,
    result: item?.result || null,
    error: item?.error || null,
  }
  if (!taskId.value) return
  stopPolling()
  if (!['SUCCESS', 'FAILURE'].includes(taskState.value.state)) {
    await pollTask()
    pollHandle.value = setInterval(pollTask, 2500)
  }
}

const restoreSweep = async (job) => {
  sweepJob.value = job
  stopSweepPolling()
  await pollSweep()
  if (canCancelSweep.value) {
    sweepPollHandle.value = setInterval(pollSweep, 2500)
  }
}

const sweepTitle = (job) => `${job.action === 'decline' ? 'Decline' : 'Accept'} - ${job.community_identifier || 'community'}`

onMounted(async () => {
  await Promise.all([loadInstitutions(), loadRequests(), loadHistory(), loadSweeps()])
})

onBeforeUnmount(() => {
  stopPolling()
  stopSweepPolling()
})
</script>
