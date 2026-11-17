<template>
  <div class="min-h-screen bg-gray-50">
    <div class="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
      <section class="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div class="border-b border-gray-200 px-6 py-5">
          <p class="text-xs font-semibold uppercase tracking-wide text-indigo-700">HPC Resources</p>
          <h1 class="mt-2 text-2xl font-semibold text-gray-900">Request HPC access</h1>
          <p class="mt-2 max-w-3xl text-sm text-gray-600">
            HPC access is reviewed by an administrator before it is enabled for workflow allocations.
          </p>
        </div>

        <div v-if="loading" class="p-6 text-sm text-gray-500">Loading HPC request status...</div>
        <div v-else class="grid gap-6 p-6 lg:grid-cols-[1fr_22rem]">
          <div v-if="hasAccess" class="rounded-lg border border-emerald-200 bg-emerald-50 p-5">
            <p class="text-sm font-semibold text-emerald-900">HPC access is enabled</p>
            <p class="mt-2 text-sm text-emerald-800">
              This account already has HPC access. The request form is locked while access remains active.
            </p>
          </div>

          <form v-else class="space-y-4" @submit.prevent="submit">
            <div class="grid gap-4 md:grid-cols-2">
              <label class="block text-sm font-medium text-gray-700">
                Full name
                <input v-model.trim="form.full_name" type="text" required class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
              </label>
              <label class="block text-sm font-medium text-gray-700">
                Institutional affiliation
                <input v-model.trim="form.affiliation" type="text" required class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm" />
              </label>
            </div>

            <fieldset class="rounded-lg border border-gray-200 p-4">
              <legend class="px-1 text-sm font-medium text-gray-700">Use cases</legend>
              <div class="mt-2 grid gap-3 sm:grid-cols-2">
                <label v-for="useCase in useCases" :key="useCase" class="inline-flex items-center gap-2 text-sm text-gray-700">
                  <input
                    v-model="form.use_cases"
                    type="checkbox"
                    :value="useCase"
                    class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  {{ useCase }}
                </label>
              </div>
            </fieldset>

            <label class="block text-sm font-medium text-gray-700">
              Notes
              <textarea v-model.trim="form.notes" rows="4" class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm"></textarea>
            </label>

            <div class="flex justify-end">
              <button
                type="submit"
                :disabled="submitting || !canSubmit"
                class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {{ submitting ? 'Submitting...' : 'Submit request' }}
              </button>
            </div>
          </form>

          <aside class="rounded-lg border border-gray-200 bg-gray-50 p-4">
            <h2 class="text-sm font-semibold text-gray-900">Current status</h2>
            <p class="mt-3 text-sm text-gray-700">
              <span class="font-medium">Access:</span>
              {{ status?.hpc?.has_access ? 'Enabled' : 'Not enabled' }}
            </p>
            <div v-if="latestRequest" class="mt-4 space-y-2 text-sm text-gray-700">
              <p><span class="font-medium">Latest request:</span> {{ latestRequest.status }}</p>
              <p><span class="font-medium">Submitted:</span> {{ formatDate(latestRequest.submitted_at) }}</p>
              <p v-if="latestRequest.review_comment"><span class="font-medium">Review note:</span> {{ latestRequest.review_comment }}</p>
            </div>
            <p v-else class="mt-4 text-sm text-gray-500">No HPC resources request has been submitted yet.</p>
          </aside>
        </div>
      </section>
      <ReservedGpuAccess v-if="!loading && hasAccess" select-session class="mt-6" />
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import hpcResourceRequestService from '@/services/hpcResourceRequest.service'
import { useToast } from '@/composables/useToast'
import ReservedGpuAccess from '@/components/hpc/ReservedGpuAccess.vue'

const toast = useToast()
const loading = ref(true)
const submitting = ref(false)
const status = ref(null)
const useCases = ref(['3D Models', 'Photographies', 'Historical Data', 'Documents', 'Other'])
const form = reactive({
  full_name: '',
  affiliation: '',
  use_cases: [],
  notes: '',
})

const latestRequest = computed(() => status.value?.hpc?.latest_request || null)
const hasAccess = computed(() => Boolean(status.value?.hpc?.has_access))
const canSubmit = computed(() => {
  return Boolean(!hasAccess.value && form.full_name && form.affiliation && form.use_cases.length && latestRequest.value?.status !== 'pending')
})

const formatDate = (value) => {
  if (!value) return 'N/A'
  return new Date(value).toLocaleString()
}

const loadStatus = async () => {
  loading.value = true
  try {
    const response = await hpcResourceRequestService.getMyStatus()
    status.value = response.data || {}
    useCases.value = response.data?.use_cases || useCases.value
    form.full_name = response.data?.profile_defaults?.full_name || ''
    form.affiliation = response.data?.profile_defaults?.affiliation || ''
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to load HPC status')
  } finally {
    loading.value = false
  }
}

const submit = async () => {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    await hpcResourceRequestService.submitRequest({
      full_name: form.full_name,
      affiliation: form.affiliation,
      use_cases: form.use_cases,
      notes: form.notes,
    })
    toast.success('HPC resources request submitted')
    await loadStatus()
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Failed to submit HPC request')
  } finally {
    submitting.value = false
  }
}

loadStatus()
</script>
