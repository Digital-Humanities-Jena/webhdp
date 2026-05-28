<template>
  <div class="min-h-screen bg-gradient-to-b from-slate-50 via-white to-slate-100">
    <div class="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6 lg:px-8">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 class="text-3xl font-bold text-slate-900">Issues Workspace</h1>
          <p class="mt-1 text-sm text-slate-600">
            Track your reports, triage incoming issues, and move from symptom to probable code location quickly.
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-rose-700"
            @click="handleReportIssue"
          >
            Report Issue
          </button>
          <button
            type="button"
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            :disabled="loading"
            @click="loadIssues"
          >
            Refresh
          </button>
        </div>
      </div>

      <LoadingSpinner v-if="loading && !issues.length" size="lg" text="Loading issues workspace..." />

      <div v-else class="space-y-6">
        <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <p class="text-xs uppercase tracking-wide text-slate-500">Visible Issues</p>
            <p class="mt-2 text-2xl font-bold text-slate-900">{{ issues.length }}</p>
          </div>
          <div class="rounded-2xl border border-amber-200 bg-white p-4 shadow-sm">
            <p class="text-xs uppercase tracking-wide text-amber-600">Open</p>
            <p class="mt-2 text-2xl font-bold text-amber-700">{{ openCount }}</p>
          </div>
          <div class="rounded-2xl border border-emerald-200 bg-white p-4 shadow-sm">
            <p class="text-xs uppercase tracking-wide text-emerald-600">Resolved</p>
            <p class="mt-2 text-2xl font-bold text-emerald-700">{{ resolvedCount }}</p>
          </div>
          <div class="rounded-2xl border border-indigo-200 bg-white p-4 shadow-sm">
            <p class="text-xs uppercase tracking-wide text-indigo-600">Queue Access</p>
            <p class="mt-2 text-sm font-semibold text-indigo-700">{{ triageAccess ? 'Enabled' : 'Reporter only' }}</p>
          </div>
        </div>

        <div class="rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div class="border-b border-slate-200 px-4 py-4">
            <div class="flex flex-wrap items-center gap-2">
              <button
                type="button"
                class="rounded-full border px-3 py-1.5 text-sm font-medium"
                :class="activeTab === 'my' ? 'border-indigo-300 bg-indigo-50 text-indigo-700' : 'border-slate-200 text-slate-700 hover:bg-slate-50'"
                @click="setActiveTab('my')"
              >
                My Issues
              </button>
              <button
                v-if="triageAccess"
                type="button"
                class="rounded-full border px-3 py-1.5 text-sm font-medium"
                :class="activeTab === 'queue' ? 'border-slate-300 bg-slate-900 text-white' : 'border-slate-200 text-slate-700 hover:bg-slate-50'"
                @click="setActiveTab('queue')"
              >
                Shared Triage Queue
              </button>
            </div>
          </div>

          <div class="grid grid-cols-1 gap-3 border-b border-slate-200 px-4 py-4 md:grid-cols-4">
            <div>
              <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">Status</label>
              <select
                v-model="filters.status"
                class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400"
                @change="loadIssues"
              >
                <option value="">All statuses</option>
                <option v-for="option in statuses" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">Page</label>
              <select
                v-model="filters.page_key"
                class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus:border-indigo-400 focus:ring-indigo-400"
                @change="loadIssues"
              >
                <option value="">All pages</option>
                <option v-for="page in pages" :key="page.page_key" :value="page.page_key">
                  {{ page.label }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">Issue Count</label>
              <p class="mt-3 text-sm font-medium text-slate-700">{{ issues.length }} item<span v-if="issues.length !== 1">s</span></p>
            </div>
            <div>
              <label class="block text-xs font-semibold uppercase tracking-wide text-slate-500">Scope</label>
              <p class="mt-3 text-sm font-medium text-slate-700">{{ activeTab === 'queue' ? 'All triage-visible issues' : 'Reporter-owned issues only' }}</p>
            </div>
          </div>

          <div v-if="error" class="border-b border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {{ error }}
          </div>

          <div v-if="loading && issues.length" class="px-4 py-3 text-sm text-slate-500">
            Refreshing issues…
          </div>

          <div v-if="!issues.length && !loading" class="px-6 py-12 text-center text-sm text-slate-500">
            No issues matched the current view.
          </div>

          <div v-else class="overflow-x-auto">
            <table class="min-w-full divide-y divide-slate-200">
              <thead class="bg-slate-50">
                <tr>
                  <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Issue</th>
                  <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Page</th>
                  <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Status</th>
                  <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Impact</th>
                  <th v-if="triageAccess" class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Priority</th>
                  <th v-if="triageAccess" class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Assignee</th>
                  <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Reporter</th>
                  <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Updated</th>
                  <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 bg-white">
                <tr v-for="issue in issues" :key="issue.id" class="hover:bg-slate-50">
                  <td class="px-4 py-4 align-top">
                    <p class="text-sm font-semibold text-slate-900">{{ issue.title }}</p>
                    <p class="mt-1 text-xs text-slate-500 line-clamp-2">
                      {{ issue.public_description || issue.expected_behavior || 'No detail provided yet.' }}
                    </p>
                    <div
                      v-if="triageAccess && (issue.code_references?.first_order || []).length"
                      class="mt-2 space-y-1"
                    >
                      <p class="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Top probable references</p>
                      <p
                        v-for="item in (issue.code_references?.first_order || []).slice(0, 2)"
                        :key="`${issue.id}-${item.kind}-${item.path_or_endpoint}`"
                        class="font-mono text-[11px] text-slate-600 break-all"
                      >
                        {{ item.path_or_endpoint }}
                      </p>
                    </div>
                  </td>
                  <td class="px-4 py-4 align-top text-sm text-slate-700">
                    <p class="font-medium">{{ issue.page_label || issue.page_key || 'Unknown page' }}</p>
                    <p class="mt-1 font-mono text-xs text-slate-500">{{ issue.route_path || issue.route_name || 'n/a' }}</p>
                  </td>
                  <td class="px-4 py-4 align-top">
                    <span class="rounded-full px-2.5 py-1 text-xs font-semibold" :class="statusClass(issue.status)">
                      {{ issue.status }}
                    </span>
                  </td>
                  <td class="px-4 py-4 align-top">
                    <span class="rounded-full px-2.5 py-1 text-xs font-semibold" :class="impactClass(issue.reporter_impact)">
                      {{ issue.reporter_impact }}
                    </span>
                  </td>
                  <td v-if="triageAccess" class="px-4 py-4 align-top">
                    <span class="rounded-full px-2.5 py-1 text-xs font-semibold" :class="priorityClass(issue.internal_priority)">
                      {{ issue.internal_priority || 'n/a' }}
                    </span>
                  </td>
                  <td v-if="triageAccess" class="px-4 py-4 align-top text-sm text-slate-700">
                    {{ issue.assignee?.email || 'Unassigned' }}
                  </td>
                  <td class="px-4 py-4 align-top text-sm text-slate-700">
                    {{ issue.reporter?.email || `User #${issue.reporter_user_id}` }}
                  </td>
                  <td class="px-4 py-4 align-top text-sm text-slate-500">
                    {{ formatDate(issue.updated_at || issue.created_at) }}
                  </td>
                  <td class="px-4 py-4 align-top text-sm">
                    <router-link :to="`/issues/${issue.id}`" class="font-medium text-indigo-600 hover:text-indigo-800">
                      Open
                    </router-link>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import issueService from '@/services/issue.service'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import { useAuthStore } from '@/stores/auth'
import { buildIssueDraftContext, saveIssueDraftContext } from '@/utils/issueDraft'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(true)
const error = ref('')
const issues = ref([])
const pages = ref([])
const statuses = ref([])
const triageAccess = ref(false)
const activeTab = ref('my')
const filters = reactive({
  status: '',
  page_key: '',
})

const openCount = computed(() => issues.value.filter((issue) => !['resolved', 'closed'].includes(issue.status)).length)
const resolvedCount = computed(() => issues.value.filter((issue) => ['resolved', 'closed'].includes(issue.status)).length)

function statusClass(status) {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'resolved' || normalized === 'closed') return 'bg-emerald-100 text-emerald-700'
  if (normalized === 'blocked' || normalized === 'needs_info') return 'bg-amber-100 text-amber-700'
  if (normalized === 'in_progress' || normalized === 'triaged') return 'bg-indigo-100 text-indigo-700'
  return 'bg-slate-100 text-slate-700'
}

function impactClass(impact) {
  const normalized = String(impact || '').trim().toLowerCase()
  if (normalized === 'blocking') return 'bg-rose-100 text-rose-700'
  if (normalized === 'high') return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-700'
}

function priorityClass(priority) {
  const normalized = String(priority || '').trim().toLowerCase()
  if (normalized === 'urgent') return 'bg-rose-100 text-rose-700'
  if (normalized === 'high') return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-700'
}

function formatDate(value) {
  if (!value) return 'N/A'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

function handleReportIssue() {
  saveIssueDraftContext(buildIssueDraftContext({ route, user: authStore.user }))
  router.push('/issues/report')
}

async function loadRegistry() {
  const response = await issueService.getRegistry()
  pages.value = response.data?.pages || []
  statuses.value = response.data?.statuses || []
}

async function loadIssues() {
  loading.value = true
  error.value = ''
  try {
    const response = await issueService.listIssues({
      scope: activeTab.value,
      status: filters.status || undefined,
      page_key: filters.page_key || undefined,
    })
    issues.value = response.data?.issues || []
    triageAccess.value = Boolean(response.data?.permissions?.can_view_issue_queue)
    if (!triageAccess.value && activeTab.value === 'queue') {
      activeTab.value = 'my'
    }
  } catch (err) {
    console.error('Failed to load issues:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load issues.'
  } finally {
    loading.value = false
  }
}

async function setActiveTab(nextTab) {
  activeTab.value = nextTab
  await loadIssues()
}

onMounted(async () => {
  try {
    await loadRegistry()
  } catch (err) {
    console.error('Failed to load issue registry:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load issue registry.'
  }
  await loadIssues()
})
</script>
