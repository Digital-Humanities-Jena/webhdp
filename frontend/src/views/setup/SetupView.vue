<template>
  <div class="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
    <div class="sm:mx-auto sm:w-full sm:max-w-md">
      <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">
        WebHDP Setup Wizard
      </h2>
      <p class="mt-2 text-center text-sm text-gray-600">
        Bootstrap the first administrator, then continue with operational readiness after login.
      </p>
      <p class="mt-2 text-center text-sm">
        <router-link to="/docs" class="font-medium text-sky-600 hover:text-sky-500">
          Open Documentation Center
        </router-link>
      </p>
      <div class="mt-4">
        <LegalLinks />
      </div>
    </div>

    <div class="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
      <div class="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">

        <!-- Step 1: Welcome -->
        <div v-if="step === 1">
          <h3 class="text-lg leading-6 font-medium text-gray-900">Welcome</h3>
          <p class="mt-2 text-sm text-gray-500">
            It looks like this is your first time running WebHDP, or the system has been reset.
            We will detect the deployment mode, run lightweight checks, and create the first administrator.
          </p>
          <div class="mt-6">
            <button
              @click="step = 2; runChecks()"
              data-testid="setup-start"
              class="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
            >
              Start Setup
            </button>
          </div>
        </div>

        <!-- Step 2: System Checks -->
        <div v-if="step === 2">
          <h3 class="text-lg leading-6 font-medium text-gray-900 mb-4">System Checks</h3>

          <div v-if="setupGuidance" class="mb-5 rounded-lg border border-indigo-100 bg-indigo-50 p-4">
            <p class="text-xs font-semibold uppercase tracking-wide text-indigo-700">Detected mode</p>
            <p class="mt-1 text-sm font-semibold text-gray-900" data-testid="setup-deployment-mode">
              {{ setupGuidance.deployment_label }} · {{ setupGuidance.storage_mode }}
            </p>
            <p class="mt-2 text-xs text-gray-600">
              Mandatory operational items are summarized here. Full storage, compute, MFA, backup, and observability setup continues after admin login.
            </p>
          </div>

          <ul class="space-y-4">
            <li class="flex items-center justify-between">
              <span class="text-sm text-gray-400">Blender Availability</span>
              <span v-if="checks.blender === 'pending'" class="text-gray-400">Checking...</span>
              <span v-else-if="checks.blender === true" class="text-green-600">✓ Detected</span>
              <span v-else class="text-gray-400">Skipped</span>
            </li>
            <li class="flex items-center justify-between">
              <span class="text-sm text-gray-700">Fast Renderer Service</span>
              <span v-if="checks.renderer === 'pending'" class="text-gray-400">Checking...</span>
              <span v-else-if="checks.renderer === true" class="text-green-600">✓ Reachable</span>
              <span v-else class="text-amber-600">(!) Not Available (Resources Restricted)</span>
            </li>
            <li class="flex items-center justify-between">
              <span class="text-sm text-gray-700">Zenodo Sandbox (Env)</span>
              <span v-if="checks.zenodoSandbox === 'pending'" class="text-gray-400">Checking...</span>
              <span v-else-if="checks.zenodoSandbox === 'Reachable'" class="text-green-600">✓ Reachable</span>
              <span v-else-if="checks.zenodoSandbox === 'Not Configured'" class="text-yellow-600">Not Configured</span>
              <span v-else class="text-red-600">✗ {{ checks.zenodoSandbox }}</span>
            </li>
            <li class="flex items-center justify-between">
              <span class="text-sm text-gray-700">Zenodo Production (Env)</span>
              <span v-if="checks.zenodoProduction === 'pending'" class="text-gray-400">Checking...</span>
              <span v-else-if="checks.zenodoProduction === 'Reachable'" class="text-green-600">✓ Reachable</span>
              <span v-else-if="checks.zenodoProduction === 'Not Configured'" class="text-yellow-600">Not Configured</span>
              <span v-else class="text-red-600">✗ {{ checks.zenodoProduction }}</span>
            </li>
          </ul>

          <div v-if="checkError" class="mt-4 p-2 bg-red-50 text-red-700 text-sm rounded">
            {{ checkError }}
          </div>

          <div v-if="mandatoryPreview.length" class="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3">
            <p class="text-sm font-semibold text-amber-900">Mandatory readiness items after login</p>
            <ul class="mt-2 space-y-1 text-xs text-amber-800">
              <li v-for="item in mandatoryPreview" :key="item.id">
                {{ item.label }}: {{ item.message }}
              </li>
            </ul>
          </div>

          <div class="mt-6">
            <button
              v-if="checks.renderer === true"
              @click="step = 3; startRenderTest()"
              class="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700"
            >
              Next: Test Rendering
            </button>
            <button
              v-else-if="!checking"
              @click="step = 4"
              data-testid="setup-skip-rendering"
              class="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-amber-600 hover:bg-amber-700"
            >
              Skip Rendering (Service Unavailable)
            </button>
          </div>
        </div>

        <!-- Step 3: Rendering -->
        <div v-if="step === 3">
          <h3 class="text-lg leading-6 font-medium text-gray-900 mb-4">Rendering Pipeline</h3>

          <div v-if="rendering" class="p-4 bg-indigo-50 border-l-4 border-indigo-400 rounded-r-lg mb-6">
            <p class="text-sm text-indigo-700">Running a small local render test...</p>
          </div>

          <div v-else-if="renderResult" class="p-4 bg-green-50 border-l-4 border-green-400 rounded-r-lg mb-6">
            <p class="text-sm text-green-700">
              <span class="font-bold">Rendering available:</span> The local renderer completed the setup test.
            </p>
          </div>

          <div v-else class="p-4 bg-amber-50 border-l-4 border-amber-400 rounded-r-lg mb-6">
            <div class="flex">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-amber-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="ml-3">
                <p class="text-sm text-amber-700">
                  <span class="font-bold">Rendering not confirmed:</span> Continue setup and review compute runtime guidance after administrator login.
                </p>
              </div>
            </div>
          </div>

          <div v-if="renderError" class="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">
            {{ renderError }}
          </div>

          <p class="text-sm text-gray-500 mb-6">
            The core platform bootstrap can continue. Operational compute policy is reviewed in the administrator readiness checklist.
          </p>

          <div class="mt-6 flex justify-between">
             <button
              @click="step = 2"
              class="py-2 px-4 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50"
            >
              Back
            </button>
            <button
              @click="step = 4"
              :disabled="rendering"
              class="ml-3 inline-flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700"
            >
              Next: Create Admin
            </button>
          </div>
        </div>

        <!-- Step 4: Admin Account -->
        <div v-if="step === 4">
          <h3 class="text-lg leading-6 font-medium text-gray-900 mb-4">Create Admin Account</h3>
          <form @submit.prevent="handleCreateAdmin">
            <div class="space-y-4">
              <div>
                <label for="email" class="block text-sm font-medium text-gray-700">Email address</label>
                <div class="mt-1">
                  <input v-model="adminForm.email" id="email" data-testid="setup-admin-email" name="email" type="email" autocomplete="email" required class="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm" />
                </div>
              </div>

              <div>
                <label for="password" class="block text-sm font-medium text-gray-700">Password</label>
                <div class="mt-1">
                  <input v-model="adminForm.password" id="password" data-testid="setup-admin-password" name="password" type="password" required class="appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm" />
                </div>
              </div>

              <div v-if="adminError" class="text-red-600 text-sm">
                {{ adminError }}
              </div>

              <div class="flex justify-between mt-4">
                 <button type="button" @click="step = 3" class="py-2 px-4 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50">Back</button>
                 <button type="submit" :disabled="creatingAdmin" data-testid="setup-finish" class="ml-3 inline-flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50">
                    {{ creatingAdmin ? 'Creating...' : 'Finish Setup' }}
                 </button>
              </div>
            </div>
          </form>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useSystemStore } from '@/stores/system'
import LegalLinks from '@/components/legal/LegalLinks.vue'

const router = useRouter()
const systemStore = useSystemStore()

const step = ref(1)
const checking = ref(false)
const rendering = ref(false)
const checkError = ref('')
const renderError = ref('')
const renderResult = ref(null)
const setupGuidance = ref(null)

// Step 2 Data
const checks = reactive({
  blender: 'pending',
  renderer: 'pending',
  zenodoSandbox: 'pending',
  zenodoProduction: 'pending'
})

const mandatoryPreview = computed(() => {
  return (setupGuidance.value?.checklist || [])
    .filter((item) => item.required_level === 'Mandatory' && item.status !== 'complete')
    .slice(0, 4)
})

// Step 4 Data
const adminForm = reactive({ email: '', password: '' })
const creatingAdmin = ref(false)
const adminError = ref('')

const runChecks = async () => {
  checking.value = true
  checkError.value = ''
  checks.blender = 'pending'
  checks.renderer = 'pending'
  checks.zenodoSandbox = 'pending'
  checks.zenodoProduction = 'pending'

  try {
    const response = await systemStore.checkHealth()
    const data = response.data

    // Only mark as reachable if both enabled and reachable
    checks.renderer = data.renderer_enabled && data.blender_reachable
    checks.blender = data.blender_reachable
    checks.zenodoSandbox = data.zenodo_sandbox_status
    checks.zenodoProduction = data.zenodo_production_status
    setupGuidance.value = data.setup_guidance || null

  } catch (err) {
    console.error(err)
    checkError.value = err.message || "Failed to connect to backend check service."
    checks.renderer = false
    checks.blender = false
    checks.zenodoSandbox = "Error"
    checks.zenodoProduction = "Error"
    setupGuidance.value = null
  } finally {
    checking.value = false
  }
}

const startRenderTest = async () => {
  rendering.value = true
  renderError.value = ''
  renderResult.value = null

  try {
    const response = await systemStore.testRender()
    const data = response.data

    if (data.success) {
      renderResult.value = data
    } else {
      throw new Error("Render reported failure.")
    }
  } catch (err) {
    console.error(err)
    renderError.value = err.response?.data?.error || err.message || "Render failed."
  } finally {
    rendering.value = false
  }
}

const handleCreateAdmin = async () => {
  creatingAdmin.value = true
  adminError.value = ''
  try {
    await systemStore.createAdmin({ ...adminForm })
    await finishSetup()
  } catch (err) {
    adminError.value = err.response?.data?.error?.message || err.message || "Failed to create admin"
  } finally {
    creatingAdmin.value = false
  }
}

const finishSetup = async () => {
  try {
    await systemStore.completeSetup()
    await router.push('/login')
  } catch (err) {
    alert("Failed to complete setup: " + err.message)
  }
}
</script>
