<template>
  <div class="space-y-6">
    <section class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h2 class="text-xl font-semibold text-slate-900">HDP Component Installer</h2>
          <p class="mt-1 text-sm text-slate-600">Choose a component and where it will run, validate the exact package, then install and smoke-test it. Installed means registered; a passing smoke test confirms the test workload ran.</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="catalogLoading || actionBusy" @click="loadCatalog">
            {{ catalogLoading ? 'Loading...' : 'Refresh Catalog' }}
          </button>
          <button type="button" class="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="loadingInstallations" @click="loadInstallations">
            {{ loadingInstallations ? 'Refreshing...' : 'Refresh Installs' }}
          </button>
        </div>
      </div>

      <div v-if="!isEnabled" class="mt-4 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        Requires Admin role.
      </div>
    </section>

    <p class="text-sm text-slate-600">1. Choose package → 2. Validate → 3. Install → 4. Smoke test</p>
    <div v-if="actionError" role="alert" class="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{{ actionError }}</div>
    <div v-if="recovery" role="status" class="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm">
      Installation {{ recovery.id }} is being tracked. Closing this page does not stop the server operation.
      <button type="button" class="ml-2 font-medium underline" @click="reconnectInstallation">Reconnect</button>
      <button type="button" class="ml-2 font-medium underline" :disabled="installing" @click="retryInstallation">Retry same request</button>
    </div>
    <ProgressBar v-if="actionBusy" :label="validating ? 'Checking package and runtime…' : installing ? 'Installing component… This may take several minutes.' : 'Running the component smoke test…'" />
    <fieldset :disabled="actionBusy || !isEnabled" class="min-w-0 grid gap-6 xl:grid-cols-[minmax(0,1fr),24rem]">
      <div class="space-y-6">
        <div class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <div class="mb-5">
            <h3 class="text-lg font-semibold text-slate-900">Install Strategy</h3>
            <div class="mt-3 flex flex-wrap gap-2">
              <button type="button" :class="strategyClass('hpc_sif')" @click="setInstallStrategy('hpc_sif')">HPC SIF</button>
              <button type="button" :class="strategyClass('local_container')" @click="setInstallStrategy('local_container')">Local Docker</button>
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <button type="button" :class="modeClass('catalog')" @click="setMode('catalog')">Catalog</button>
            <button type="button" :class="modeClass('custom')" @click="setMode('custom')">Custom manifest</button>
          </div>

          <div v-if="mode === 'catalog'" class="mt-5 space-y-4">
            <div class="flex flex-wrap gap-2">
              <button type="button" :class="sourceClass('all')" @click="setCatalogSource('all')">All sources</button>
              <button type="button" :class="sourceClass('local')" @click="setCatalogSource('local')">Local catalog</button>
              <button type="button" :class="sourceClass('remote')" @click="setCatalogSource('remote')">Remote indexes</button>
            </div>
            <div class="grid gap-3 sm:grid-cols-2">
              <input aria-label="Search components" v-model.trim="catalogSearch" type="search" class="min-w-0 rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 sm:col-span-2" placeholder="Search components" />
              <select aria-label="Component category" v-model="catalogCategory" class="rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500">
                <option value="">All categories</option>
                <option v-for="category in catalogCategories" :key="category" :value="category">{{ category }}</option>
              </select>
              <select aria-label="Component tag" v-model="catalogTag" class="rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500">
                <option value="">All tags</option>
                <option v-for="tag in catalogTags" :key="tag" :value="tag">{{ tag }}</option>
              </select>
            </div>

            <div v-if="catalogWarnings.length" class="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
              {{ catalogWarnings.length }} catalog warning{{ catalogWarnings.length === 1 ? '' : 's' }}. Expand raw catalog details below for paths and messages.
            </div>

            <LoadingSpinner v-if="catalogLoading" text="Loading component catalog…" />
            <div v-else-if="catalogError" role="alert" class="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{{ catalogError }} <button type="button" class="font-semibold underline" @click="loadCatalog">Try again</button></div>
            <p v-if="diagnosticsError" role="status" class="text-sm text-amber-800">{{ diagnosticsError }}</p>
            <div v-if="!catalogLoading" class="grid gap-3 lg:grid-cols-2">
              <article
                v-for="component in filteredCatalog"
                :key="catalogKey(component)"
                class="rounded-md border p-4 transition hover:border-indigo-300"
                :class="selectedCatalogKey === catalogKey(component) ? 'border-indigo-500 bg-indigo-50' : 'border-slate-200 bg-white'"
              >
                <button type="button" class="w-full rounded text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500" :aria-pressed="selectedCatalogKey === catalogKey(component)" @click="selectCatalogComponent(component)">
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <p class="font-semibold text-slate-900">{{ component.label || component.component_key }}</p>
                    <p class="mt-1 text-xs text-slate-500">{{ component.component_key }} v{{ component.version }}</p>
                  </div>
                  <div class="flex flex-col items-end gap-1">
                    <span class="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">{{ installStrategyLabel(component.install_strategy || installStrategy) }}</span>
                    <span :class="trustClass(component.trust_level)" class="rounded-full px-2 py-0.5 text-xs font-semibold">{{ trustLabel(component.trust_level) }}</span>
                  </div>
                </div>
                <p class="mt-2 line-clamp-3 text-sm text-slate-600">{{ component.description || 'No description provided.' }}</p>
                <div class="mt-3 flex flex-wrap gap-1">
                  <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{{ catalogSourceLabel(component.catalog_source) }}</span>
                  <span class="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">{{ distributionTierLabel(component.distribution_tier) }}</span>
                  <span v-if="component.category" class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{{ component.category }}</span>
                  <span v-for="tag in component.tags || []" :key="tag" class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{{ tag }}</span>
                </div>
                </button>
                <div v-if="component.git?.url || component.zenodo?.doi || component.docker_digest || component.sif_sha256" class="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
                  <a v-if="component.git?.url" :href="component.git.url" target="_blank" rel="noreferrer" class="text-indigo-700 hover:text-indigo-900" @click.stop>Git</a>
                  <a v-if="component.zenodo?.record_url" :href="component.zenodo.record_url" target="_blank" rel="noreferrer" class="text-indigo-700 hover:text-indigo-900" @click.stop>Zenodo</a>
                  <span v-else-if="component.zenodo?.doi">DOI {{ component.zenodo.doi }}</span>
                  <span v-if="component.docker_digest">Docker digest</span>
                  <span v-if="component.sif_sha256">SIF checksum</span>
                </div>
              </article>
            </div>

            <p v-if="!catalogLoading && !catalogError && filteredCatalog.length === 0" class="rounded-md border border-slate-200 p-6 text-center text-sm text-slate-500">
              No matching installable components.
            </p>
          </div>

          <div v-else class="mt-5">
            <div class="mb-2 flex items-center justify-between">
              <label class="text-sm font-semibold text-slate-900">component.yaml</label>
              <label class="cursor-pointer rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">
                Upload YAML
                <input type="file" accept=".yaml,.yml,text/yaml,text/plain" class="hidden" @change="handleManifestUpload" />
              </label>
            </div>
            <textarea
              aria-label="Component manifest YAML" v-model="customManifestText"
              rows="18"
              class="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs text-slate-800 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              placeholder="Paste component.yaml"
              @input="clearActionResults"
            />
          </div>
        </div>

        <div class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h3 class="text-lg font-semibold text-slate-900">Manifest Review</h3>
          <div v-if="activeManifestText" class="mt-4 grid gap-4 lg:grid-cols-2">
            <div class="space-y-2 text-sm text-slate-700">
              <p><span class="font-medium">Component:</span> {{ activeComponentSummary.component_key || 'n/a' }}</p>
              <p><span class="font-medium">Version:</span> {{ activeComponentSummary.version || 'n/a' }}</p>
              <p><span class="font-medium">Category:</span> {{ activeComponentSummary.category || 'n/a' }}</p>
              <p><span class="font-medium">Distribution:</span> {{ distributionTierLabel(activeComponentSummary.distribution_tier) }}</p>
              <p><span class="font-medium">Profile:</span> {{ activeComponentSummary.profile_id || 'n/a' }}</p>
              <p><span class="font-medium">Strategy:</span> {{ installStrategyLabel(activeComponentSummary.install_strategy || installStrategy) }}</p>
              <p><span class="font-medium">Catalog:</span> {{ catalogSourceLabel(activeComponentSummary.catalog_source) }}</p>
              <p><span class="font-medium">Trust:</span> {{ trustLabel(activeComponentSummary.trust_level) }}</p>
              <p><span class="font-medium">Smoke test:</span> {{ activeComponentSummary.has_smoke_test ? 'Declared' : 'Not declared' }}</p>
              <p v-if="selectedCatalogComponent?.manifest_sha256" class="break-all"><span class="font-medium">Manifest SHA-256:</span> {{ selectedCatalogComponent.manifest_sha256 }}</p>
              <p v-if="selectedCatalogComponent?.source_path" class="break-all"><span class="font-medium">Source:</span> {{ selectedCatalogComponent.source_path }}</p>
              <p v-if="selectedCatalogComponent?.sif_sha256" class="break-all"><span class="font-medium">SIF SHA-256:</span> {{ selectedCatalogComponent.sif_sha256 }}</p>
              <p v-if="selectedCatalogComponent?.docker_digest" class="break-all"><span class="font-medium">Docker digest:</span> {{ selectedCatalogComponent.docker_digest }}</p>
            </div>
            <textarea :value="activeManifestText" readonly rows="12" class="w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700" />
          </div>
          <p v-else class="mt-4 text-sm text-slate-500">Select a catalog component or provide a custom manifest.</p>
        </div>

        <div class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          <h3 class="text-lg font-semibold text-slate-900">{{ sourceTitle }}</h3>
          <input
            :aria-label="sourceTitle" v-model.trim="sourceValue"
            type="text"
            class="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            :placeholder="sourcePlaceholder"
            @input="clearActionResults"
          />
          <input
            v-if="installStrategy === 'local_container'"
            v-model.trim="customDockerDigest"
            type="text"
            class="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            placeholder="Optional Docker digest, for example sha256:..."
            @input="clearActionResults"
          />
          <input
            v-else
            v-model.trim="customSifSha256"
            type="text"
            class="mt-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            placeholder="Optional SIF SHA-256 checksum"
            @input="clearActionResults"
          />
          <p class="mt-3 text-sm text-slate-600">{{ canInstall ? 'This exact package passed readiness checks. Install it, then run its smoke test.' : 'Validate after changing the manifest, runtime or source. Installation stays unavailable until readiness checks pass.' }}</p>
          <div class="mt-4 flex flex-wrap gap-3">
            <button type="button" class="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="!canValidate || validating || installing || testingId || !isEnabled" @click="validatePackage">
              {{ validating ? 'Validating...' : 'Validate Package' }}
            </button>
            <button type="button" class="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50" :disabled="Boolean(recovery) || !canInstall || installing || validating || testingId || !isEnabled" @click="installPackage">
              {{ installing ? 'Installing...' : installButtonLabel }}
            </button>
            <button v-if="latestInstallation" type="button" class="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="actionBusy || !isEnabled || latestInstallation.status !== 'installed'" @click="testInstallation(latestInstallation)">
              {{ testingId === latestInstallation.installation_id ? 'Testing...' : 'Run Smoke Test' }}
            </button>
          </div>
        </div>

        <ResultPanel title="Validation Details" :payload="validation" empty-text="No validation result yet." />
        <ResultPanel title="Install Details" :payload="installResult" empty-text="No install result yet." />
        <ResultPanel title="Smoke Test Details" :payload="testResult" empty-text="No smoke test result yet." />
      </div>

      <aside class="space-y-4">
        <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h3 class="text-sm font-semibold text-slate-900">Progress</h3>
          <div class="mt-4 space-y-3">
            <div v-for="step in progressSteps" :key="step.id" class="flex items-start gap-3">
              <span :class="stepClass(step.state)" class="mt-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full text-xs font-bold">{{ stepLabel(step.state) }}</span>
              <div>
                <p class="text-sm font-medium text-slate-900">{{ step.label }}</p>
                <p class="break-all text-xs text-slate-500">{{ step.detail }}</p>
              </div>
            </div>
          </div>
        </div>

        <div v-if="validation" class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <h3 class="text-sm font-semibold text-slate-900">Validation Checks</h3>
          <div class="mt-3 space-y-2 text-sm">
            <div v-for="check in validationChecks" :key="check.name" class="flex items-center justify-between gap-3">
              <span class="text-slate-700">{{ check.name }}<span v-if="check.message" class="block text-xs text-slate-500">{{ check.message }}</span></span>
              <span :class="check.success ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'" class="rounded-full px-2 py-0.5 text-xs font-semibold">
                {{ check.success ? 'passed' : 'warning' }}
              </span>
            </div>
            <p v-if="validation.duplicate" class="rounded-md border border-amber-200 bg-amber-50 p-2 text-amber-900">This component version is already registered or installing.</p>
          </div>
        </div>

        <details class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <summary class="cursor-pointer text-sm font-semibold text-slate-900">Raw Catalog Details</summary>
          <pre class="mt-3 max-h-80 overflow-auto rounded-md bg-slate-950 p-3 text-xs text-slate-100">{{ prettyJson({ summary: catalogSummary, warnings: catalogWarnings, diagnostics: indexDiagnostics }) }}</pre>
        </details>
      </aside>
    </fieldset>

    <section class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <h3 class="text-lg font-semibold text-slate-900">Installations</h3>
      <LoadingSpinner v-if="loadingInstallations" class="mt-4" text="Loading installation history…" />
      <p v-if="installationsError" role="alert" class="mt-3 text-sm text-rose-700">{{ installationsError }}</p>
      <div v-if="!loadingInstallations" class="mt-4 overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th class="px-3 py-2">Component</th>
              <th class="px-3 py-2">Strategy</th>
              <th class="px-3 py-2">Status</th>
              <th class="px-3 py-2">Source</th>
              <th class="px-3 py-2">Updated</th>
              <th class="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="item in installations" :key="item.installation_id">
              <td class="px-3 py-2 font-medium text-slate-900">{{ item.component_key }} v{{ item.version }}</td>
              <td class="px-3 py-2 text-slate-600">{{ installStrategyLabel(item.install_strategy) }}</td>
              <td class="px-3 py-2"><span :class="statusClass(item.status)" class="rounded-full px-2 py-0.5 text-xs font-semibold">{{ item.status }}</span></td>
              <td class="max-w-md truncate px-3 py-2 text-slate-600">{{ item.sif_remote_path || item.container_image || 'n/a' }}</td>
              <td class="px-3 py-2 text-slate-600">{{ formatDate(item.updated_at) }}</td>
              <td class="px-3 py-2 text-right">
                <button type="button" class="text-sm font-medium text-indigo-700 hover:text-indigo-900 disabled:opacity-50" :disabled="actionBusy || !isEnabled || item.status !== 'installed'" @click="testInstallation(item)">
                  {{ testingId === item.installation_id ? 'Testing...' : 'Test' }}
                </button>
              </td>
            </tr>
            <tr v-if="!installationsError && installations.length === 0">
              <td colspan="6" class="px-3 py-8 text-center text-slate-500">No installed components yet.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onBeforeUnmount, computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import toolsService from '@/services/tools.service'

const ResultPanel = defineComponent({
  props: {
    title: { type: String, required: true },
    payload: { type: Object, default: null },
    emptyText: { type: String, required: true },
  },
  setup(props) {
    return () => h('details', { class: 'rounded-lg border border-slate-200 bg-white p-6 shadow-sm' }, [
      h('summary', { class: 'cursor-pointer text-sm font-semibold text-slate-900' }, props.title),
      props.payload
        ? h('pre', { class: 'mt-4 max-h-96 overflow-auto rounded-md bg-slate-950 p-4 text-xs text-slate-100' }, JSON.stringify(props.payload, null, 2))
        : h('p', { class: 'mt-4 text-sm text-slate-500' }, props.emptyText),
    ])
  },
})

const { success, warning, error: showError } = useToast()

const isEnabled = ref(false)
const actionError = ref('')
const catalogError = ref('')
const installationsError = ref('')
const validatedPayload = ref('')
let catalogRequestId = 0
const actionBusy = computed(() => validating.value || installing.value || Boolean(testingId.value))
const authStore = useAuthStore()
const installStrategy = ref('hpc_sif')
const mode = ref('catalog')
const catalogSource = ref('all')
const catalog = ref([])
const catalogSummary = ref({ total: 0, installable: 0, warnings: [] })
const catalogLoading = ref(false)
const catalogSearch = ref('')
const catalogCategory = ref('')
const catalogTag = ref('')
const selectedCatalogKey = ref('')
const customManifestText = ref('')
const sifSource = ref('')
const containerImage = ref('')
const customSifSha256 = ref('')
const customDockerDigest = ref('')
const validation = ref(null)
const installResult = ref(null)
const testResult = ref(null)
const latestInstallation = ref(null)
const installations = ref([])
const validating = ref(false)
const installing = ref(false)
const loadingInstallations = ref(false)
const testingId = ref('')
const indexDiagnostics = ref(null)
const diagnosticsError = ref('')
const recovery = ref(null)
let recoveryTimer
let reconnecting = false
let disposed = false
const recoveryKey = () => `component-install:${authStore.user?.id || 'current'}`
function saveRecovery() { try { sessionStorage.setItem(recoveryKey(), JSON.stringify(recovery.value)) } catch { /* Current-page recovery remains available. */ } }
async function reconnectInstallation() {
  clearTimeout(recoveryTimer)
  if (!recovery.value || reconnecting) return
  const requestId = recovery.value.id
  reconnecting = true
  try {
    const response = await toolsService.getHdpComponentInstallation(requestId)
    if (disposed || recovery.value?.id !== requestId) return
    latestInstallation.value = response.data.installation
    if (latestInstallation.value.status === 'installed') {
      actionError.value = ''
      recovery.value = null
      saveRecovery()
      await loadInstallations()
    } else if (latestInstallation.value.status === 'failed') {
      actionError.value = latestInstallation.value.error || 'Installation failed. Review its details before retrying.'
      recovery.value = null
      saveRecovery()
    }
  } catch (err) { actionError.value = err?.error?.message || err?.message || 'Installation status is unavailable. Reconnect or retry the same request.' }
  finally { reconnecting = false }
  if (recovery.value && !disposed) recoveryTimer = setTimeout(reconnectInstallation, 5000)
}
onBeforeUnmount(() => { disposed = true; clearTimeout(recoveryTimer) })

const catalogWarnings = computed(() => catalogSummary.value?.warnings || [])
const catalogCategories = computed(() => sortedUnique(catalog.value.map((item) => item.category).filter(Boolean)))
const catalogTags = computed(() => sortedUnique(catalog.value.flatMap((item) => item.tags || [])))
const selectedCatalogComponent = computed(() => mode.value === 'catalog' ? (catalog.value.find((item) => catalogKey(item) === selectedCatalogKey.value) || null) : null)
const activeManifestText = computed(() => mode.value === 'catalog' ? (selectedCatalogComponent.value?.manifest_text || '') : customManifestText.value)
const sourceValue = computed({
  get() {
    return installStrategy.value === 'local_container' ? containerImage.value : sifSource.value
  },
  set(value) {
    if (installStrategy.value === 'local_container') {
      containerImage.value = value
    } else {
      sifSource.value = value
    }
  },
})
const sourceTitle = computed(() => installStrategy.value === 'local_container' ? 'Container Image' : 'SIF Source')
const sourcePlaceholder = computed(() => installStrategy.value === 'local_container' ? 'ghcr.io/hdp-components/component:1.0.0 or local-image:tag' : '/work/user/components/component.sif or https://.../component.sif')
const installButtonLabel = computed(() => installStrategy.value === 'local_container' ? 'Install Locally' : 'Install on HPC')
const canValidate = computed(() => Boolean(activeManifestText.value.trim() && sourceValue.value.trim()))
const readinessCheckKey = computed(() => installStrategy.value === 'local_container' ? 'local_container' : 'hpc_link')
const canInstall = computed(() => Boolean(validatedPayload.value === JSON.stringify(installPayload()) && validation.value && !validation.value.duplicate && validation.value.checks?.[readinessCheckKey.value]?.success === true))
const activeComponentSummary = computed(() => {
  const component = selectedCatalogComponent.value
  const metadata = component?.manifest?.metadata || {}
  return {
    component_key: component?.component_key || metadata.name || '',
    version: component?.version || metadata.version || '',
    category: component?.category || metadata.category || '',
    distribution_tier: component?.distribution_tier || component?.manifest?.distribution?.tier || 'external_installable',
    profile_id: component?.profile?.id || '',
    install_strategy: component?.install_strategy || installStrategy.value,
    catalog_source: component?.catalog_source || 'local',
    trust_level: component?.trust_level || '',
    has_smoke_test: Boolean(component?.has_smoke_test),
  }
})

const filteredCatalog = computed(() => {
  const search = catalogSearch.value.toLowerCase()
  return catalog.value.filter((item) => {
    const haystack = [
      item.component_key,
      item.label,
      item.description,
      item.category,
      ...(item.tags || []),
    ].join(' ').toLowerCase()
    if (search && !haystack.includes(search)) return false
    if (catalogCategory.value && item.category !== catalogCategory.value) return false
    if (catalogTag.value && !(item.tags || []).includes(catalogTag.value)) return false
    return true
  })
})

const validationChecks = computed(() => {
  const checks = validation.value?.checks || {}
  return Object.entries(checks).map(([name, value]) => ({
    name,
    success: value?.success === true,
    message: value?.error || value?.message || (value?.success === true ? '' : 'No passing result reported.'),
  }))
})

const progressSteps = computed(() => [
  {
    id: 'select',
    label: mode.value === 'catalog' ? 'Select component' : 'Provide manifest',
    detail: activeComponentSummary.value.component_key || 'Pending',
    state: activeManifestText.value.trim() ? 'passed' : 'pending',
  },
  {
    id: 'source',
    label: installStrategy.value === 'local_container' ? 'Provide Docker image' : 'Provide SIF source',
    detail: sourceValue.value || 'Pending',
    state: sourceValue.value ? 'passed' : 'pending',
  },
  {
    id: 'validate',
    label: 'Validate package',
    detail: validation.value?.component_key || 'Pending',
    state: validating.value ? 'running' : validation.value ? (validation.value.checks?.[readinessCheckKey.value]?.success === true ? 'passed' : 'warning') : 'pending',
  },
  {
    id: 'install',
    label: installStrategy.value === 'local_container' ? 'Install locally' : 'Install on HPC',
    detail: latestInstallation.value?.remote_install_dir || latestInstallation.value?.container_image || latestInstallation.value?.status || 'Pending',
    state: installing.value ? 'running' : latestInstallation.value?.status === 'installed' ? 'passed' : latestInstallation.value?.status === 'failed' ? 'failed' : 'pending',
  },
  {
    id: 'test',
    label: 'Smoke test',
    detail: testResult.value?.test?.remote_test_dir || testResult.value?.test?.status || 'Pending',
    state: testingId.value ? 'running' : testResult.value?.test?.status === 'skipped' ? 'warning' : testResult.value?.test?.success === true ? 'passed' : testResult.value?.test?.success === false ? 'failed' : 'pending',
  },
])

function sortedUnique(values) {
  return Array.from(new Set(values.map((item) => String(item || '').trim()).filter(Boolean))).sort()
}

function catalogKey(component) {
  return `${component.catalog_source || 'local'}:${component.install_strategy || installStrategy.value}:${component.component_key}:${component.version}`
}

function catalogContainerImage(component) {
  const strategy = (component?.install_strategies || []).find((item) => item?.id === 'local_container')
  return strategy?.image || component?.container_image || component?.artifacts?.docker?.image || component?.profile?.image || ''
}

function catalogSifSource(component) {
  return component?.sif_source || component?.artifacts?.sif?.source || ''
}

function syncSelectedCatalogSource(component) {
  if (installStrategy.value === 'local_container') {
    const image = catalogContainerImage(component)
    containerImage.value = image
    return
  }
  const sif = catalogSifSource(component)
  sifSource.value = sif
}

function modeClass(target) {
  return mode.value === target
    ? 'rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white'
    : 'rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50'
}

function strategyClass(target) {
  return installStrategy.value === target
    ? 'rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white'
    : 'rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50'
}

function sourceClass(target) {
  return catalogSource.value === target
    ? 'rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white'
    : 'rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50'
}

function installStrategyLabel(value) {
  return value === 'local_container' ? 'Local Docker' : 'HPC SIF'
}

function catalogSourceLabel(value) {
  if (value === 'remote_index') return 'Remote index'
  if (value === 'remote') return 'Remote index'
  return 'Local catalog'
}

function trustLabel(value) {
  if (value === 'trusted') return 'Trusted'
  if (value === 'community-reviewed') return 'Community reviewed'
  if (value === 'experimental') return 'Experimental'
  if (value === 'local') return 'Local'
  return 'Unrated'
}

function trustClass(value) {
  if (value === 'trusted') return 'bg-emerald-50 text-emerald-700'
  if (value === 'community-reviewed') return 'bg-sky-50 text-sky-700'
  if (value === 'experimental') return 'bg-amber-50 text-amber-700'
  return 'bg-slate-100 text-slate-600'
}

function distributionTierLabel(value) {
  if (value === 'core') return 'Core'
  if (value === 'bundled_example') return 'Bundled example'
  return 'External installable'
}

function stepClass(state) {
  if (state === 'passed') return 'bg-emerald-100 text-emerald-700'
  if (state === 'failed') return 'bg-rose-100 text-rose-700'
  if (state === 'warning') return 'bg-amber-100 text-amber-700'
  if (state === 'running') return 'bg-indigo-100 text-indigo-700'
  return 'bg-slate-100 text-slate-500'
}

function stepLabel(state) {
  if (state === 'passed') return '✓'
  if (state === 'failed') return '!'
  if (state === 'warning') return '!'
  if (state === 'running') return '…'
  return '•'
}

function statusClass(status) {
  if (status === 'installed') return 'bg-emerald-50 text-emerald-700'
  if (status === 'failed') return 'bg-rose-50 text-rose-700'
  return 'bg-amber-50 text-amber-700'
}

function formatDate(value) {
  if (!value) return 'n/a'
  return new Date(value).toLocaleString()
}

function prettyJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

function clearActionResults() {
  validatedPayload.value = ''
  actionError.value = ''
  validation.value = null
  installResult.value = null
  testResult.value = null
  latestInstallation.value = null
}

function setMode(nextMode) {
  if (actionBusy.value) return
  mode.value = nextMode
  clearActionResults()
}

async function setInstallStrategy(nextStrategy) {
  if (actionBusy.value) return
  if (installStrategy.value === nextStrategy) return
  installStrategy.value = nextStrategy
  selectedCatalogKey.value = ''
  clearActionResults()
  await loadCatalog()
}

async function setCatalogSource(nextSource) {
  if (actionBusy.value) return
  if (catalogSource.value === nextSource) return
  catalogSource.value = nextSource
  selectedCatalogKey.value = ''
  clearActionResults()
  await loadCatalog()
}

function selectCatalogComponent(component) {
  if (actionBusy.value) return
  selectedCatalogKey.value = catalogKey(component)
  syncSelectedCatalogSource(component)
  clearActionResults()
}

function installPayload() {
  const component = selectedCatalogComponent.value
  const payload = {
    manifest_text: activeManifestText.value,
    install_strategy: installStrategy.value,
    sif_source: sifSource.value,
    container_image: containerImage.value,
  }
  if (component) {
    Object.assign(payload, {
      catalog_ref: component.catalog_ref || null,
      catalog_source: component.catalog_source || '',
      trust_level: component.trust_level || '',
      git: component.git || {},
      release: component.release || {},
      zenodo: component.zenodo || {},
      compatibility: component.compatibility || {},
      license: component.license || null,
      citation: component.citation || null,
      sbom_url: component.sbom_url || '',
      provenance_url: component.provenance_url || '',
      docker_digest: component.docker_digest || component.artifacts?.docker?.digest || customDockerDigest.value || '',
      sif_sha256: component.sif_sha256 || component.artifacts?.sif?.sha256 || customSifSha256.value || '',
    })
  } else {
    payload.docker_digest = customDockerDigest.value || ''
    payload.sif_sha256 = customSifSha256.value || ''
  }
  return payload
}

async function handleManifestUpload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  customManifestText.value = await file.text()
  clearActionResults()
}

async function loadContext() {
  try {
    const response = await toolsService.getContext()
    isEnabled.value = !!response.data?.features?.hdp_component_installer?.enabled
  } catch (err) {
    isEnabled.value = false
  }
}

async function loadCatalog() {
  if (actionBusy.value) return
  const requestId = ++catalogRequestId
  catalogLoading.value = true
  catalogError.value = ''
  diagnosticsError.value = ''
  indexDiagnostics.value = null
  Promise.resolve().then(() => toolsService.getHdpComponentCatalogDiagnostics?.()).then(response => {
    if (requestId === catalogRequestId) indexDiagnostics.value = response?.data || null
  }).catch(() => {
    if (requestId === catalogRequestId) diagnosticsError.value = 'Catalog diagnostics are unavailable. You can still choose and validate a package.'
  })
  try {
    const response = await toolsService.listHdpComponentCatalog({ install_strategy: installStrategy.value, source: catalogSource.value })
    if (requestId !== catalogRequestId) return
    catalog.value = response.data?.components || []
    catalogSummary.value = response.data?.summary || { total: catalog.value.length, installable: catalog.value.length, warnings: [] }
    if (!catalog.value.some(item => catalogKey(item) === selectedCatalogKey.value) && catalog.value.length > 0) {
      selectedCatalogKey.value = catalogKey(catalog.value[0])
      syncSelectedCatalogSource(catalog.value[0])
    }
  } catch (err) {
    if (requestId !== catalogRequestId) return
    catalogError.value = err?.error?.message || err?.message || 'Failed to load component catalog.'
  } finally {
    if (requestId === catalogRequestId) catalogLoading.value = false
  }
}

async function loadInstallations() {
  loadingInstallations.value = true
  installationsError.value = ''
  try {
    const response = await toolsService.listHdpComponentInstallations()
    installations.value = response.data?.installations || []
  } catch (err) {
    installationsError.value = err?.error?.message || err?.message || 'Could not load installation history. Use Refresh Installs to retry.'
  } finally {
    loadingInstallations.value = false
  }
}

async function validatePackage() {
  if (actionBusy.value || !isEnabled.value || !canValidate.value) return
  actionError.value = ''
  const snapshot = JSON.stringify(installPayload())
  validating.value = true
  validation.value = null
  installResult.value = null
  testResult.value = null
  latestInstallation.value = null
  try {
    const response = await toolsService.validateHdpComponentInstall({
      ...installPayload(),
    })
    if (snapshot !== JSON.stringify(installPayload())) return
    validation.value = response.data
    validatedPayload.value = snapshot
    if (validation.value?.checks?.[readinessCheckKey.value]?.success !== true) {
      warning(installStrategy.value === 'local_container' ? 'Package checks completed, but the local Docker image is not ready.' : 'Package checks completed, but HPC-Link is not ready.')
    } else {
      success('Component package validated.')
    }
  } catch (err) {
    actionError.value = err?.error?.message || err?.message || 'Validation failed. Review the source and manifest, then try again.'
    showError(actionError.value)
  } finally {
    validating.value = false
  }
}

async function installPackage() {
  if (recovery.value || actionBusy.value || !isEnabled.value || !canInstall.value) return
  actionError.value = ''
  installing.value = true
  installResult.value = null
  testResult.value = null
  try {
    recovery.value = { id: crypto.randomUUID(), payload: installPayload() }
    saveRecovery()
    const response = await toolsService.installHdpComponent({ ...recovery.value.payload, request_id: recovery.value.id })
    installResult.value = response.data || null
    latestInstallation.value = response.data?.installation || null
    if (latestInstallation.value?.status !== 'installed') throw new Error('Installation was not confirmed. Refresh installation history before retrying.')
    validatedPayload.value = ''
    recovery.value = null
    saveRecovery()
    success(installStrategy.value === 'local_container' ? 'Component installed locally.' : 'Component installed on HPC.')
    await loadInstallations()
  } catch (err) {
    actionError.value = err?.error?.message || err?.message || 'Installation could not be confirmed. Refresh installation history before retrying to avoid a duplicate request.'
    validatedPayload.value = ''
    if (['VALIDATION_ERROR', 'OPERATION_CONFLICT', 'SECURITY_ERROR', 'FORBIDDEN'].includes(err?.error?.code)) { recovery.value = null; saveRecovery() }
    showError(actionError.value)
    await reconnectInstallation()
    await loadInstallations()
  } finally {
    installing.value = false
  }
}

async function retryInstallation() {
  if (!recovery.value || installing.value) return
  installing.value = true
  try { await toolsService.installHdpComponent({ ...recovery.value.payload, request_id: recovery.value.id }) }
  catch (err) {
    actionError.value = err?.error?.message || err?.message || 'Installation is not confirmed yet.'
    if (['VALIDATION_ERROR', 'OPERATION_CONFLICT', 'SECURITY_ERROR', 'FORBIDDEN'].includes(err?.error?.code)) { recovery.value = null; saveRecovery() }
  }
  finally { installing.value = false; await reconnectInstallation() }
}

async function testInstallation(item) {
  if (actionBusy.value || !isEnabled.value || item.status !== 'installed') return
  actionError.value = ''
  testingId.value = item.installation_id
  testResult.value = null
  try {
    const response = await toolsService.testHdpComponentInstallation(item.installation_id)
    testResult.value = response.data || null
    latestInstallation.value = response.data?.installation || item
    if (response.data?.test?.status === 'skipped') warning('Smoke test skipped. No workload was executed; readiness alone is not a passing test.')
    else if (response.data?.test?.success === true) success('Smoke test passed.')
    else {
      actionError.value = response.data?.test?.error || 'Smoke test did not pass. Review the test details before using this component.'
      warning(actionError.value)
    }
    await loadInstallations()
  } catch (err) {
    actionError.value = err?.error?.message || err?.message || 'Smoke test failed.'
    showError(actionError.value)
  } finally {
    testingId.value = ''
  }
}

watch(() => JSON.stringify(installPayload()), () => { clearActionResults() }, { flush: 'sync' })

onMounted(async () => {
  await loadContext()
  await Promise.all([loadCatalog(), loadInstallations()])
  try { recovery.value = JSON.parse(sessionStorage.getItem(recoveryKey()) || 'null') } catch { recovery.value = null }
  if (recovery.value) await reconnectInstallation()
})
</script>
