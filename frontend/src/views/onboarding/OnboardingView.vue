<template>
  <div class="min-h-screen bg-gray-50">
    <div class="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
      <section class="rounded-xl border border-gray-200 bg-white shadow-sm">
        <div class="border-b border-gray-200 px-6 py-5">
          <p class="text-xs font-semibold uppercase tracking-wide text-indigo-700">First Steps</p>
          <h1 class="mt-2 text-2xl font-semibold text-gray-900">Set up your WebHDP workspace</h1>
          <p class="mt-2 max-w-3xl text-sm text-gray-600">
            Start by uploading a model, then review files, add descriptions and choose processing. Account details, Zenodo keys and HPC access can be prepared here when you need them.
          </p>
        </div>

        <div class="grid gap-4 p-6 md:grid-cols-3">
          <article v-for="step in steps" :key="step.id" class="rounded-lg border border-gray-200 bg-gray-50 p-4">
            <div class="flex items-start justify-between gap-3">
              <div>
                <h2 class="text-sm font-semibold text-gray-900">{{ step.title }}</h2>
                <p class="mt-2 text-sm text-gray-600">{{ step.body }}</p>
              </div>
              <span
                class="rounded-full px-2.5 py-1 text-xs font-medium"
                :class="step.complete ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-700'"
              >
                {{ step.status }}
              </span>
            </div>
            <router-link
              :to="step.to"
              class="mt-4 inline-flex rounded-md border border-indigo-200 px-3 py-2 text-xs font-medium text-indigo-700 hover:bg-indigo-50"
            >
              {{ step.action }}
            </router-link>
          </article>
        </div>

        <div class="flex flex-wrap justify-end gap-3 border-t border-gray-200 px-6 py-4">
          <button
            type="button"
            class="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
            :disabled="saving"
            @click="finish('skip')"
          >
            Skip for now
          </button>
          <button
            type="button"
            class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
            :disabled="saving"
            @click="finish('complete')"
          >
            {{ saving ? 'Saving...' : 'Continue to upload' }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'

const authStore = useAuthStore()
const router = useRouter()
const toast = useToast()
const saving = ref(false)

const profileComplete = computed(() => Boolean(authStore.user?.full_name && authStore.user?.affiliation))
const zenodoComplete = computed(() => Boolean(authStore.user?.zenodo_credentials_configured))
const hpcSummary = computed(() => authStore.user?.hpc || {})
const hpcComplete = computed(() => Boolean(hpcSummary.value.has_access))

const steps = computed(() => [
  {
    id: 'profile',
    title: 'Account setup',
    body: profileComplete.value ? 'Your name and affiliation are available for forms and records.' : 'Add your full name and institutional affiliation.',
    action: profileComplete.value ? 'Review account' : 'Add profile details',
    to: '/account/configuration',
    complete: profileComplete.value,
    status: profileComplete.value ? 'Ready' : 'Optional',
  },
  {
    id: 'zenodo',
    title: 'Zenodo key',
    body: 'Needed when a pipeline creates or uploads Zenodo drafts. Sandbox and Production use separate keys; your institution may provide access.',
    action: 'Open Zenodo keys',
    to: '/account/configuration',
    complete: zenodoComplete.value,
    status: zenodoComplete.value ? 'Configured' : 'Before processing',
  },
  {
    id: 'hpc',
    title: 'HPC resources',
    body: hpcSummary.value.has_access ? 'HPC access is enabled for this account.' : (hpcSummary.value.latest_request?.status === 'pending' ? 'Your request is awaiting approval. You can prepare files and metadata while you wait.' : 'Request access to remote computing for rendering. Approval lets you request compute time; it does not start a rendering job.'),
    action: 'Open HPC access',
    to: '/hpc-resources',
    complete: hpcComplete.value,
    status: hpcComplete.value ? 'Access enabled' : hpcSummary.value.latest_request?.status === 'pending' ? 'Awaiting approval' : hpcSummary.value.latest_request?.status === 'rejected' ? 'Not approved' : 'For rendering',
  },
])

const finish = async (action) => {
  saving.value = true
  try {
    await authStore.updateOnboarding(action)
    toast.success(action === 'skip' ? 'First steps skipped' : 'First steps completed')
    router.push('/workflow/upload')
  } catch (error) {
    toast.error(error?.error?.message || error?.message || 'Could not update onboarding')
  } finally {
    saving.value = false
  }
}
</script>
