<template>
  <div class="min-h-screen bg-gray-50">
    <div class="mx-auto max-w-5xl space-y-6 px-4 py-8 sm:px-6 lg:px-8">
      <header>
        <h1 ref="pageHeading" tabindex="-1" class="text-3xl font-semibold text-gray-900 focus:outline-none">Get started with WebHDP</h1>
        <p class="mt-2 max-w-2xl text-sm leading-relaxed text-gray-700">
          WebHDP helps you prepare cultural heritage files, describe them, and run processing workflows.
        </p>
      </header>

      <section v-if="tourOpen" aria-labelledby="tour-step-title" class="rounded-xl border border-indigo-200 bg-white p-5 shadow-sm sm:p-7">
        <ol aria-label="Tour progress" class="mb-5 flex gap-2">
          <li v-for="(_, index) in tourSteps" :key="index" class="flex-1" :aria-current="stepIndex === index ? 'step' : undefined">
            <span class="block h-1 rounded-full" :class="stepIndex >= index ? 'bg-indigo-600' : 'bg-slate-200'" aria-hidden="true"></span>
            <span class="sr-only">{{ tourSteps[index].title }}</span>
          </li>
        </ol>
        <p class="text-sm font-medium text-indigo-700">Step {{ stepIndex + 1 }} of {{ tourSteps.length }}</p>
        <h2 id="tour-step-title" ref="stepHeading" tabindex="-1" class="mt-1 text-xl font-semibold text-gray-900 focus:outline-none" aria-describedby="tour-step-description">
          {{ currentStep.title }}
        </h2>
        <p id="tour-step-description" class="mt-2 max-w-3xl text-sm leading-relaxed text-gray-700">{{ currentStep.description }}</p>
        <dl class="mt-5 grid gap-3 sm:grid-cols-2">
          <div v-for="detail in currentStep.details" :key="detail.title" class="rounded-lg border border-gray-200 bg-gray-50 p-4">
            <dt class="text-sm font-semibold text-gray-900">{{ detail.title }}</dt>
            <dd class="mt-1 text-sm leading-relaxed text-gray-700">{{ detail.description }}</dd>
          </div>
        </dl>
        <div class="mt-6 flex flex-wrap items-center gap-3">
          <button v-if="stepIndex" type="button" :disabled="saving" class="secondary-action" @click="showStep(stepIndex - 1)">Back</button>
          <button v-if="stepIndex < tourSteps.length - 1" type="button" class="primary-action" @click="showStep(stepIndex + 1)">Next</button>
          <button v-else type="button" :disabled="saving" class="primary-action" @click="completeTour">{{ saving ? 'Saving…' : 'Finish tour' }}</button>
          <button type="button" :disabled="saving" class="secondary-action" @click="pauseTour">Pause tour</button>
          <button v-if="onboardingRequired" type="button" :disabled="saving" class="secondary-action" @click="enterWorkspace('/dashboard')">Skip for now</button>
        </div>
        <p v-if="saveError" class="mt-3 text-sm text-rose-700" role="alert">{{ saveError }}</p>
      </section>

      <div v-else class="space-y-6">
        <p v-if="tourFinished" role="status" class="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">Tour complete. Try the sample workflow to see the steps in action.</p>
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <section class="flex flex-col items-start rounded-xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6" aria-labelledby="intro-tour-title">
            <h2 id="intro-tour-title" class="text-lg font-semibold text-gray-900">Learn how WebHDP works</h2>
            <p class="mt-2 flex-1 text-sm leading-relaxed text-gray-700">A short tour of uploads, metadata, processing, and where to find your results.</p>
            <button ref="tourButton" type="button" class="primary-action mt-5" @click="showStep(savedStep ?? 0)">{{ tourButtonLabel }}</button>
          </section>
          <section class="flex flex-col items-start rounded-xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6" aria-labelledby="sample-tutorial-title">
            <h2 id="sample-tutorial-title" class="text-lg font-semibold text-gray-900">Try a 3D asset tutorial</h2>
            <p class="mt-2 flex-1 text-sm leading-relaxed text-gray-700">Use a sample model to check its metadata, run a pipeline, and download the results. You can repeat the tutorial at any time.</p>
            <router-link to="/tutorial/3d" class="primary-action mt-5">Start 3D tutorial</router-link>
          </section>
          <section class="flex flex-col items-start rounded-xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6" aria-labelledby="account-setup-title">
            <h2 id="account-setup-title" class="text-lg font-semibold text-gray-900">Set up your account</h2>
            <p class="mt-2 flex-1 text-sm leading-relaxed text-gray-700">Connect Zenodo, join an institution workspace, or request computing access. Use the steps that fit your work.</p>
            <router-link to="/account/setup" class="secondary-action mt-5">Open account setup</router-link>
          </section>
        </div>

        <section aria-labelledby="own-workspace-title" class="rounded-xl border border-gray-200 bg-white p-5 shadow-sm sm:p-6">
          <h2 id="own-workspace-title" class="text-lg font-semibold text-gray-900">Work with your own files</h2>
          <p class="mt-2 text-sm text-gray-700">Start a new upload or open your dashboard to find existing work.</p>
          <div class="mt-4 flex flex-wrap items-center gap-3">
            <button type="button" :disabled="saving" class="primary-action" @click="enterWorkspace('/workflow/upload')">Continue to upload</button>
            <button type="button" :disabled="saving" class="secondary-action" @click="enterWorkspace('/dashboard')">{{ onboardingRequired ? 'Skip for now' : 'Go to dashboard' }}</button>
          </div>
          <p v-if="saveError" class="mt-3 text-sm text-rose-700" role="alert">{{ saveError }}</p>
        </section>

      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const saving = ref(false)
const saveError = ref('')
const tourOpen = ref(false)
const tourFinished = ref(false)
const stepIndex = ref(0)
const savedStep = ref(null)
const pageHeading = ref(null)
const stepHeading = ref(null)
const tourButton = ref(null)

const tourSteps = [
  {
    title: 'Find your work',
    description: 'The dashboard brings together your recent work and gives you a starting point for a new upload.',
    details: [
      { title: 'Uploads', description: 'Find the files in your workspaces and resume an upload when you are ready.' },
      { title: 'Submissions', description: 'Follow processing, open the result, and review any items that need attention.' },
    ],
  },
  {
    title: 'Add files and describe your assets',
    description: 'A session is the workspace for an upload. It holds the source files, their descriptions, and the progress of your workflow.',
    details: [
      { title: 'One asset', description: 'Upload a self-contained model or image, then enter its title, creator, description, and rights.' },
      { title: 'Several assets', description: 'Use a metadata spreadsheet (MSF) to describe each asset. Its filename column connects each row to the correct source file.' },
    ],
  },
  {
    title: 'Choose how to process',
    description: 'A pipeline runs a series of steps. Each HDP Component performs one step, such as checking a model or generating a metadata file.',
    details: [
      { title: 'Check requirements', description: 'The pipeline lists its inputs, results, and any GPU requirement. Ask for HPC access if the workflow needs remote computing.' },
      { title: 'Follow progress', description: 'After reviewing readiness, start processing and follow the queue and step status from the submission.' },
    ],
  },
  {
    title: 'Review results and prepare a draft',
    description: 'Review what changed, then download the prepared files. For a publishing workflow, check the draft in the selected Zenodo environment.',
    details: [
      { title: 'Artifacts', description: 'These are the files the pipeline produces, such as a prepared model, a repair report, or linked metadata files.' },
      { title: 'Zenodo Sandbox', description: 'Use the Sandbox to review test drafts. For your own publishing workflows, select an available Zenodo credential for the chosen environment.' },
    ],
  },
]

const currentStep = computed(() => tourSteps[stepIndex.value])
const onboardingRequired = computed(() => Boolean(authStore.user?.onboarding_required))
const tourKey = computed(() => authStore.user?.id ? `webhdp:intro-tour:v1:${authStore.user.id}` : '')
const tourButtonLabel = computed(() => {
  if (savedStep.value !== null) return 'Continue the tour'
  return tourFinished.value || authStore.user?.onboarding_completed_at ? 'Replay the tour' : 'Take the tour'
})

function readSavedStep(key) {
  if (!key) return null
  try {
    const stored = window.localStorage.getItem(key)
    if (stored === null) return null
    const index = Number(stored)
    return Number.isInteger(index) && index >= 0 && index < tourSteps.length ? index : null
  } catch {
    return null
  }
}

function saveStep(index) {
  savedStep.value = index
  if (!tourKey.value) return
  try {
    if (index === null) window.localStorage.removeItem(tourKey.value)
    else window.localStorage.setItem(tourKey.value, String(index))
  } catch {
    // The tour is usable even when browser storage is unavailable.
  }
}

async function showStep(index) {
  stepIndex.value = index
  saveStep(index)
  tourOpen.value = true
  tourFinished.value = false
  saveError.value = ''
  await nextTick()
  stepHeading.value?.focus()
}

async function pauseTour() {
  tourOpen.value = false
  saveError.value = ''
  if (route.query.tour === '1') await router.replace({ query: { ...route.query, tour: undefined } })
  await nextTick()
  tourButton.value?.focus()
}

watch(tourKey, (key) => {
  savedStep.value = readSavedStep(key)
  tourOpen.value = false
  tourFinished.value = false
  saveError.value = ''
  if (route.query.tour === '1') showStep(savedStep.value ?? 0)
}, { immediate: true })

watch(() => route.query.tour, (value) => {
  if (value === '1') showStep(savedStep.value ?? 0)
})

async function saveOnboarding(action) {
  if (saving.value) return false
  saving.value = true
  saveError.value = ''
  try {
    if (onboardingRequired.value || (action === 'complete' && authStore.user?.role === 'user' && !authStore.user.onboarding_completed_at)) {
      await authStore.updateOnboarding(action)
    }
    return true
  } catch (error) {
    saveError.value = error?.error?.message || error?.message || 'Could not save your tour progress. Try again.'
    return false
  } finally {
    saving.value = false
  }
}

async function completeTour() {
  if (!await saveOnboarding('complete')) return
  saveStep(null)
  tourOpen.value = false
  tourFinished.value = true
  if (route.query.tour === '1') await router.replace({ query: { ...route.query, tour: undefined } })
  await nextTick()
  pageHeading.value?.focus()
}

async function enterWorkspace(destination) {
  if (!await saveOnboarding('skip')) return
  await router.push(destination)
}
</script>

<style scoped>
.primary-action {
  @apply inline-flex min-h-11 items-center rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:opacity-60;
}

.secondary-action {
  @apply inline-flex min-h-11 items-center rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:opacity-60;
}
</style>
