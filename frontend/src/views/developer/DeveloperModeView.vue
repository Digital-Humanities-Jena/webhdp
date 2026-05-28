<template>
  <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
    <div class="mb-6">
      <p class="text-xs font-semibold uppercase tracking-wide text-indigo-600">Developer Mode</p>
      <h1 class="mt-1 text-2xl font-bold text-gray-900">Onboarding Diagnostics</h1>
      <p class="mt-2 max-w-3xl text-sm text-gray-600">
        Read-only development context for contributors. This page exposes commands, documentation links,
        feature flags, and non-secret runtime state.
      </p>
    </div>

    <LoadingSpinner v-if="isLoading" text="Loading developer diagnostics" />
    <Alert v-else-if="errorMessage" type="error" :message="errorMessage" />

    <div v-else-if="status" class="space-y-6">
      <section class="grid gap-4 md:grid-cols-3">
        <div class="rounded-md border border-gray-200 bg-white p-4">
          <p class="text-xs font-semibold uppercase tracking-wide text-gray-500">Version</p>
          <p class="mt-2 text-lg font-semibold text-gray-900">{{ status.version?.version || 'Unknown' }}</p>
          <p class="mt-1 text-xs text-gray-500">{{ status.version?.timestamp || 'No timestamp' }}</p>
        </div>
        <div class="rounded-md border border-gray-200 bg-white p-4">
          <p class="text-xs font-semibold uppercase tracking-wide text-gray-500">Runtime</p>
          <p class="mt-2 text-lg font-semibold text-gray-900">{{ status.runtime?.flask_env || 'development' }}</p>
          <p class="mt-1 text-xs text-gray-500">Storage: {{ status.runtime?.storage_mode || 'unknown' }}</p>
        </div>
        <div class="rounded-md border border-gray-200 bg-white p-4">
          <p class="text-xs font-semibold uppercase tracking-wide text-gray-500">API Contract</p>
          <p :class="['mt-2 text-lg font-semibold', status.api_contract?.exists ? 'text-emerald-700' : 'text-amber-700']">
            {{ status.api_contract?.exists ? 'Generated' : 'Missing' }}
          </p>
          <code class="mt-1 block text-xs text-gray-500">{{ status.api_contract?.regenerate_command }}</code>
        </div>
      </section>

      <section class="rounded-md border border-gray-200 bg-white">
        <div class="border-b border-gray-200 px-4 py-3">
          <h2 class="text-sm font-semibold text-gray-900">Contributor Commands</h2>
        </div>
        <div class="divide-y divide-gray-100">
          <div v-for="item in status.commands" :key="item.command" class="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <span class="text-sm text-gray-700">{{ item.label }}</span>
            <code class="rounded bg-gray-100 px-2 py-1 text-xs text-gray-800">{{ item.command }}</code>
          </div>
        </div>
      </section>

      <section class="rounded-md border border-gray-200 bg-white">
        <div class="border-b border-gray-200 px-4 py-3">
          <h2 class="text-sm font-semibold text-gray-900">Developer Documentation</h2>
        </div>
        <div class="grid gap-3 p-4 md:grid-cols-2">
          <router-link
            v-for="doc in status.docs"
            :key="doc.path"
            :to="doc.path"
            class="rounded-md border border-gray-200 p-3 text-sm transition hover:border-indigo-200 hover:bg-indigo-50"
          >
            <span class="font-medium text-gray-900">{{ doc.label }}</span>
            <span :class="['ml-2 text-xs', doc.exists ? 'text-emerald-600' : 'text-amber-600']">
              {{ doc.exists ? 'available' : 'missing' }}
            </span>
            <code class="mt-1 block text-xs text-gray-500">{{ doc.file }}</code>
          </router-link>
        </div>
      </section>

      <section class="grid gap-6 lg:grid-cols-2">
        <div class="rounded-md border border-gray-200 bg-white">
          <div class="border-b border-gray-200 px-4 py-3">
            <h2 class="text-sm font-semibold text-gray-900">Feature Flags</h2>
          </div>
          <dl class="divide-y divide-gray-100">
            <div v-for="(value, key) in status.feature_flags" :key="key" class="flex items-center justify-between px-4 py-3">
              <dt class="text-sm text-gray-700">{{ formatKey(key) }}</dt>
              <dd :class="['text-sm font-semibold', value ? 'text-emerald-700' : 'text-gray-500']">{{ value ? 'on' : 'off' }}</dd>
            </div>
          </dl>
        </div>

        <div class="rounded-md border border-gray-200 bg-white">
          <div class="border-b border-gray-200 px-4 py-3">
            <h2 class="text-sm font-semibold text-gray-900">Current Developer Access</h2>
          </div>
          <dl class="divide-y divide-gray-100">
            <div class="flex items-center justify-between px-4 py-3">
              <dt class="text-sm text-gray-700">Role</dt>
              <dd class="text-sm font-semibold text-gray-900">{{ status.user?.role }}</dd>
            </div>
            <div class="px-4 py-3">
              <dt class="text-sm text-gray-700">Capabilities</dt>
              <dd class="mt-2 flex flex-wrap gap-2">
                <span v-for="capability in status.user?.capabilities || []" :key="capability" class="rounded bg-gray-100 px-2 py-1 text-xs text-gray-700">
                  {{ capability }}
                </span>
                <span v-if="!(status.user?.capabilities || []).length" class="text-xs text-gray-500">None</span>
              </dd>
            </div>
          </dl>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'

import Alert from '@/components/ui/Alert.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import developerService from '@/services/developer.service'

const isLoading = ref(false)
const errorMessage = ref('')
const status = ref(null)

const formatKey = (key) => String(key || '').replaceAll('_', ' ')

async function loadStatus() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const response = await developerService.getStatus()
    status.value = response.data
  } catch (error) {
    errorMessage.value = error?.error?.message || error?.message || 'Unable to load developer diagnostics.'
  } finally {
    isLoading.value = false
  }
}

onMounted(loadStatus)
</script>
