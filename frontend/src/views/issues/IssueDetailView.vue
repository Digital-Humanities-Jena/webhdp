<template>
  <div class="min-h-screen bg-gradient-to-b from-slate-50 via-white to-slate-100">
    <div class="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6 lg:px-8">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <router-link to="/issues" class="text-sm font-medium text-indigo-600 hover:text-indigo-800">
            &larr; Back to Issues
          </router-link>
          <h1 class="mt-2 text-3xl font-bold text-slate-900">
            <template v-if="issue">Issue #{{ issue.id }}</template>
            <template v-else>Issue Detail</template>
          </h1>
          <p class="mt-1 text-sm text-slate-600">
            Reporter context, discussion, and deterministic probable code references in one view.
          </p>
        </div>
        <div class="flex flex-wrap gap-2" v-if="issue">
          <span class="rounded-full px-3 py-1.5 text-sm font-semibold" :class="statusClass(issue.status)">
            {{ issue.status }}
          </span>
          <button
            v-if="issue.permissions?.can_edit_internal_fields"
            type="button"
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            :disabled="refreshingRefs"
            @click="handleRefreshReferences"
          >
            {{ refreshingRefs ? 'Refreshing…' : 'Refresh Code References' }}
          </button>
        </div>
      </div>

      <LoadingSpinner v-if="loading" size="lg" text="Loading issue detail..." />

      <div v-else-if="error" class="rounded-2xl border border-rose-200 bg-white p-6 text-sm text-rose-700 shadow-sm">
        {{ error }}
      </div>

      <div v-else-if="issue" class="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <section class="space-y-6">
          <article class="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div class="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 class="text-xl font-semibold text-slate-900">{{ issue.title }}</h2>
                <p class="mt-2 text-sm text-slate-500">
                  Reported by {{ issue.reporter?.email || `user #${issue.reporter_user_id}` }}
                  on {{ formatDate(issue.created_at) }}
                </p>
              </div>
              <div class="grid grid-cols-2 gap-3 text-sm">
                <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Page</p>
                  <p class="mt-1 font-medium text-slate-900">{{ issue.page_label || issue.page_key || 'Unknown' }}</p>
                </div>
                <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Impact</p>
                  <p class="mt-1 font-medium text-slate-900">{{ issue.reporter_impact }}</p>
                </div>
                <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Type</p>
                  <p class="mt-1 font-medium text-slate-900">{{ issue.issue_type }}</p>
                </div>
                <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <p class="text-xs uppercase tracking-wide text-slate-500">Route</p>
                  <p class="mt-1 font-mono text-xs text-slate-700 break-all">{{ issue.route_path || issue.route_name || 'n/a' }}</p>
                </div>
              </div>
            </div>
          </article>

          <article class="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div class="flex items-start justify-between gap-4">
              <div>
                <h2 class="text-lg font-semibold text-slate-900">Report details</h2>
                <p class="mt-1 text-sm text-slate-500">
                  Reporter-editable while the issue is still new or waiting for more information.
                </p>
              </div>
              <span
                class="rounded-full px-2.5 py-1 text-xs font-semibold"
                :class="issue.permissions?.can_reporter_edit || issue.permissions?.can_edit_internal_fields ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'"
              >
                {{ issue.permissions?.can_reporter_edit || issue.permissions?.can_edit_internal_fields ? 'Editable' : 'Read only' }}
              </span>
            </div>

            <div class="mt-5 grid grid-cols-1 gap-4">
              <div>
                <label class="block text-sm font-medium text-slate-700">Title</label>
                <input
                  v-model.trim="reportForm.title"
                  type="text"
                  :disabled="!canEditReportFields || savingReport"
                  class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                />
              </div>
              <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label class="block text-sm font-medium text-slate-700">Issue type</label>
                  <select
                    v-model="reportForm.issue_type"
                    :disabled="!canEditReportFields || savingReport"
                    class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                  >
                    <option v-for="option in issueTypes" :key="option.value" :value="option.value">
                      {{ option.label }}
                    </option>
                  </select>
                </div>
                <div>
                  <label class="block text-sm font-medium text-slate-700">Impact</label>
                  <select
                    v-model="reportForm.reporter_impact"
                    :disabled="!canEditReportFields || savingReport"
                    class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                  >
                    <option v-for="option in reporterImpacts" :key="option.value" :value="option.value">
                      {{ option.label }}
                    </option>
                  </select>
                </div>
              </div>
              <div>
                <label class="block text-sm font-medium text-slate-700">Exact page</label>
                <select
                  v-model="reportForm.page_key"
                  :disabled="!canEditReportFields || savingReport"
                  class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                >
                  <option value="" disabled>Select the page where the issue occurred</option>
                  <option v-for="page in pageOptions" :key="page.page_key" :value="page.page_key">
                    {{ page.label }}
                  </option>
                </select>
                <p class="mt-2 text-xs text-slate-500">
                  Route context remains captured separately at
                  <span class="font-mono text-slate-700">{{ issue.route_path || issue.route_name || 'n/a' }}</span>.
                </p>
              </div>
              <div>
                <label class="block text-sm font-medium text-slate-700">What happened?</label>
                <textarea
                  v-model.trim="reportForm.public_description"
                  rows="4"
                  :disabled="!canEditReportFields || savingReport"
                  class="mt-1 block w-full rounded-2xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                />
              </div>
              <div>
                <label class="block text-sm font-medium text-slate-700">Expected behavior</label>
                <textarea
                  v-model.trim="reportForm.expected_behavior"
                  rows="4"
                  :disabled="!canEditReportFields || savingReport"
                  class="mt-1 block w-full rounded-2xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                />
              </div>
              <div v-if="hasTechnicalFields || canEditReportFields" class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <p class="text-sm font-semibold text-slate-900">Technical detail</p>
                <div class="mt-3 grid grid-cols-1 gap-4">
                  <div>
                    <p class="text-xs uppercase tracking-wide text-slate-500">Reproduction</p>
                    <textarea
                      v-if="canEditReportFields"
                      v-model.trim="reportForm.reproduction_steps"
                      rows="3"
                      :disabled="savingReport"
                      class="mt-1 block w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                    />
                    <p v-else class="mt-1 whitespace-pre-wrap text-sm text-slate-700">{{ issue.reproduction_steps }}</p>
                  </div>
                  <div>
                    <p class="text-xs uppercase tracking-wide text-slate-500">Technical details</p>
                    <textarea
                      v-if="canEditReportFields"
                      v-model.trim="reportForm.technical_details"
                      rows="3"
                      :disabled="savingReport"
                      class="mt-1 block w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                    />
                    <p v-else class="mt-1 whitespace-pre-wrap text-sm text-slate-700">{{ issue.technical_details }}</p>
                  </div>
                  <div>
                    <p class="text-xs uppercase tracking-wide text-slate-500">Console notes</p>
                    <textarea
                      v-if="canEditReportFields"
                      v-model.trim="reportForm.console_notes"
                      rows="3"
                      :disabled="savingReport"
                      class="mt-1 block w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                    />
                    <p v-else class="mt-1 whitespace-pre-wrap text-sm text-slate-700">{{ issue.console_notes }}</p>
                  </div>
                  <div>
                    <p class="text-xs uppercase tracking-wide text-slate-500">API notes</p>
                    <textarea
                      v-if="canEditReportFields"
                      v-model.trim="reportForm.api_notes"
                      rows="3"
                      :disabled="savingReport"
                      class="mt-1 block w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                    />
                    <p v-else class="mt-1 whitespace-pre-wrap text-sm text-slate-700">{{ issue.api_notes }}</p>
                  </div>
                  <div>
                    <p class="text-xs uppercase tracking-wide text-slate-500">Suspected subsystem</p>
                    <input
                      v-if="canEditReportFields"
                      v-model.trim="reportForm.suspected_subsystem"
                      type="text"
                      :disabled="savingReport"
                      class="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400 disabled:bg-slate-50"
                    />
                    <p v-else class="mt-1 text-sm font-medium text-slate-900">{{ issue.suspected_subsystem }}</p>
                  </div>
                </div>
              </div>
              <div v-if="canEditReportFields" class="flex justify-end">
                <button
                  type="button"
                  :disabled="savingReport"
                  class="rounded-xl bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60"
                  @click="saveReportFields"
                >
                  {{ savingReport ? 'Saving…' : 'Save Report Details' }}
                </button>
              </div>
            </div>
          </article>

          <article class="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <div class="flex items-start justify-between gap-4">
              <div>
                <h2 class="text-lg font-semibold text-slate-900">Discussion</h2>
                <p class="mt-1 text-sm text-slate-500">
                  Public replies are visible to the reporter. Internal notes remain triage-only.
                </p>
              </div>
            </div>

            <div class="mt-5 space-y-4">
              <div
                v-for="comment in issue.comments || []"
                :key="comment.id"
                class="rounded-2xl border border-slate-200 bg-slate-50 p-4"
              >
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div class="flex items-center gap-2">
                    <p class="text-sm font-semibold text-slate-900">
                      {{ comment.author?.email || `User #${comment.author_user_id}` }}
                    </p>
                    <span
                      v-if="comment.is_internal"
                      class="rounded-full bg-slate-900 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white"
                    >
                      Internal
                    </span>
                  </div>
                  <p class="text-xs text-slate-500">{{ formatDate(comment.created_at) }}</p>
                </div>
                <p class="mt-3 whitespace-pre-wrap text-sm text-slate-700">{{ comment.body }}</p>
              </div>

              <div v-if="!(issue.comments || []).length" class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5 text-sm text-slate-500">
                No comments yet.
              </div>
            </div>

            <div class="mt-6 rounded-2xl border border-slate-200 bg-white p-4">
              <label class="block text-sm font-medium text-slate-700">Add comment</label>
              <textarea
                v-model.trim="commentForm.body"
                rows="4"
                class="mt-2 block w-full rounded-2xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400"
                placeholder="Add an update, question, or resolution note."
              />
              <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
                <label
                  v-if="issue.permissions?.can_comment_internal"
                  class="inline-flex items-center gap-2 text-sm text-slate-700"
                >
                  <input
                    v-model="commentForm.is_internal"
                    type="checkbox"
                    class="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span>Internal triage note</span>
                </label>
                <div class="ml-auto">
                  <button
                    type="button"
                    :disabled="savingComment"
                    class="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
                    @click="submitComment"
                  >
                    {{ savingComment ? 'Posting…' : 'Post Comment' }}
                  </button>
                </div>
              </div>
            </div>
          </article>
        </section>

        <aside class="space-y-6">
          <article
            v-if="issue.permissions?.can_edit_internal_fields"
            class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <div class="flex items-start justify-between gap-3">
              <div>
                <h2 class="text-sm font-semibold text-slate-900">Triage Controls</h2>
                <p class="mt-1 text-sm text-slate-500">Status, priority, and ownership stay internal.</p>
              </div>
              <span class="rounded-full bg-slate-900 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white">
                Internal
              </span>
            </div>

            <div class="mt-4 space-y-4">
              <div>
                <label class="block text-sm font-medium text-slate-700">Status</label>
                <select
                  v-model="triageForm.status"
                  :disabled="savingTriage"
                  class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:ring-slate-500"
                >
                  <option v-for="option in statuses" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </div>

              <div>
                <label class="block text-sm font-medium text-slate-700">Internal priority</label>
                <select
                  v-model="triageForm.internal_priority"
                  :disabled="savingTriage"
                  class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:ring-slate-500"
                >
                  <option v-for="option in priorities" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </div>

              <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <p class="text-xs uppercase tracking-wide text-slate-500">Assignee</p>
                <select
                  v-model="triageForm.assignee_user_id"
                  :disabled="savingTriage || !issue.permissions?.can_assign_issues"
                  class="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm focus:border-slate-500 focus:ring-slate-500 disabled:bg-slate-50"
                >
                  <option :value="null">Unassigned</option>
                  <option v-for="userOption in assignableUsers" :key="userOption.id" :value="userOption.id">
                    {{ formatAssigneeOption(userOption) }}
                  </option>
                </select>
                <p class="mt-2 text-xs text-slate-500">
                  Current owner:
                  <span class="font-medium text-slate-700">{{ issue.assignee?.email || 'Unassigned' }}</span>
                </p>
                <div class="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    :disabled="savingTriage || !issue.permissions?.can_assign_issues"
                    class="rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-white"
                    @click="assignToMe"
                  >
                    Assign to me
                  </button>
                  <button
                    type="button"
                    :disabled="savingTriage || !issue.assignee_user_id"
                    class="rounded-xl border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-white disabled:opacity-60"
                    @click="clearAssignee"
                  >
                    Clear assignee
                  </button>
                </div>
              </div>

              <button
                type="button"
                :disabled="savingTriage"
                class="w-full rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
                @click="saveTriageFields"
              >
                {{ savingTriage ? 'Saving…' : 'Save Triage State' }}
              </button>
            </div>
          </article>

          <article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 class="text-sm font-semibold text-slate-900">Captured Context</h2>
            <div class="mt-4 space-y-3 text-sm">
              <div>
                <p class="text-xs uppercase tracking-wide text-slate-500">Current URL</p>
                <p class="mt-1 font-mono text-xs text-slate-700 break-all">{{ issue.current_url || 'Unavailable' }}</p>
              </div>
              <div>
                <p class="text-xs uppercase tracking-wide text-slate-500">Reporter groups</p>
                <p class="mt-1 text-slate-700">{{ (issue.user_context?.reporter_groups || []).join(', ') || 'None' }}</p>
              </div>
              <div>
                <p class="text-xs uppercase tracking-wide text-slate-500">Application version</p>
                <p class="mt-1 text-slate-700">
                  {{ issue.environment_context?.app_version?.version || 'unknown' }}
                  <span class="text-xs text-slate-500">
                    · {{ issue.environment_context?.app_version?.timestamp || 'unknown' }}
                  </span>
                </p>
              </div>
            </div>
            <details class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <summary class="cursor-pointer text-sm font-semibold text-slate-900">Raw context JSON</summary>
              <pre class="mt-3 max-h-[18rem] overflow-auto text-xs leading-5 text-slate-700">{{ contextPreview }}</pre>
            </details>
          </article>

          <article class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold text-slate-900">Probable Code References</h2>
              <span
                class="rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide"
                :class="issue.permissions?.can_edit_internal_fields ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-500'"
              >
                {{ issue.permissions?.can_edit_internal_fields ? 'Visible' : 'Triage only' }}
              </span>
            </div>

            <div
              v-if="!issue.permissions?.can_edit_internal_fields"
              class="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500"
            >
              Code intelligence is available to moderators, admins, and developer-group users.
            </div>

            <div v-else class="mt-4 space-y-5">
              <section v-for="group in codeReferenceGroups" :key="group.key">
                <div class="flex items-center justify-between gap-3">
                  <h3 class="text-xs font-semibold uppercase tracking-wide text-slate-500">{{ group.label }}</h3>
                  <span class="text-xs text-slate-400">{{ group.items.length }}</span>
                </div>
                <div v-if="!group.items.length" class="mt-2 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-3 text-sm text-slate-500">
                  No references resolved for this order.
                </div>
                <div v-else class="mt-2 space-y-3">
                  <div
                    v-for="item in group.items"
                    :key="`${group.key}-${item.kind}-${item.path_or_endpoint}`"
                    class="rounded-2xl border border-slate-200 bg-slate-50 p-4"
                  >
                    <div class="flex items-start justify-between gap-3">
                      <div>
                        <p class="text-sm font-semibold text-slate-900">{{ item.label }}</p>
                        <p class="mt-1 font-mono text-xs text-slate-600 break-all">{{ item.path_or_endpoint }}</p>
                      </div>
                      <span class="rounded-full bg-white px-2 py-1 text-[11px] font-semibold text-slate-600">
                        {{ item.score }}
                      </span>
                    </div>
                    <p class="mt-3 text-xs leading-5 text-slate-600">{{ item.reason }}</p>
                  </div>
                </div>
              </section>
            </div>
          </article>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import issueService from '@/services/issue.service'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const authStore = useAuthStore()
const toast = useToast()

const loading = ref(true)
const error = ref('')
const issue = ref(null)
const registry = ref({ statuses: [], internal_priorities: [], issue_types: [], reporter_impacts: [] })
const savingReport = ref(false)
const savingTriage = ref(false)
const savingComment = ref(false)
const refreshingRefs = ref(false)

const reportForm = reactive({
  title: '',
  issue_type: 'general',
  reporter_impact: 'medium',
  page_key: '',
  public_description: '',
  expected_behavior: '',
  technical_details: '',
  reproduction_steps: '',
  console_notes: '',
  api_notes: '',
  suspected_subsystem: '',
})

const triageForm = reactive({
  status: 'new',
  internal_priority: 'medium',
  assignee_user_id: null,
})

const commentForm = reactive({
  body: '',
  is_internal: false,
})

const statuses = computed(() => registry.value.statuses || [])
const priorities = computed(() => registry.value.internal_priorities || [])
const issueTypes = computed(() => registry.value.issue_types || [])
const reporterImpacts = computed(() => registry.value.reporter_impacts || [])
const assignableUsers = computed(() => registry.value.assignable_users || [])
const canEditReportFields = computed(() => Boolean(issue.value?.permissions?.can_reporter_edit || issue.value?.permissions?.can_edit_internal_fields))
const hasTechnicalFields = computed(() => Boolean(
  issue.value?.technical_details ||
  issue.value?.reproduction_steps ||
  issue.value?.console_notes ||
  issue.value?.api_notes ||
  issue.value?.suspected_subsystem
))
const pageOptions = computed(() => (registry.value.pages || []).map((page) => ({
  page_key: page.page_key,
  label: `${page.label} · ${page.route_templates?.[0] || page.route_name || page.page_key}`,
})))
const selectedPage = computed(() => (registry.value.pages || []).find((page) => page.page_key === reportForm.page_key) || null)

const codeReferenceGroups = computed(() => {
  const references = issue.value?.code_references || {}
  return [
    { key: 'first_order', label: 'First order', items: references.first_order || [] },
    { key: 'second_order', label: 'Second order', items: references.second_order || [] },
    { key: 'third_order', label: 'Third order', items: references.third_order || [] },
  ]
})

const contextPreview = computed(() => JSON.stringify({
  route_context: issue.value?.route_context || {},
  related_entity_ids: issue.value?.related_entity_ids || {},
  environment_context: issue.value?.environment_context || {},
  user_context: issue.value?.user_context || {},
  capture_context: issue.value?.capture_context || {},
}, null, 2))

function statusClass(status) {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'resolved' || normalized === 'closed') return 'bg-emerald-100 text-emerald-700'
  if (normalized === 'blocked' || normalized === 'needs_info') return 'bg-amber-100 text-amber-700'
  if (normalized === 'in_progress' || normalized === 'triaged') return 'bg-indigo-100 text-indigo-700'
  return 'bg-slate-100 text-slate-700'
}

function formatDate(value) {
  if (!value) return 'N/A'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

function formatAssigneeOption(userOption) {
  const email = userOption?.email || `User #${userOption?.id}`
  return userOption?.role ? `${email} (${userOption.role})` : email
}

function syncForms() {
  if (!issue.value) return
  reportForm.title = issue.value.title || ''
  reportForm.issue_type = issue.value.issue_type || 'general'
  reportForm.reporter_impact = issue.value.reporter_impact || 'medium'
  reportForm.page_key = issue.value.page_key || ''
  reportForm.public_description = issue.value.public_description || ''
  reportForm.expected_behavior = issue.value.expected_behavior || ''
  reportForm.technical_details = issue.value.technical_details || ''
  reportForm.reproduction_steps = issue.value.reproduction_steps || ''
  reportForm.console_notes = issue.value.console_notes || ''
  reportForm.api_notes = issue.value.api_notes || ''
  reportForm.suspected_subsystem = issue.value.suspected_subsystem || ''
  triageForm.status = issue.value.status || 'new'
  triageForm.internal_priority = issue.value.internal_priority || 'medium'
  triageForm.assignee_user_id = issue.value.assignee_user_id ?? null
  commentForm.body = ''
  commentForm.is_internal = false
}

async function loadRegistry() {
  const response = await issueService.getRegistry()
  registry.value = response.data || registry.value
}

async function loadIssue() {
  loading.value = true
  error.value = ''
  try {
    const response = await issueService.getIssue(route.params.issueId)
    issue.value = response.data?.issue || null
    syncForms()
  } catch (err) {
    console.error('Failed to load issue:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load issue.'
  } finally {
    loading.value = false
  }
}

async function saveReportFields() {
  if (!issue.value) return
  savingReport.value = true
  try {
    const response = await issueService.updateIssue(issue.value.id, {
      title: reportForm.title,
      issue_type: reportForm.issue_type,
      reporter_impact: reportForm.reporter_impact,
      page_key: reportForm.page_key,
      page_label: selectedPage.value?.label || issue.value.page_label || null,
      public_description: reportForm.public_description,
      expected_behavior: reportForm.expected_behavior,
      technical_details: reportForm.technical_details,
      reproduction_steps: reportForm.reproduction_steps,
      console_notes: reportForm.console_notes,
      api_notes: reportForm.api_notes,
      suspected_subsystem: reportForm.suspected_subsystem,
    })
    issue.value = response.data?.issue || issue.value
    syncForms()
    toast.success('Issue report updated')
  } catch (err) {
    console.error('Failed to update issue report:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to update issue report.')
  } finally {
    savingReport.value = false
  }
}

async function saveTriageFields(extraPayload = {}) {
  if (!issue.value) return
  savingTriage.value = true
  try {
    const response = await issueService.updateIssue(issue.value.id, {
      status: triageForm.status,
      internal_priority: triageForm.internal_priority,
      assignee_user_id: triageForm.assignee_user_id,
      ...extraPayload,
    })
    issue.value = response.data?.issue || issue.value
    syncForms()
    toast.success('Triage state updated')
  } catch (err) {
    console.error('Failed to update triage state:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to update triage state.')
  } finally {
    savingTriage.value = false
  }
}

async function assignToMe() {
  await saveTriageFields({ assignee_user_id: authStore.user?.id || null })
}

async function clearAssignee() {
  await saveTriageFields({ assignee_user_id: null })
}

async function submitComment() {
  if (!issue.value) return
  savingComment.value = true
  try {
    const response = await issueService.addComment(issue.value.id, {
      body: commentForm.body,
      is_internal: commentForm.is_internal,
    })
    issue.value = response.data?.issue || issue.value
    syncForms()
    toast.success('Comment added')
  } catch (err) {
    console.error('Failed to add issue comment:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to add comment.')
  } finally {
    savingComment.value = false
  }
}

async function handleRefreshReferences() {
  if (!issue.value) return
  refreshingRefs.value = true
  try {
    const response = await issueService.refreshCodeReferences(issue.value.id)
    issue.value = response.data?.issue || issue.value
    syncForms()
    toast.success('Code references refreshed')
  } catch (err) {
    console.error('Failed to refresh code references:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to refresh code references.')
  } finally {
    refreshingRefs.value = false
  }
}

onMounted(async () => {
  try {
    await loadRegistry()
  } catch (err) {
    console.error('Failed to load issue registry:', err)
  }
  await loadIssue()
})
</script>
