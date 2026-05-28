<template>
  <div class="space-y-6">
    <section class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">Zenodo Metadata Batch Operations</p>
          <h2 class="mt-2 text-2xl font-semibold text-slate-900">Community membership operations across sessions</h2>
          <p class="mt-2 max-w-3xl text-sm text-slate-600">
            Select records grouped by session, filter the cross-session set, then queue a serial Zenodo-safe batch run.
          </p>
        </div>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Sessions</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">{{ summary.sessions_with_matches || 0 }}</p>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Filtered</p>
            <p class="mt-1 text-2xl font-semibold text-slate-900">{{ summary.records_filtered || 0 }}</p>
          </div>
          <div class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Selected</p>
            <p class="mt-1 text-2xl font-semibold text-emerald-800">{{ selectedCount }}</p>
          </div>
          <div class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Warnings</p>
            <p class="mt-1 text-2xl font-semibold text-amber-800">{{ sessionWarnings.length }}</p>
          </div>
        </div>
      </div>
    </section>

    <section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div class="space-y-6">
        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Filters</h3>
              <p class="mt-1 text-xs text-slate-500">Creators, communities, dates, owners, and record status.</p>
            </div>
            <div class="flex gap-2">
              <button
                type="button"
                class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                @click="resetFilters"
                :disabled="loading"
              >
                Reset
              </button>
              <button
                type="button"
                class="rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60"
                @click="applyFilters"
                :disabled="loading"
              >
                Apply Filters
              </button>
            </div>
          </div>

          <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <input v-model="filters.q" type="text" placeholder="Search title, DOI, IDs, owner" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <input v-model.number="filters.session_id" type="number" min="1" placeholder="Session ID" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <input v-model.number="filters.owner_user_id" type="number" min="1" placeholder="Owner User ID" class="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <select v-model="filters.record_status" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
              <option value="all">All statuses</option>
              <option value="draft">Draft</option>
              <option value="published">Published</option>
              <option value="other">Other</option>
            </select>
            <select v-model="filters.is_sandbox" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
              <option value="">All environments</option>
              <option value="true">Sandbox</option>
              <option value="false">Production</option>
            </select>
            <input v-model="filters.creator" type="text" placeholder="Creator contains..." class="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <input v-model="filters.community" type="text" placeholder="Community contains..." class="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <select v-model.number="filters.per_page" class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
              <option :value="5">5 sessions / page</option>
              <option :value="10">10 sessions / page</option>
              <option :value="20">20 sessions / page</option>
            </select>
            <label class="text-xs font-medium uppercase tracking-wide text-slate-500">
              Publication Date From
              <input v-model="filters.publication_date_from" type="date" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
            </label>
            <label class="text-xs font-medium uppercase tracking-wide text-slate-500">
              Publication Date To
              <input v-model="filters.publication_date_to" type="date" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case tracking-normal text-slate-900" />
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
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Selection</h3>
              <p class="mt-1 text-xs text-slate-500">Use current page, full filtered results, or per-session toggles.</p>
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
            <span>{{ allFilteredRecordRefs.length }} filtered refs available</span>
            <span>{{ pagination.total_groups || 0 }} session groups</span>
          </div>
        </section>

        <LoadingSpinner v-if="loading" size="lg" text="Loading Zenodo batch record groups..." />

        <section v-else-if="error" class="rounded-2xl border border-rose-200 bg-white p-6 shadow-sm">
          <Alert v-model="showError" variant="error" :message="error" :dismissible="false" />
        </section>

        <section v-else class="space-y-5">
          <div v-if="sessionWarnings.length" class="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <p class="font-semibold">Session warnings</p>
            <ul class="mt-2 space-y-1 text-xs">
              <li v-for="warning in sessionWarnings.slice(0, 8)" :key="`${warning.session_id}-${warning.reason}`">
                Session {{ warning.session_id }}: {{ warning.reason }}
              </li>
            </ul>
          </div>

          <div v-if="groups.length === 0" class="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500 shadow-sm">
            No records match the current filters.
          </div>

          <article
            v-for="group in groups"
            :key="group.session.id"
            class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
          >
            <header class="border-b border-slate-100 bg-slate-50 px-5 py-4">
              <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <div class="flex flex-wrap items-center gap-2">
                    <h3 class="text-lg font-semibold text-slate-900">Session #{{ group.session.id }}</h3>
                    <span class="rounded-full border border-slate-300 bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
                      {{ group.session.status || 'unknown' }}
                    </span>
                    <span class="rounded-full border border-cyan-200 bg-cyan-50 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-cyan-700">
                      {{ group.summary.records_returned }} records
                    </span>
                  </div>
                  <p class="mt-2 text-sm text-slate-600">
                    {{ group.session.owner_email || `User #${group.session.owner_user_id}` }}
                    <span v-if="group.session.created_at"> · created {{ formatDate(group.session.created_at) }}</span>
                  </p>
                </div>
                <div class="flex flex-wrap gap-2">
                  <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-white" @click="selectSession(group, true)">
                    Select Session
                  </button>
                  <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-white" @click="selectSession(group, false)">
                    Clear Session
                  </button>
                </div>
              </div>
            </header>

            <div class="divide-y divide-slate-100">
              <div
                v-for="record in group.records"
                :key="recordKey(record)"
                class="grid gap-4 px-5 py-4 lg:grid-cols-[auto_minmax(0,1.2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_auto]"
              >
                <div class="pt-1">
                  <input
                    :checked="isSelected(record)"
                    type="checkbox"
                    class="h-4 w-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                    @change="toggleRecord(record)"
                  />
                </div>

                <div class="min-w-0">
                  <div class="flex flex-wrap items-center gap-2">
                    <p class="text-sm font-semibold text-slate-900">{{ record.record_title || 'Untitled record' }}</p>
                    <span :class="statusClass(record.record_status)" class="rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide">
                      {{ record.record_status || 'unknown' }}
                    </span>
                    <span
                      :class="record.is_sandbox ? 'border-amber-200 bg-amber-50 text-amber-700' : 'border-sky-200 bg-sky-50 text-sky-700'"
                      class="rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
                    >
                      {{ record.is_sandbox ? 'Sandbox' : 'Production' }}
                    </span>
                  </div>
                  <p class="mt-1 text-xs text-slate-500">
                    Local {{ record.local_record_id }} · Zenodo {{ record.zenodo_record_id || 'N/A' }} · {{ record.zenodo_doi || 'No DOI' }}
                  </p>
                  <div class="mt-2 flex flex-wrap gap-1.5">
                    <span
                      v-for="community in record.communities_normalized"
                      :key="`${recordKey(record)}-${community}`"
                      class="rounded-full border border-cyan-200 bg-cyan-50 px-2 py-1 text-[11px] font-medium text-cyan-800"
                    >
                      {{ community }}
                    </span>
                    <span v-if="!record.communities_normalized?.length" class="rounded-full border border-slate-200 bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-500">
                      No communities
                    </span>
                  </div>
                </div>

                <div class="min-w-0">
                  <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Creators</p>
                  <p class="mt-1 text-sm text-slate-700">
                    {{ record.creators_normalized?.join(', ') || 'No creators' }}
                  </p>
                  <p class="mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Publication / Updated</p>
                  <p class="mt-1 text-sm text-slate-700">
                    {{ record.publication_date || 'No publication date' }}
                  </p>
                  <p class="text-xs text-slate-500">{{ formatDate(record.updated_at) }}</p>
                </div>

                <div class="min-w-0">
                  <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Current Operation Eligibility</p>
                  <div class="mt-2">
                    <span
                      :class="currentEligibility(record)?.eligible ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-rose-200 bg-rose-50 text-rose-700'"
                      class="inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide"
                    >
                      {{ currentEligibility(record)?.eligible ? 'Eligible' : 'Ineligible' }}
                    </span>
                    <p class="mt-2 text-xs text-slate-600">{{ currentEligibility(record)?.reason || currentNoopReason(record) }}</p>
                  </div>
                </div>

                <div class="flex items-start justify-end">
                  <a
                    v-if="record.record_link"
                    :href="record.record_link"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Open Zenodo
                  </a>
                </div>
              </div>
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
          <h3 class="text-sm font-semibold text-slate-900">Operation</h3>
          <div class="mt-4 space-y-4">
            <div>
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">Type</label>
              <select v-model="operation.operation" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
                <option value="append_if_missing">Append if missing</option>
                <option value="remove_communities">Remove communities</option>
              </select>
            </div>

            <div v-if="operation.operation === 'remove_communities'">
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">Remove Mode</label>
              <select v-model="operation.remove_mode" class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
                <option value="one">Remove one community</option>
                <option value="all">Remove all communities</option>
              </select>
            </div>

            <div v-if="requiresCommunityIdentifier">
              <label class="text-xs font-semibold uppercase tracking-wide text-slate-500">Community Identifier</label>
              <input v-model="operation.community_identifier" type="text" placeholder="e.g. 3d-big-data-space" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            </div>

            <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Preview</p>
              <div class="mt-3 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p class="text-slate-500">Actionable</p>
                  <p class="text-xl font-semibold text-emerald-700">{{ previewSummary.actionable }}</p>
                </div>
                <div>
                  <p class="text-slate-500">No-op</p>
                  <p class="text-xl font-semibold text-slate-700">{{ previewSummary.unchanged }}</p>
                </div>
                <div>
                  <p class="text-slate-500">Ineligible</p>
                  <p class="text-xl font-semibold text-rose-700">{{ previewSummary.ineligible }}</p>
                </div>
                <div>
                  <p class="text-slate-500">Selected</p>
                  <p class="text-xl font-semibold text-slate-900">{{ selectedCount }}</p>
                </div>
              </div>
            </div>

            <button
              type="button"
              class="w-full rounded-xl bg-cyan-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="!canLaunchOperation || launching"
              @click="launchOperation"
            >
              {{ launching ? 'Queueing…' : 'Queue Batch Operation' }}
            </button>
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <h3 class="text-sm font-semibold text-slate-900">Recent Runs</h3>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="loadHistory">
              Refresh
            </button>
          </div>
          <div v-if="historyLoading" class="mt-4 text-sm text-slate-500">Loading recent Zenodo batch runs…</div>
          <div v-else-if="historyItems.length === 0" class="mt-4 text-sm text-slate-500">No batch operations recorded yet.</div>
          <div v-else class="mt-4 space-y-3">
            <article
              v-for="item in historyItems"
              :key="item.task_id"
              class="rounded-xl border border-slate-200 bg-slate-50 p-3"
            >
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-semibold text-slate-900">{{ historyTitle(item) }}</p>
                <span class="rounded-full border border-slate-300 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-700">
                  {{ item.state }}
                </span>
              </div>
              <p class="mt-1 text-xs text-slate-500">
                {{ item.created_at ? formatDate(item.created_at) : 'Unknown start time' }}
                <span v-if="item.requested_by?.email"> · {{ item.requested_by.email }}</span>
              </p>
              <p class="mt-2 text-xs text-slate-600">
                {{ item.summary?.processed || 0 }} / {{ item.summary?.total_records || item.selected_count || 0 }} processed ·
                {{ item.summary?.succeeded || 0 }} succeeded ·
                {{ item.summary?.failed || 0 }} failed
              </p>
              <div class="mt-3 flex items-center justify-between gap-2">
                <p class="text-xs text-slate-500">{{ item.status || 'No status recorded.' }}</p>
                <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-white" @click="restoreTask(item)">
                  Open
                </button>
              </div>
            </article>
          </div>
        </section>

        <section v-if="taskState" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <h3 class="text-sm font-semibold text-slate-900">Task Progress</h3>
            <span class="rounded-full border border-slate-300 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700">
              {{ taskState.state }}
            </span>
          </div>
          <p class="mt-2 text-sm text-slate-600">{{ taskState.status || 'Waiting for updates…' }}</p>
          <div class="mt-4 h-2.5 overflow-hidden rounded-full bg-slate-100">
            <div class="h-full rounded-full bg-cyan-600 transition-all duration-300" :style="{ width: `${taskProgress.percent || 0}%` }"></div>
          </div>
          <div class="mt-4 grid grid-cols-2 gap-3 text-sm">
            <div><p class="text-slate-500">Processed</p><p class="font-semibold text-slate-900">{{ taskProgress.processed || 0 }} / {{ taskProgress.total_records || 0 }}</p></div>
            <div><p class="text-slate-500">Succeeded</p><p class="font-semibold text-emerald-700">{{ taskProgress.succeeded || 0 }}</p></div>
            <div><p class="text-slate-500">Unchanged</p><p class="font-semibold text-slate-700">{{ taskProgress.unchanged || 0 }}</p></div>
            <div><p class="text-slate-500">Ineligible</p><p class="font-semibold text-rose-700">{{ taskProgress.ineligible || 0 }}</p></div>
            <div><p class="text-slate-500">Failed</p><p class="font-semibold text-rose-700">{{ taskProgress.failed || 0 }}</p></div>
            <div><p class="text-slate-500">Rate waits</p><p class="font-semibold text-amber-700">{{ taskProgress.rate_limited_waits || 0 }}</p></div>
          </div>
        </section>

        <section v-if="taskResults.length" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <h3 class="text-sm font-semibold text-slate-900">Latest Results</h3>
            <button type="button" class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="downloadResults">
              Export JSON
            </button>
          </div>
          <div class="mt-4 max-h-[420px] space-y-3 overflow-auto">
            <article
              v-for="result in taskResults.slice().reverse()"
              :key="`${result.session_id}-${result.local_record_id}-${result.status}`"
              class="rounded-xl border border-slate-200 bg-slate-50 p-3"
            >
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-semibold text-slate-900">
                  Session {{ result.session_id }} · Record {{ result.local_record_id }}
                </p>
                <span :class="resultStatusClass(result.status)" class="rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide">
                  {{ result.status }}
                </span>
              </div>
              <p class="mt-1 text-sm text-slate-600">{{ result.record_title || 'Untitled record' }}</p>
              <p class="mt-2 text-xs text-slate-500">{{ result.message || 'No message returned.' }}</p>
            </article>
          </div>
        </section>
      </aside>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import toolsService from '@/services/tools.service'
import { useToast } from '@/composables/useToast'

const toast = useToast()
const loading = ref(true)
const launching = ref(false)
const payload = ref(null)
const error = ref('')
const showError = computed(() => !!error.value)
const selection = ref(new Set())
const selectedRecordCatalog = ref(new Map())
const historyLoading = ref(false)
const historyItems = ref([])
const pollHandle = ref(null)
const taskId = ref('')
const taskState = ref(null)

const filters = ref({
  q: '',
  session_id: null,
  owner_user_id: null,
  record_status: 'all',
  is_sandbox: '',
  creator: '',
  community: '',
  publication_date_from: '',
  publication_date_to: '',
  updated_from: '',
  updated_to: '',
  page: 1,
  per_page: 10,
})

const operation = ref({
  operation: 'append_if_missing',
  remove_mode: 'one',
  community_identifier: '',
})

const summary = computed(() => payload.value?.summary || {})
const groups = computed(() => payload.value?.groups || [])
const sessionWarnings = computed(() => payload.value?.session_warnings || [])
const pagination = computed(() => payload.value?.pagination || { page: 1, total_pages: 1 })
const allFilteredRecordRefs = computed(() => payload.value?.all_filtered_record_refs || [])
const previewRecords = computed(() => payload.value?.all_filtered_records_preview || [])
const filteredRecordKeySet = computed(() => new Set(allFilteredRecordRefs.value.map((record) => `${record.session_id}:${record.local_record_id}`)))

const selectedCount = computed(() => selection.value.size)
const selectedPreviewRecords = computed(() => {
  const records = []
  for (const key of selection.value) {
    const record = selectedRecordCatalog.value.get(key)
    if (record) records.push(record)
  }
  return records
})
const selectedVisibleCount = computed(() => {
  let count = 0
  for (const key of selection.value) {
    if (filteredRecordKeySet.value.has(key)) {
      count += 1
    }
  }
  return count
})
const selectedOutsideCurrentFiltersCount = computed(() => Math.max(0, selectedCount.value - selectedVisibleCount.value))

const requiresCommunityIdentifier = computed(() => {
  return operation.value.operation === 'append_if_missing'
    || (operation.value.operation === 'remove_communities' && operation.value.remove_mode === 'one')
})

const currentOperationKey = computed(() => {
  if (operation.value.operation === 'append_if_missing') return 'append_if_missing'
  return operation.value.remove_mode === 'all' ? 'remove_all' : 'remove_one'
})

const previewSummary = computed(() => {
  const summaryValue = { actionable: 0, unchanged: 0, ineligible: 0 }
  const targetCommunity = (operation.value.community_identifier || '').trim().toLowerCase()
  for (const record of selectedPreviewRecords.value) {
    const eligibility = ((record.operation_eligibility || {})[currentOperationKey.value] || {})
    if (!eligibility.eligible) {
      summaryValue.ineligible += 1
      continue
    }
    const communities = (record.communities_normalized || []).map((item) => String(item).toLowerCase())
    if (currentOperationKey.value === 'append_if_missing') {
      if (targetCommunity && communities.includes(targetCommunity)) summaryValue.unchanged += 1
      else summaryValue.actionable += 1
    } else if (currentOperationKey.value === 'remove_one') {
      if (!targetCommunity || !communities.includes(targetCommunity)) summaryValue.unchanged += 1
      else summaryValue.actionable += 1
    } else {
      if (!communities.length) summaryValue.unchanged += 1
      else summaryValue.actionable += 1
    }
  }
  return summaryValue
})

const taskProgress = computed(() => taskState.value?.progress || taskState.value?.result?.progress || {})
const taskResults = computed(() => taskState.value?.result?.results || [])

const canLaunchOperation = computed(() => {
  if (selectedCount.value === 0) return false
  if (requiresCommunityIdentifier.value && !(operation.value.community_identifier || '').trim()) return false
  return previewSummary.value.actionable > 0
})

const recordKey = (record) => `${record.session_id}:${record.local_record_id}`

const mergeRecordCatalog = (records = []) => {
  const next = new Map(selectedRecordCatalog.value)
  for (const record of records) {
    if (!record || record.session_id == null || record.local_record_id == null) continue
    next.set(recordKey(record), record)
  }
  selectedRecordCatalog.value = next
}

const indexPayloadRecords = (responseData) => {
  if (!responseData || typeof responseData !== 'object') return
  const records = [...(responseData.all_filtered_records_preview || [])]
  for (const group of responseData.groups || []) {
    records.push(...(group.records || []))
  }
  mergeRecordCatalog(records)
}

const reconcileTaskResultsIntoCatalog = (results = []) => {
  const next = new Map(selectedRecordCatalog.value)
  for (const result of results) {
    if (!result || result.session_id == null || result.local_record_id == null) continue
    const key = `${result.session_id}:${result.local_record_id}`
    const existing = next.get(key)
    if (!existing) continue
    next.set(key, {
      ...existing,
      record_status: result.record_status || existing.record_status,
      communities_normalized: Array.isArray(result.after_communities)
        ? result.after_communities
        : existing.communities_normalized,
    })
  }
  selectedRecordCatalog.value = next
}

const isSelected = (record) => selection.value.has(recordKey(record))

const toggleRecord = (record) => {
  mergeRecordCatalog([record])
  const key = recordKey(record)
  const next = new Set(selection.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selection.value = next
}

const selectSession = (group, enabled) => {
  mergeRecordCatalog(group.records || [])
  const next = new Set(selection.value)
  for (const record of group.records || []) {
    const key = recordKey(record)
    if (enabled) next.add(key)
    else next.delete(key)
  }
  selection.value = next
}

const selectCurrentPage = () => {
  const next = new Set(selection.value)
  const currentPageRecords = []
  for (const group of groups.value) {
    currentPageRecords.push(...(group.records || []))
    for (const record of group.records || []) next.add(recordKey(record))
  }
  mergeRecordCatalog(currentPageRecords)
  selection.value = next
}

const selectAllFiltered = () => {
  mergeRecordCatalog(previewRecords.value)
  selection.value = new Set(allFilteredRecordRefs.value.map((record) => `${record.session_id}:${record.local_record_id}`))
}

const clearSelection = () => {
  selection.value = new Set()
  selectedRecordCatalog.value = new Map()
}

const formatDate = (value) => {
  if (!value) return 'N/A'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString()
}

const statusClass = (status) => {
  if (status === 'published') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'draft') return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-slate-200 bg-slate-100 text-slate-700'
}

const resultStatusClass = (status) => {
  if (status === 'succeeded') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'unchanged') return 'border-slate-200 bg-slate-100 text-slate-700'
  if (status === 'ineligible' || status === 'failed_capability_check') return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-rose-200 bg-rose-50 text-rose-700'
}

const historyTitle = (entry) => {
  if (!entry) return 'Unknown operation'
  if (entry.operation === 'append_if_missing') {
    return `Append '${entry.community_identifier || 'community'}' if missing`
  }
  if (entry.remove_mode === 'all') {
    return 'Remove all communities'
  }
  return `Remove '${entry.community_identifier || 'community'}'`
}

const currentEligibility = (record) => ((record.operation_eligibility || {})[currentOperationKey.value] || {})

const currentNoopReason = (record) => {
  const communities = (record.communities_normalized || []).map((item) => String(item).toLowerCase())
  const targetCommunity = (operation.value.community_identifier || '').trim().toLowerCase()
  if (currentOperationKey.value === 'append_if_missing' && targetCommunity && communities.includes(targetCommunity)) {
    return `Would be unchanged because '${operation.value.community_identifier.trim()}' is already present.`
  }
  if (currentOperationKey.value === 'remove_one' && targetCommunity && !communities.includes(targetCommunity)) {
    return `Would be unchanged because '${operation.value.community_identifier.trim()}' is not present.`
  }
  if (currentOperationKey.value === 'remove_all' && communities.length === 0) {
    return 'Would be unchanged because the record has no communities.'
  }
  return ''
}

const normalizedParams = () => {
  const params = {
    q: filters.value.q || undefined,
    session_id: filters.value.session_id || undefined,
    owner_user_id: filters.value.owner_user_id || undefined,
    record_status: filters.value.record_status || 'all',
    is_sandbox: filters.value.is_sandbox || undefined,
    creator: filters.value.creator || undefined,
    community: filters.value.community || undefined,
    publication_date_from: filters.value.publication_date_from || undefined,
    publication_date_to: filters.value.publication_date_to || undefined,
    updated_from: filters.value.updated_from ? new Date(filters.value.updated_from).toISOString() : undefined,
    updated_to: filters.value.updated_to ? new Date(filters.value.updated_to).toISOString() : undefined,
    page: filters.value.page,
    per_page: filters.value.per_page,
  }
  return params
}

const loadRecords = async () => {
  loading.value = true
  error.value = ''
  try {
    const response = await toolsService.getZenodoBatchOperationRecords(normalizedParams())
    payload.value = response.data
    indexPayloadRecords(response.data)
  } catch (err) {
    console.error('Failed to load Zenodo batch operation records', err)
    error.value = err.error?.message || err.message || 'Failed to load Zenodo batch operation records.'
  } finally {
    loading.value = false
  }
}

const loadHistory = async () => {
  historyLoading.value = true
  try {
    const response = await toolsService.getZenodoBatchOperationHistory({ limit: 12 })
    historyItems.value = response.data?.tasks || []
  } catch (err) {
    console.error('Failed to load Zenodo batch history', err)
  } finally {
    historyLoading.value = false
  }
}

const applyFilters = async () => {
  filters.value.page = 1
  await loadRecords()
}

const resetFilters = async () => {
  filters.value = {
    q: '',
    session_id: null,
    owner_user_id: null,
    record_status: 'all',
    is_sandbox: '',
    creator: '',
    community: '',
    publication_date_from: '',
    publication_date_to: '',
    updated_from: '',
    updated_to: '',
    page: 1,
    per_page: 10,
  }
  await loadRecords()
}

const changePage = async (page) => {
  filters.value.page = page
  await loadRecords()
}

const stopPolling = () => {
  if (pollHandle.value) {
    clearInterval(pollHandle.value)
    pollHandle.value = null
  }
}

const pollTask = async () => {
  if (!taskId.value) return
  try {
    const response = await toolsService.getZenodoBatchOperationTask(taskId.value)
    taskState.value = response.data
    reconcileTaskResultsIntoCatalog(response.data?.result?.results || [])
    if (['SUCCESS', 'FAILURE'].includes(response.data?.state)) {
      stopPolling()
      await loadHistory()
      if (response.data?.state === 'SUCCESS') {
        await loadRecords()
      }
    }
  } catch (err) {
    console.error('Failed to poll Zenodo batch task', err)
  }
}

const launchOperation = async () => {
  launching.value = true
  try {
    const payloadBody = {
      operation: operation.value.operation,
      remove_mode: operation.value.operation === 'remove_communities' ? operation.value.remove_mode : undefined,
      community_identifier: requiresCommunityIdentifier.value ? operation.value.community_identifier.trim() : undefined,
      record_refs: Array.from(selection.value).map((key) => {
        const [sessionId, localRecordId] = key.split(':')
        return {
          session_id: Number(sessionId),
          local_record_id: Number(localRecordId),
        }
      }),
    }
    const response = await toolsService.launchZenodoCommunityOperation(payloadBody)
    taskId.value = response.data?.task_id || ''
    taskState.value = {
      state: 'PENDING',
      status: 'Queued Zenodo community operation',
      progress: {
        total_records: selectedCount.value,
        processed: 0,
        percent: 0,
      },
      result: null,
    }
    toast.success('Zenodo batch operation queued')
    await loadHistory()
    stopPolling()
    await pollTask()
    pollHandle.value = setInterval(() => {
      pollTask()
    }, 2500)
  } catch (err) {
    console.error('Failed to queue Zenodo batch operation', err)
    toast.error(err.error?.message || err.message || 'Failed to queue Zenodo batch operation')
  } finally {
    launching.value = false
  }
}

const downloadResults = () => {
  const jsonString = JSON.stringify(taskState.value?.result || {}, null, 2)
  const blob = new Blob([jsonString], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `zenodo_batch_operation_${taskId.value || 'results'}.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const restoreTask = async (entry) => {
  taskId.value = entry?.task_id || ''
  taskState.value = {
    state: entry?.state || 'PENDING',
    status: entry?.status || 'Pending...',
    progress: entry?.progress || null,
    result: entry?.result || null,
    error: entry?.error || null,
  }
  if (!taskId.value) return

  stopPolling()
  if (!['SUCCESS', 'FAILURE'].includes(taskState.value.state)) {
    await pollTask()
    pollHandle.value = setInterval(() => {
      pollTask()
    }, 2500)
  }
}

onMounted(async () => {
  await Promise.all([loadRecords(), loadHistory()])
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>
