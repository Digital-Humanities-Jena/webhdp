<template>
  <div class="min-h-screen bg-gradient-to-b from-rose-50 via-white to-slate-50">
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <router-link to="/issues" class="text-sm font-medium text-indigo-600 hover:text-indigo-800">
            &larr; Back to Issues
          </router-link>
          <h1 class="mt-2 text-3xl font-bold text-slate-900">Report an Issue</h1>
          <p class="mt-1 text-sm text-slate-600">
            Capture the current page precisely, describe the problem clearly, and include technical detail only when useful.
          </p>
        </div>
        <div class="rounded-2xl border border-rose-200 bg-white px-4 py-3 shadow-sm">
          <p class="text-xs uppercase tracking-wide text-rose-600">Mode</p>
          <div class="mt-2 flex gap-2">
            <button
              type="button"
              class="rounded-full border px-3 py-1.5 text-sm font-medium"
              :class="mode === 'simple' ? 'border-rose-300 bg-rose-50 text-rose-700' : 'border-slate-200 text-slate-700 hover:bg-slate-50'"
              @click="mode = 'simple'"
            >
              Simple
            </button>
            <button
              type="button"
              class="rounded-full border px-3 py-1.5 text-sm font-medium"
              :class="mode === 'technical' ? 'border-slate-300 bg-slate-900 text-white' : 'border-slate-200 text-slate-700 hover:bg-slate-50'"
              @click="mode = 'technical'"
            >
              Technical
            </button>
          </div>
        </div>
      </div>

      <LoadingSpinner v-if="loading" size="lg" text="Preparing issue report context..." />

      <div v-else class="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <section class="rounded-3xl border border-slate-200 bg-white shadow-sm">
          <div class="border-b border-slate-200 px-6 py-5">
            <h2 class="text-lg font-semibold text-slate-900">Intake</h2>
            <p class="mt-1 text-sm text-slate-500">
              The form is structured for both plain-language bug reports and developer-level diagnostics.
            </p>
          </div>

          <form class="space-y-6 px-6 py-6" @submit.prevent="handleSubmit">
            <div v-if="error" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {{ error }}
            </div>

            <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div class="md:col-span-2">
                <label class="block text-sm font-medium text-slate-700">Title</label>
                <input
                  v-model.trim="form.title"
                  type="text"
                  placeholder="Short summary of the problem"
                  class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-rose-400 focus:ring-rose-400"
                />
              </div>

              <div>
                <label class="block text-sm font-medium text-slate-700">Impact</label>
                <select
                  v-model="form.reporter_impact"
                  class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-rose-400 focus:ring-rose-400"
                >
                  <option v-for="option in reporterImpacts" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </div>

              <div>
                <label class="block text-sm font-medium text-slate-700">Issue type</label>
                <select
                  v-model="form.issue_type"
                  class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-rose-400 focus:ring-rose-400"
                >
                  <option v-for="option in issueTypes" :key="option.value" :value="option.value">
                    {{ option.label }}
                  </option>
                </select>
              </div>

              <div class="md:col-span-2">
                <label class="block text-sm font-medium text-slate-700">Exact page</label>
                <select
                  v-model="form.page_key"
                  class="mt-1 block w-full rounded-xl border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-rose-400 focus:ring-rose-400"
                >
                  <option value="" disabled>Select the page where the issue occurred</option>
                  <option v-for="option in pageOptions" :key="option.page_key" :value="option.page_key">
                    {{ option.label }}
                  </option>
                </select>
                <div class="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                  <span v-if="form.route_path">Detected route: <span class="font-mono text-slate-700">{{ form.route_path }}</span></span>
                  <span v-if="selectedPage?.route_name">Route name: <span class="font-medium text-slate-700">{{ selectedPage.route_name }}</span></span>
                </div>
              </div>

              <div class="md:col-span-2">
                <label class="block text-sm font-medium text-slate-700">What went wrong?</label>
                <textarea
                  v-model.trim="form.public_description"
                  rows="5"
                  placeholder="Describe what you saw."
                  class="mt-1 block w-full rounded-2xl border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-rose-400 focus:ring-rose-400"
                />
              </div>

              <div class="md:col-span-2">
                <label class="block text-sm font-medium text-slate-700">What did you expect instead?</label>
                <textarea
                  v-model.trim="form.expected_behavior"
                  rows="4"
                  placeholder="Describe the intended result."
                  class="mt-1 block w-full rounded-2xl border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-rose-400 focus:ring-rose-400"
                />
              </div>
            </div>

            <div
              v-if="mode === 'technical'"
              class="rounded-3xl border border-slate-200 bg-slate-50/80 p-5"
            >
              <div class="flex items-start justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold text-slate-900">Technical detail</h3>
                  <p class="mt-1 text-sm text-slate-500">
                    Include developer-oriented notes only when they add signal.
                  </p>
                </div>
                <span class="rounded-full bg-slate-900 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-white">
                  Advanced
                </span>
              </div>

              <div class="mt-4 grid grid-cols-1 gap-4">
                <div>
                  <label class="block text-sm font-medium text-slate-700">Reproduction steps</label>
                  <textarea
                    v-model.trim="form.reproduction_steps"
                    rows="4"
                    placeholder="List exact steps, inputs, and conditions."
                    class="mt-1 block w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
                  />
                </div>
                <div>
                  <label class="block text-sm font-medium text-slate-700">Technical details</label>
                  <textarea
                    v-model.trim="form.technical_details"
                    rows="4"
                    placeholder="Observed internals, edge cases, or suspected failure mode."
                    class="mt-1 block w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
                  />
                </div>
                <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <div>
                    <label class="block text-sm font-medium text-slate-700">Console notes</label>
                    <textarea
                      v-model.trim="form.console_notes"
                      rows="4"
                      placeholder="Paste relevant console output."
                      class="mt-1 block w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
                    />
                  </div>
                  <div>
                    <label class="block text-sm font-medium text-slate-700">API notes</label>
                    <textarea
                      v-model.trim="form.api_notes"
                      rows="4"
                      placeholder="HTTP status, request payload, or response details."
                      class="mt-1 block w-full rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
                    />
                  </div>
                </div>
                <div>
                  <label class="block text-sm font-medium text-slate-700">Suspected subsystem</label>
                  <input
                    v-model.trim="form.suspected_subsystem"
                    type="text"
                    placeholder="e.g. session_routes, auth store, provenance view"
                    class="mt-1 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
                  />
                </div>
              </div>
            </div>

            <div class="flex flex-wrap items-center justify-end gap-3">
              <router-link
                to="/issues"
                class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </router-link>
              <button
                type="submit"
                :disabled="submitting"
                class="rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {{ submitting ? 'Submitting…' : 'Create Issue' }}
              </button>
            </div>
          </form>
        </section>

        <aside class="space-y-5">
          <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 class="text-sm font-semibold text-slate-900">Detected context</h2>
            <div class="mt-4 space-y-3 text-sm">
              <div>
                <p class="text-xs uppercase tracking-wide text-slate-500">Current page</p>
                <p class="mt-1 font-medium text-slate-900">{{ detectedPageLabel }}</p>
              </div>
              <div>
                <p class="text-xs uppercase tracking-wide text-slate-500">Route path</p>
                <p class="mt-1 font-mono text-xs text-slate-700 break-all">{{ form.route_path || 'Unavailable' }}</p>
              </div>
              <div>
                <p class="text-xs uppercase tracking-wide text-slate-500">Related entities</p>
                <p class="mt-1 text-slate-700">{{ relatedEntitySummary }}</p>
              </div>
              <div>
                <p class="text-xs uppercase tracking-wide text-slate-500">Application version</p>
                <p class="mt-1 font-medium text-slate-900">
                  v{{ appVersion.version || 'unknown' }}
                  <span class="text-xs font-normal text-slate-500">· {{ appVersion.timestamp || 'unknown' }}</span>
                </p>
              </div>
            </div>
          </section>

          <section class="rounded-3xl border border-slate-200 bg-slate-950 p-5 text-slate-100 shadow-sm">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-sm font-semibold">Captured context preview</h2>
              <span class="rounded-full border border-white/20 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-300">
                JSON
              </span>
            </div>
            <pre class="mt-4 max-h-[28rem] overflow-auto rounded-2xl bg-black/30 p-3 text-xs leading-5 text-slate-200">{{ contextPreview }}</pre>
          </section>
        </aside>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { clearIssueDraftContext, consumeIssueDraftContext } from '@/utils/issueDraft'
import issueService from '@/services/issue.service'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const authStore = useAuthStore()
const toast = useToast()

const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const mode = ref('simple')
const registry = ref({ pages: [], issue_types: [], reporter_impacts: [], app_version: {} })

const form = reactive({
  title: '',
  issue_type: 'general',
  reporter_impact: 'medium',
  page_key: '',
  page_label: '',
  route_name: null,
  route_path: null,
  current_url: null,
  public_description: '',
  expected_behavior: '',
  technical_details: '',
  reproduction_steps: '',
  console_notes: '',
  api_notes: '',
  suspected_subsystem: '',
  route_context: {},
  related_entity_ids: {},
  environment_context: {},
  user_context: {},
  capture_context: {},
})

const issueTypes = computed(() => registry.value.issue_types || [])
const reporterImpacts = computed(() => registry.value.reporter_impacts || [])
const appVersion = computed(() => registry.value.app_version || {})

const currentMatchedPage = computed(() => {
  const pages = registry.value.pages || []
  return pages.find((page) => {
    if (form.route_name && page.route_name === form.route_name) return true
    return Array.isArray(page.route_templates) && page.route_templates.some((template) => {
      if (!form.route_path) return false
      const pattern = String(template || '').replace(/:[A-Za-z0-9_]+/g, '[^/]+')
      return new RegExp(`^${pattern}$`).test(form.route_path)
    })
  }) || null
})

const pageOptions = computed(() => {
  const pages = Array.isArray(registry.value.pages) ? registry.value.pages : []
  const currentOption = currentMatchedPage.value && form.route_path
    ? {
        page_key: currentMatchedPage.value.page_key,
        label: `Current page: ${currentMatchedPage.value.label} (${form.route_path})`,
      }
    : null

  const remaining = pages
    .filter((page) => page.page_key !== currentOption?.page_key)
    .map((page) => ({
      page_key: page.page_key,
      label: `${page.label} · ${page.route_templates?.[0] || page.route_name || page.page_key}`,
    }))

  return currentOption ? [currentOption, ...remaining] : remaining
})

const selectedPage = computed(() => {
  return (registry.value.pages || []).find((page) => page.page_key === form.page_key) || currentMatchedPage.value
})

const detectedPageLabel = computed(() => {
  if (selectedPage.value?.label) return selectedPage.value.label
  if (form.route_name) return String(form.route_name)
  return 'Unresolved page'
})

const relatedEntitySummary = computed(() => {
  const entries = Object.entries(form.related_entity_ids || {})
  if (!entries.length) return 'No explicit route entities detected'
  return entries.map(([key, value]) => `${key}: ${value}`).join(' · ')
})

const contextPreview = computed(() => {
  const preview = {
    route_name: form.route_name,
    route_path: form.route_path,
    current_url: form.current_url,
    route_context: form.route_context,
    related_entity_ids: form.related_entity_ids,
    environment_context: form.environment_context,
    user_context: form.user_context,
    capture_context: form.capture_context,
  }
  return JSON.stringify(preview, null, 2)
})

function hydratePageSelection() {
  if (selectedPage.value?.page_key) {
    form.page_key = selectedPage.value.page_key
    form.page_label = selectedPage.value.label
  }
}

function applyInitialContext() {
  const initialContext = consumeIssueDraftContext() || {}
  form.route_name = initialContext.route_name || null
  form.route_path = initialContext.route_path || null
  form.current_url = initialContext.current_url || null
  form.route_context = initialContext.route_context || {}
  form.related_entity_ids = initialContext.related_entity_ids || {}
  form.environment_context = initialContext.environment_context || {}
  form.user_context = initialContext.user_context || {
    reporter_id: authStore.user?.id || null,
    reporter_email: authStore.user?.email || null,
    reporter_role: authStore.user?.role || 'user',
    reporter_groups: Array.isArray(authStore.user?.groups) ? authStore.user.groups : [],
    reporter_capabilities: Array.isArray(authStore.user?.capabilities) ? authStore.user.capabilities : [],
  }
  form.capture_context = initialContext.capture_context || {}
}

function mergeVersionIntoContext() {
  form.environment_context = {
    ...(form.environment_context || {}),
    app_version: appVersion.value || {},
  }
  form.capture_context = {
    ...(form.capture_context || {}),
    reported_from: 'issue_report_view',
    registry_version: registry.value?.version || 1,
  }
}

async function loadRegistry() {
  loading.value = true
  error.value = ''
  try {
    const response = await issueService.getRegistry()
    registry.value = response.data || registry.value
    hydratePageSelection()
    mergeVersionIntoContext()
  } catch (err) {
    console.error('Failed to load issue registry:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load issue registry.'
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  submitting.value = true
  error.value = ''
  if (selectedPage.value?.label) {
    form.page_label = selectedPage.value.label
  }

  try {
    const response = await issueService.createIssue({
      title: form.title,
      issue_type: form.issue_type,
      reporter_impact: form.reporter_impact,
      page_key: form.page_key,
      page_label: form.page_label,
      route_name: form.route_name,
      route_path: form.route_path,
      current_url: form.current_url,
      public_description: form.public_description,
      expected_behavior: form.expected_behavior,
      technical_details: form.technical_details,
      reproduction_steps: form.reproduction_steps,
      console_notes: form.console_notes,
      api_notes: form.api_notes,
      suspected_subsystem: form.suspected_subsystem,
      route_context: form.route_context,
      related_entity_ids: form.related_entity_ids,
      environment_context: form.environment_context,
      user_context: form.user_context,
      capture_context: form.capture_context,
    })
    const issueId = response.data?.issue?.id
    clearIssueDraftContext()
    toast.success('Issue created successfully')
    if (issueId) {
      router.push(`/issues/${issueId}`)
    } else {
      router.push('/issues')
    }
  } catch (err) {
    console.error('Failed to create issue:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to create issue.'
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  applyInitialContext()
  await loadRegistry()
})
</script>
