<template>
  <div class="min-h-screen bg-gray-50">
    <div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <header class="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-indigo-700">Administrator Setup</p>
          <h1 class="mt-2 text-2xl font-semibold text-gray-900">Operational Readiness</h1>
          <p class="mt-2 max-w-3xl text-sm text-gray-600">
            Mode-aware setup guidance for this WebHDP instance. Mandatory items should be resolved before users start real workflows.
          </p>
        </div>
        <button
          type="button"
          data-testid="readiness-refresh"
          class="inline-flex items-center justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          :disabled="loading"
          @click="loadGuidance"
        >
          <ArrowPathIcon class="mr-2 h-4 w-4" aria-hidden="true" />
          Refresh
        </button>
      </header>

      <div v-if="loading" class="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500 shadow-sm">
        Loading setup guidance...
      </div>

      <div v-else-if="error" class="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
        {{ error }}
      </div>

      <div v-else-if="guidance" class="space-y-6">
        <section class="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
          <div class="grid gap-4 md:grid-cols-4">
            <div>
              <p class="text-xs font-medium uppercase text-gray-500">Mode</p>
              <p class="mt-1 text-lg font-semibold text-gray-900" data-testid="readiness-mode">{{ guidance.deployment_label }}</p>
              <p class="text-xs text-gray-500">{{ guidance.deployment_mode }} / {{ guidance.deployment_class }}</p>
            </div>
            <div>
              <p class="text-xs font-medium uppercase text-gray-500">Storage</p>
              <p class="mt-1 text-lg font-semibold text-gray-900">{{ guidance.storage_mode }}</p>
            </div>
            <div>
              <p class="text-xs font-medium uppercase text-gray-500">Mandatory Open</p>
              <p class="mt-1 text-lg font-semibold" :class="mandatoryOpen ? 'text-rose-700' : 'text-emerald-700'">
                {{ mandatoryOpen }}
              </p>
            </div>
            <div>
              <p class="text-xs font-medium uppercase text-gray-500">Recommended Open</p>
              <p class="mt-1 text-lg font-semibold" :class="recommendedOpen ? 'text-amber-700' : 'text-emerald-700'">
                {{ recommendedOpen }}
              </p>
            </div>
          </div>
        </section>

        <section
          v-for="section in guidance.sections"
          :key="section.id"
          class="rounded-lg border border-gray-200 bg-white shadow-sm"
          :data-testid="`readiness-section-${section.id}`"
        >
          <div class="border-b border-gray-200 px-5 py-4">
            <h2 class="text-base font-semibold text-gray-900">{{ section.title }}</h2>
          </div>
          <div class="divide-y divide-gray-100">
            <article
              v-for="item in section.items"
              :key="item.id"
              class="grid gap-4 px-5 py-4 md:grid-cols-[minmax(0,1fr)_auto]"
              :data-testid="`readiness-item-${item.id}`"
            >
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <CheckCircleIcon v-if="item.status === 'complete'" class="h-5 w-5 text-emerald-600" aria-hidden="true" />
                  <ExclamationTriangleIcon v-else-if="item.severity === 'error'" class="h-5 w-5 text-rose-600" aria-hidden="true" />
                  <InformationCircleIcon v-else class="h-5 w-5 text-amber-600" aria-hidden="true" />
                  <h3 class="text-sm font-semibold text-gray-900">{{ item.label }}</h3>
                  <span
                    class="rounded-full px-2.5 py-1 text-xs font-semibold"
                    :class="levelClass(item.required_level)"
                    data-testid="readiness-required-level"
                  >
                    {{ item.required_level }}
                  </span>
                  <span
                    class="rounded-full px-2.5 py-1 text-xs font-semibold"
                    :class="statusClass(item)"
                  >
                    {{ statusLabel(item.status) }}
                  </span>
                </div>
                <p class="mt-2 text-sm text-gray-600">{{ item.message }}</p>
              </div>
              <div class="flex items-center md:justify-end">
                <router-link
                  v-if="item.route"
                  :to="item.route"
                  class="inline-flex items-center rounded-md border border-indigo-200 px-3 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-50"
                  data-testid="readiness-action"
                >
                  Open
                  <ArrowTopRightOnSquareIcon class="ml-2 h-4 w-4" aria-hidden="true" />
                </router-link>
              </div>
            </article>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  ArrowPathIcon,
  ArrowTopRightOnSquareIcon,
  CheckCircleIcon,
  ExclamationTriangleIcon,
  InformationCircleIcon,
} from '@heroicons/vue/24/outline'
import adminService from '@/services/admin.service'

const guidance = ref(null)
const loading = ref(true)
const error = ref('')

const mandatoryOpen = computed(() => guidance.value?.summary?.mandatory_open?.length || 0)
const recommendedOpen = computed(() => guidance.value?.summary?.recommended_open?.length || 0)

const statusLabel = (status) => {
  if (status === 'complete') return 'Complete'
  if (status === 'optional') return 'Optional'
  return 'Action needed'
}

const levelClass = (level) => {
  if (level === 'Mandatory') return 'bg-rose-100 text-rose-700'
  if (level === 'Recommended') return 'bg-amber-100 text-amber-800'
  return 'bg-sky-100 text-sky-700'
}

const statusClass = (item) => {
  if (item.status === 'complete') return 'bg-emerald-100 text-emerald-700'
  if (item.severity === 'error') return 'bg-rose-100 text-rose-700'
  if (item.severity === 'warning') return 'bg-amber-100 text-amber-800'
  return 'bg-gray-100 text-gray-700'
}

const loadGuidance = async () => {
  loading.value = true
  error.value = ''
  try {
    const response = await adminService.getSetupGuidance()
    guidance.value = response.data || null
  } catch (err) {
    error.value = err?.error?.message || err?.message || 'Could not load setup guidance.'
  } finally {
    loading.value = false
  }
}

onMounted(loadGuidance)
</script>
