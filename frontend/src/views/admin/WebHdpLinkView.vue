<template>
  <main class="link-admin mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
    <header class="flex flex-wrap items-start justify-between gap-4">
      <div><p class="eyebrow">Application integrations</p><h1 class="mt-2 text-3xl font-semibold text-gray-900">WebHDP-Link</h1><p class="mt-3 max-w-3xl text-gray-600">Make selected pipelines available to other applications. WebHDP manages access, input files, processing and results.</p></div>
      <div class="flex flex-wrap gap-2"><router-link to="/docs/webhdp-link" class="secondary">Integration guide</router-link><button class="secondary" :disabled="loading || Boolean(busy)" @click="load">{{ loading ? 'Refreshing…' : 'Refresh' }}</button></div>
    </header>
    <div v-if="error" class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">{{ error }}</div>
    <div v-if="notice" class="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800" role="status">{{ notice }}</div>
    <div class="grid gap-4 sm:grid-cols-3">
      <div class="metric"><p>Published pipelines</p><strong>{{ publications.filter(item => item.enabled).length }}</strong><span>Available for permitted applications</span></div>
      <div class="metric"><p>Connected applications</p><strong>{{ clients.filter(item => item.enabled).length }}</strong><span>With explicit origins and pipeline access</span></div>
      <div class="metric"><p>Processing queue</p><strong>{{ activeRuns.length }}</strong><span>{{ runs.filter(item => item.status === 'running').length }} running · {{ runs.filter(item => item.status === 'queued').length }} queued</span></div>
    </div>

    <section class="panel" aria-labelledby="pipelines-heading">
      <div class="section-heading"><div><h2 id="pipelines-heading">Published pipelines</h2><p>Each publication pins a native pipeline version and defines its public inputs and parameters.</p></div><button class="primary" :disabled="Boolean(busy)" @click="showPublicationForm = !showPublicationForm">{{ showPublicationForm ? 'Close form' : 'Publish a pipeline' }}</button></div>
      <form v-if="showPublicationForm" class="form-area space-y-5" @submit.prevent="createPublication">
        <div class="grid gap-4 md:grid-cols-2">
          <label>Public name<input v-model.trim="publicationForm.name" required maxlength="160" placeholder="Piano roll to MIDI"></label>
          <label>Publication ID<input v-model.trim="publicationForm.id" required pattern="[a-z0-9][a-z0-9_-]*" maxlength="80" placeholder="piano-roll-midi"><small>Stable identifier used by applications.</small></label>
          <label>Native pipeline<select v-model="publicationForm.pipeline_identifier" required @change="selectPipeline"><option value="" disabled>Select a pipeline</option><option v-for="pipeline in pipelineOptions" :key="pipeline.identifier" :value="pipeline.identifier">{{ pipeline.name }} ({{ pipeline.identifier }})</option></select></label>
          <label>Version<select v-model="publicationForm.pipeline_version" required @change="resetParameterFields"><option value="" disabled>Select a version</option><option v-for="version in selectedPipeline?.versions || []" :key="version.version" :value="version.version">{{ version.version }}</option></select></label>
        </div>
        <label>Description<textarea v-model.trim="publicationForm.description" rows="2" maxlength="2000" placeholder="Explain what this pipeline produces and any input requirements."></textarea></label>
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label>Input handling<select v-model="publicationForm.execution_mode"><option value="record">Process each file separately</option><option value="bundle">Process the files together</option></select></label>
          <label>Minimum files<input v-model.number="publicationForm.min_files" type="number" min="1" max="1000" required></label>
          <label>Maximum files<input v-model.number="publicationForm.max_files" type="number" :min="publicationForm.min_files" max="1000" required></label>
          <label>Allowed extensions<input v-model="publicationForm.extensions" required placeholder=".png, .jpg"><small>Comma-separated, including the dot.</small></label>
        </div>
        <fieldset class="rounded-lg border border-gray-200 bg-white p-4">
          <legend class="px-1 text-sm font-semibold text-gray-900">Computing resources</legend>
          <label class="checkbox-label"><input v-model="publicationForm.hpc_enabled" type="checkbox"><span>Request HPC resources through WebHDP</span></label>
          <p class="mt-2 text-xs text-gray-500">Requires a configured HPC-Link service and compatible component profiles. Applications never receive HPC credentials.</p>
          <div v-if="publicationForm.hpc_enabled" class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label>Duration (hours)<input v-model.number="publicationForm.walltime_hours" type="number" min="1" max="168" placeholder="Use central default"></label>
            <label>Partition<input v-model.trim="publicationForm.partition" placeholder="Instance default"></label>
            <label>GPUs<input v-model.number="publicationForm.gpu_count" type="number" min="0" max="8" required></label>
            <label>GPU type<input v-model.trim="publicationForm.gpu_type" placeholder="Instance default"></label>
          </div>
          <div v-if="publicationForm.hpc_enabled" class="mt-4">
            <label class="checkbox-label"><input v-model="publicationForm.retain_allocation" type="checkbox"><span>Keep allocation after completion</span></label>
            <p class="mt-2 text-xs text-gray-500">By default, WebHDP releases this job's allocation when processing ends. Retained allocations are managed by the administrator and are not automatically reused by other jobs.</p>
            <label v-if="publicationForm.retain_allocation" class="checkbox-label mt-3"><input v-model="publicationForm.reuse_retained_allocation" type="checkbox"><span>Reuse a compatible retained allocation</span></label>
            <p v-if="publicationForm.retain_allocation" class="mt-2 text-xs text-gray-500">Reuse an idle allocation retained by an earlier Link job for the same user and resource policy. Jobs remain isolated; the original scheduler expiry does not change.</p>
          </div>
        </fieldset>
        <fieldset v-if="parameterFields.length" class="space-y-3"><legend class="mb-2 text-sm font-semibold text-gray-900">Parameters applications may change</legend><p class="text-sm text-gray-600">Leave parameters unselected to keep the pipeline defaults. Exposed names become part of the public API.</p>
          <div v-for="field in parameterFields" :key="field.key" class="rounded-lg border border-gray-200 bg-white p-3">
            <label class="checkbox-label"><input v-model="field.exposed" type="checkbox"><span>{{ field.label }} <small>{{ field.step_id }} · {{ field.type }}</small></span></label>
            <div v-if="field.exposed" class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label>Public name<input v-model.trim="field.publicName" required pattern="[A-Za-z_][A-Za-z0-9_]*"></label>
              <label>Label<input v-model.trim="field.label" required></label>
              <template v-if="['integer', 'number'].includes(field.type)"><label>Minimum<input v-model="field.minimum" type="number" :step="field.type === 'integer' ? '1' : 'any'"></label><label>Maximum<input v-model="field.maximum" type="number" :step="field.type === 'integer' ? '1' : 'any'"></label></template>
            </div>
          </div>
        </fieldset>
        <div class="flex flex-wrap items-center gap-3"><button class="primary" type="submit" :disabled="Boolean(busy) || !publicationForm.pipeline_version">{{ busy === 'publication' ? 'Publishing…' : 'Publish selected version' }}</button><span class="text-xs text-gray-500">Publication is limited to the Link API on this instance.</span></div>
      </form>
      <div v-if="!publications.length && !loading" class="empty">No pipelines published yet. Publish a native pipeline to begin.</div>
      <div class="divide-y divide-gray-100">
        <article v-for="publication in publications" :key="publication.id" class="px-5 py-5">
          <div class="flex flex-wrap items-start justify-between gap-3"><div><div class="flex flex-wrap items-center gap-2"><h3 class="font-semibold text-gray-900">{{ publication.name }}</h3><span :class="['badge', publication.enabled ? 'badge-green' : 'badge-gray']">{{ publication.enabled ? 'Enabled' : 'Disabled' }}</span></div><p class="mt-1 font-mono text-xs text-gray-500">{{ publication.id }} · {{ publication.pipeline_identifier }} / {{ publication.pipeline_version }}</p><p class="mt-2 text-sm text-gray-600">{{ publication.description }}</p></div><button class="secondary" :disabled="Boolean(busy)" @click="togglePublication(publication)">{{ publication.enabled ? 'Disable' : 'Enable' }}</button></div>
          <div class="mt-3 flex flex-wrap gap-2 text-xs text-gray-600"><span class="rounded bg-gray-100 px-2 py-1">{{ publication.input?.min_files }}–{{ publication.input?.max_files }} files</span><span class="rounded bg-gray-100 px-2 py-1">{{ publication.input?.extensions?.join(', ') }}</span><span class="rounded bg-gray-100 px-2 py-1">{{ publication.execution_mode === 'bundle' ? 'Files processed together' : 'One execution per file' }}</span></div>
          <ol v-if="publication.structure?.length" class="mt-3 flex flex-wrap gap-2 text-xs text-indigo-700"><li v-for="(step, index) in publication.structure" :key="step.id" class="rounded border border-indigo-100 bg-indigo-50 px-2 py-1">{{ index + 1 }}. {{ step.name || step.id }}</li></ol>
          <details v-if="Object.keys(publication.parameter_schema?.properties || publication.parameters || {}).length" class="mt-3 text-sm"><summary class="cursor-pointer text-indigo-700">Public parameters</summary><ul class="mt-2 space-y-1"><li v-for="(field, name) in publication.parameter_schema?.properties || publication.parameters" :key="name"><code>{{ name }}</code> <span class="text-gray-500">{{ field.type }}{{ field.minimum !== undefined ? ` · minimum ${field.minimum}` : '' }}{{ field.maximum !== undefined ? ` · maximum ${field.maximum}` : '' }}</span></li></ul></details>
        </article>
      </div>
    </section>

    <section class="panel" aria-labelledby="clients-heading">
      <div class="section-heading"><div><h2 id="clients-heading">Applications</h2><p>Register exact application addresses, permitted pipelines and processing limits.</p></div><button class="primary" :disabled="Boolean(busy)" @click="toggleClientForm">{{ showClientForm ? 'Close form' : 'Register an application' }}</button></div>
      <form v-if="showClientForm" class="form-area space-y-4" @submit.prevent="saveClient">
        <h3 v-if="editingClientId" class="font-semibold text-gray-900">Edit application access</h3>
        <div class="grid gap-4 sm:grid-cols-2"><label>Application name<input v-model.trim="clientForm.name" required maxlength="160" placeholder="Heritage Model Studio"></label><label>Client ID<input v-model.trim="clientForm.id" :readonly="Boolean(editingClientId)" required pattern="[a-z0-9][a-z0-9_-]*" maxlength="80" placeholder="heritage-model-studio"></label><label>Browser origins<textarea v-model="clientForm.origins" rows="2" placeholder="https://studio.example.org"></textarea><small>One exact origin per line. No wildcards or paths. Leave empty for server-only clients.</small></label><label>OAuth return addresses<textarea v-model="clientForm.redirect_uris" rows="2" placeholder="https://studio.example.org/callback"></textarea><small>One complete address per line. Must belong to a registered origin.</small></label></div>
        <fieldset><legend class="mb-2 text-sm font-semibold text-gray-900">Allowed pipelines</legend><div class="flex flex-wrap gap-x-5 gap-y-2"><label v-for="publication in publications" :key="publication.id" class="checkbox-label"><input v-model="clientForm.pipeline_ids" type="checkbox" :value="publication.id"><span>{{ publication.name }}</span></label><p v-if="!publications.length" class="text-sm text-gray-500">Publish a pipeline first.</p></div></fieldset>
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><label>Queued jobs<input v-model.number="clientForm.max_queued_runs" type="number" min="1" max="1000" required></label><label>Concurrent jobs<input v-model.number="clientForm.max_concurrent_runs" type="number" min="1" max="64" required></label><label>Maximum upload (MiB)<input v-model.number="clientForm.upload_mib" type="number" min="1" max="20480" required></label><label>Storage allowance (MiB)<input v-model.number="clientForm.storage_mib" type="number" :min="clientForm.upload_mib" max="1048576" required></label></div>
        <div class="grid gap-4 sm:grid-cols-2">
          <label>Queued jobs per account<input v-model.number="clientForm.max_queued_runs_per_user" type="number" min="1" :max="clientForm.max_queued_runs"><small>Leave blank for up to five, subject to the application limit.</small></label>
          <label>Storage per account (MiB)<input v-model.number="clientForm.user_storage_mib" type="number" min="0.001" step="any" :max="clientForm.storage_mib"><small>Leave blank to use the automatic account share.</small></label>
        </div>
        <button class="primary" type="submit" :disabled="Boolean(busy) || !clientForm.pipeline_ids.length">{{ busy === 'client' ? 'Saving…' : editingClientId ? 'Save application' : 'Register application' }}</button>
      </form>
      <div v-if="!clients.length && !loading" class="empty">No applications registered yet.</div>
      <div class="divide-y divide-gray-100"><article v-for="client in clients" :key="client.id" class="px-5 py-5"><div class="flex flex-wrap items-start justify-between gap-3"><div><div class="flex flex-wrap items-center gap-2"><h3 class="font-semibold text-gray-900">{{ client.name }}</h3><span :class="['badge', client.enabled ? 'badge-green' : 'badge-gray']">{{ client.enabled ? 'Enabled' : 'Disabled' }}</span></div><p class="mt-1 font-mono text-xs text-gray-500">{{ client.id }}</p></div><div class="flex flex-wrap gap-2"><button class="secondary" :disabled="Boolean(busy)" @click="editClient(client)">Edit</button><button class="secondary" :disabled="Boolean(busy) || !client.enabled" @click="prepareToken(client)">Create server token</button><button class="secondary" :disabled="Boolean(busy)" @click="toggleClient(client)">{{ client.enabled ? 'Disable access' : 'Enable access' }}</button></div></div><div class="mt-3 grid gap-3 text-sm md:grid-cols-2"><div><p class="text-xs font-medium uppercase tracking-wide text-gray-500">Origins</p><p v-for="origin in client.origins" :key="origin" class="mt-1 break-all font-mono text-xs text-gray-700">{{ origin }}</p><p v-if="!client.origins?.length" class="mt-1 text-gray-600">Server access only</p></div><div><p class="text-xs font-medium uppercase tracking-wide text-gray-500">Allowed pipelines</p><p class="mt-1 text-gray-700">{{ client.pipeline_ids?.map(pipelineName).join(', ') }}</p></div></div><p class="mt-3 text-xs text-gray-500">{{ client.max_concurrent_runs }} concurrent · {{ client.max_queued_runs }} queued · {{ formatBytes(client.max_upload_bytes) }} per upload · {{ formatBytes(client.max_storage_bytes) }} storage</p><details v-if="client.redirect_uris?.length" class="mt-3 text-sm"><summary class="cursor-pointer text-indigo-700">OAuth return addresses</summary><p v-for="uri in client.redirect_uris" :key="uri" class="mt-2 break-all font-mono text-xs text-gray-600">{{ uri }}</p></details></article></div>
    </section>

    <section class="panel" aria-labelledby="tokens-heading">
      <div class="section-heading"><div><h2 id="tokens-heading">Access tokens</h2><p>Server tokens support unattended batch processing. Browser applications use the sign-in and consent flow.</p></div></div>
      <form v-if="tokenClient" class="form-area space-y-4" @submit.prevent="issueToken"><h3 class="font-semibold text-gray-900">Server token for {{ tokenClient.name }}</h3><div class="grid gap-4 sm:grid-cols-2"><label>Execution owner (WebHDP user ID)<input v-model.number="tokenForm.user_id" type="number" min="1" required><small>Jobs run with this user's identity.</small></label><label>Expires after (seconds)<input v-model.number="tokenForm.expires_in" type="number" min="60" max="86400" required></label></div><fieldset><legend class="mb-2 text-sm font-semibold text-gray-900">Permissions</legend><div class="space-y-2"><label v-for="(label, scope) in linkScopeLabels" :key="scope" class="checkbox-label"><input v-model="tokenForm.scopes" type="checkbox" :value="scope"><span>{{ label }}</span></label></div></fieldset><div class="flex gap-3"><button class="primary" :disabled="Boolean(busy) || !tokenForm.scopes.length">Create token</button><button class="secondary" type="button" @click="tokenClient = null">Close</button></div></form>
      <div v-if="issuedToken" class="m-5 rounded-lg border border-amber-200 bg-amber-50 p-4"><h3 class="font-semibold text-amber-900">Save this token now</h3><p class="mt-1 text-sm text-amber-900">It is shown once. Keep it in your application's server secret store. Never put it in browser code or a public repository.</p><label class="mt-3">New server token<textarea :value="issuedToken" readonly rows="3" autocomplete="off" spellcheck="false" class="font-mono text-xs"></textarea></label><button class="secondary mt-3" @click="issuedToken = ''">I have saved the token</button></div>
      <div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th>Application</th><th>Owner</th><th>Expires</th><th>Status</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody><tr v-for="token in tokens" :key="token.id || token.token_id"><td>{{ clientName(token.client_id) }}</td><td>{{ token.user_id }}</td><td>{{ formatDate(token.expires_at) }}</td><td><span :class="['badge', token.revoked_at || token.revoked || new Date(token.expires_at).getTime() <= Date.now() ? 'badge-gray' : 'badge-green']">{{ token.revoked_at || token.revoked ? 'Revoked' : new Date(token.expires_at).getTime() <= Date.now() ? 'Expired' : 'Active' }}</span></td><td><button v-if="!token.revoked_at && !token.revoked" class="text-sm font-medium text-red-700 disabled:opacity-50" :disabled="Boolean(busy)" @click="revokeToken(token)">Revoke</button></td></tr></tbody></table></div><p v-if="!tokens.length && !loading" class="empty">No access tokens issued.</p>
    </section>

    <section class="panel" aria-labelledby="queue-heading">
      <div class="section-heading"><div><h2 id="queue-heading">Processing jobs</h2><p>Jobs remain in the queue until a WebHDP-Link worker is available.</p></div><label class="checkbox-label text-sm"><input v-model="autoRefresh" type="checkbox">Refresh every 5 seconds</label></div>
      <div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th>Job</th><th>Pipeline</th><th>Status</th><th>Progress</th><th>Submitted</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody><tr v-for="run in runs" :key="run.id"><td class="font-mono text-xs">{{ run.id.slice(0, 12) }}</td><td>{{ pipelineName(run.pipeline_id) }}<p class="mt-1 text-xs text-gray-500">{{ run.pipeline_version }}</p></td><td><span :class="['badge', statusClass(run.status)]">{{ run.status }}</span><p v-if="run.hpc_cleanup_pending" class="mt-2 max-w-xs text-xs text-amber-800">HPC release pending; the worker will retry.</p><p v-if="run.error" class="mt-2 max-w-xs text-xs text-red-700">{{ typeof run.error === 'string' ? run.error : run.error.message || run.error.detail }}</p></td><td>{{ run.progress?.completed || 0 }} / {{ run.progress?.total || 0 }}</td><td class="whitespace-nowrap text-xs">{{ formatDate(run.created_at) }}</td><td><button v-if="['queued', 'running'].includes(run.status)" class="text-sm font-medium text-red-700 disabled:opacity-50" :disabled="Boolean(busy)" @click="cancelRun(run)">Cancel job</button></td></tr></tbody></table></div><p v-if="!runs.length && !loading" class="empty">No processing jobs submitted yet.</p>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import linkService from '@/services/webhdpLink.service'
import { linkErrorMessage, linkScopeLabels } from '@/utils/webhdpLink'

const authStore = useAuthStore()
const loading = ref(false), busy = ref(''), error = ref(''), notice = ref('')
const publications = ref([]), clients = ref([]), tokens = ref([]), runs = ref([]), pipelineOptions = ref([])
const editingClientId = ref('')
const showPublicationForm = ref(false), showClientForm = ref(false), tokenClient = ref(null), issuedToken = ref(''), autoRefresh = ref(false)
const publicationForm = reactive({ id: '', name: '', description: '', pipeline_identifier: '', pipeline_version: '', execution_mode: 'record', min_files: 1, max_files: 1, extensions: '', hpc_enabled: false, walltime_hours: '', retain_allocation: false, reuse_retained_allocation: false, partition: '', gpu_count: 1, gpu_type: '' })
const clientDefaults = { id: '', name: '', origins: '', redirect_uris: '', max_queued_runs: 20, max_concurrent_runs: 1, upload_mib: 100, storage_mib: 1024, max_queued_runs_per_user: '', user_storage_mib: '' }
const clientForm = reactive({ ...clientDefaults, pipeline_ids: [] })
const tokenForm = reactive({ user_id: authStore.user?.id || '', expires_in: 3600, scopes: Object.keys(linkScopeLabels) })
const parameterFields = ref([])
const selectedPipeline = computed(() => pipelineOptions.value.find(item => item.identifier === publicationForm.pipeline_identifier))
const selectedVersion = computed(() => selectedPipeline.value?.versions.find(item => item.version === publicationForm.pipeline_version))
const activeRuns = computed(() => runs.value.filter(item => ['queued', 'running'].includes(item.status)))
const splitLines = (value) => value.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
const pipelineName = (id) => publications.value.find(item => item.id === id)?.name || id
const clientName = (id) => clients.value.find(item => item.id === id)?.name || id
const formatDate = (value) => value ? new Date(value).toLocaleString() : '—'
const formatBytes = (value) => `${Math.round(Number(value || 0) / 1048576)} MiB`
const statusClass = (status) => status === 'succeeded' ? 'badge-green' : status === 'failed' ? 'badge-red' : ['running', 'queued'].includes(status) ? 'badge-blue' : 'badge-gray'
let timer

async function load() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const [publicationResponse, clientResponse, tokenResponse, runResponse, optionResponse] = await Promise.all([
      linkService.listPublications(), linkService.listClients(), linkService.listTokens(), linkService.listRuns(), linkService.pipelineOptions(),
    ])
    publications.value = publicationResponse.publications
    clients.value = clientResponse.clients
    tokens.value = tokenResponse.tokens
    runs.value = runResponse.runs
    pipelineOptions.value = optionResponse.pipelines || []
  } catch (err) { error.value = linkErrorMessage(err) }
  finally { loading.value = false }
}

async function perform(key, operation, message) {
  if (busy.value) return false
  busy.value = key
  error.value = ''
  notice.value = ''
  try { await operation(); await load(); notice.value = message; return true }
  catch (err) { error.value = linkErrorMessage(err); return false }
  finally { busy.value = '' }
}

function selectPipeline() {
  publicationForm.pipeline_version = selectedPipeline.value?.versions?.[0]?.version || ''
  resetParameterFields()
}
function resetParameterFields() {
  parameterFields.value = (selectedVersion.value?.steps || []).flatMap(step => (step.parameters || []).filter(field => ['boolean', 'integer', 'number', 'string', 'text', 'string_dropdown'].includes(field.type)).map(field => ({
    ...field, key: `${step.id}.${field.name}`, step_id: step.id, parameter: field.name,
    label: field.label || field.name, type: ['text', 'string_dropdown'].includes(field.type) ? 'string' : field.type,
    publicName: field.name, exposed: false, minimum: field.minimum ?? field.min ?? '', maximum: field.maximum ?? field.max ?? '',
  })))
}
async function createPublication() {
  const parameters = {}
  try {
    for (const field of parameterFields.value.filter(item => item.exposed)) {
      if (Object.hasOwn(parameters, field.publicName)) throw new Error('Every public parameter must have a unique name.')
      const parameter = { step_id: field.step_id, parameter: field.parameter, type: field.type, label: field.label }
      if (field.default !== undefined) parameter.default = field.default
      if (field.enum) parameter.enum = field.enum
      else if (field.options?.length) parameter.enum = field.options.map(option => typeof option === 'object' ? option.value : option)
      if (field.minimum !== '') parameter.minimum = Number(field.minimum)
      if (field.maximum !== '') parameter.maximum = Number(field.maximum)
      parameters[field.publicName] = parameter
    }
  } catch (err) { error.value = linkErrorMessage(err); return }
  const payload = { id: publicationForm.id, name: publicationForm.name, description: publicationForm.description,
    pipeline_identifier: publicationForm.pipeline_identifier, pipeline_version: publicationForm.pipeline_version,
    execution_mode: publicationForm.execution_mode, enabled: true, parameters,
    input: { min_files: publicationForm.min_files, max_files: publicationForm.max_files, extensions: publicationForm.extensions.split(',').map(value => value.trim().toLowerCase()).filter(Boolean) },
  }
  if (publicationForm.hpc_enabled) payload.hpc = { enabled: true, retain_allocation: publicationForm.retain_allocation, reuse_retained_allocation: publicationForm.retain_allocation && publicationForm.reuse_retained_allocation, ...(publicationForm.walltime_hours !== '' ? { walltime_hours: publicationForm.walltime_hours } : {}), gpu_count: publicationForm.gpu_count, ...(publicationForm.gpu_type ? { gpu_type: publicationForm.gpu_type } : {}), ...(publicationForm.partition ? { partition: publicationForm.partition } : {}) }
  if (await perform('publication', () => linkService.createPublication(payload), 'Pipeline published for WebHDP-Link.')) showPublicationForm.value = false
}
function toggleClientForm() {
  showClientForm.value = !showClientForm.value
  if (showClientForm.value) {
    editingClientId.value = ''
    Object.assign(clientForm, { ...clientDefaults, pipeline_ids: [] })
  }
}
function editClient(client) {
  editingClientId.value = client.id
  Object.assign(clientForm, { ...client, origins: (client.origins || []).join('\n'), redirect_uris: (client.redirect_uris || []).join('\n'), pipeline_ids: [...(client.pipeline_ids || [])],
    upload_mib: client.max_upload_bytes / 1048576, storage_mib: client.max_storage_bytes / 1048576,
    max_queued_runs_per_user: client.max_queued_runs_per_user ?? '', user_storage_mib: client.max_storage_bytes_per_user == null ? '' : client.max_storage_bytes_per_user / 1048576 })
  showClientForm.value = true
}
async function saveClient() {
  const payload = { id: clientForm.id, name: clientForm.name, enabled: true, origins: splitLines(clientForm.origins), redirect_uris: splitLines(clientForm.redirect_uris), pipeline_ids: [...clientForm.pipeline_ids],
    max_queued_runs: clientForm.max_queued_runs, max_concurrent_runs: clientForm.max_concurrent_runs, max_upload_bytes: Math.round(clientForm.upload_mib * 1048576), max_storage_bytes: Math.round(clientForm.storage_mib * 1048576),
    max_queued_runs_per_user: clientForm.max_queued_runs_per_user === '' ? null : clientForm.max_queued_runs_per_user,
    max_storage_bytes_per_user: clientForm.user_storage_mib === '' ? null : Math.round(clientForm.user_storage_mib * 1048576) }
  const id = editingClientId.value
  if (id) { delete payload.id; delete payload.enabled }
  if (await perform('client', () => id ? linkService.updateClient(id, payload) : linkService.createClient(payload), id ? 'Application access updated.' : 'Application registered. Its client ID can be used in the browser SDK.')) showClientForm.value = false
}
const togglePublication = (item) => perform(`publication-${item.id}`, () => linkService.updatePublication(item.id, { enabled: !item.enabled }), item.enabled ? 'Publication disabled.' : 'Publication enabled.')
const toggleClient = (item) => perform(`client-${item.id}`, () => linkService.updateClient(item.id, { enabled: !item.enabled }), item.enabled ? 'Application access disabled.' : 'Application access enabled.')
const cancelRun = (item) => perform(`run-${item.id}`, () => linkService.cancelRun(item.id), 'Cancellation requested. Check the job status for completion.')
const revokeToken = (item) => perform(`token-${item.id || item.token_id}`, () => linkService.revokeToken(item.id || item.token_id), 'Token revoked.')
function prepareToken(client) { tokenClient.value = client; issuedToken.value = ''; tokenForm.user_id = authStore.user?.id || ''; notice.value = '' }
async function issueToken() {
  const client = tokenClient.value
  if (!client) return
  await perform('issue-token', async () => {
    const result = await linkService.issueToken(client.id, { user_id: tokenForm.user_id, expires_in: tokenForm.expires_in, scope: tokenForm.scopes.join(' ') })
    issuedToken.value = result.access_token
    tokenClient.value = null
  }, 'Server token created. Save it before leaving this page.')
}
onMounted(() => {
  load()
  timer = setInterval(async () => {
    if (!autoRefresh.value || loading.value || busy.value) return
    try { runs.value = (await linkService.listRuns()).runs }
    catch (err) { error.value = linkErrorMessage(err) }
  }, 5000)
})
onUnmounted(() => { clearInterval(timer); issuedToken.value = '' })
</script>

<style scoped>
.eyebrow { @apply text-xs font-semibold uppercase tracking-wider text-indigo-600; }
.panel { @apply overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm; }
.section-heading { @apply flex flex-wrap items-center justify-between gap-4 border-b border-gray-100 px-5 py-5; }
.section-heading h2 { @apply text-lg font-semibold text-gray-900; }
.section-heading p { @apply mt-1 max-w-3xl text-sm text-gray-500; }
.primary { @apply rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50; }
.secondary { @apply rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50; }
.metric { @apply rounded-xl border border-gray-200 bg-white p-5; }
.metric p { @apply text-sm font-medium text-gray-600; }
.metric strong { @apply my-2 block text-3xl font-semibold text-gray-900; }
.metric span { @apply text-xs text-gray-500; }
.form-area { @apply border-b border-gray-200 bg-gray-50 p-5; }
label { @apply block text-sm font-medium text-gray-700; }
label input:not([type="checkbox"]), label select, label textarea { @apply mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-normal text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500; }
label small { @apply mt-1 block text-xs font-normal text-gray-500; }
.checkbox-label { @apply flex items-start gap-2 font-normal; }
.checkbox-label input { @apply mt-1 h-4 w-4 shrink-0 accent-indigo-600; }
.badge { @apply inline-flex rounded-full px-2 py-0.5 text-xs font-medium; }
.badge-green { @apply bg-emerald-50 text-emerald-800; }
.badge-gray { @apply bg-gray-100 text-gray-600; }
.badge-blue { @apply bg-indigo-50 text-indigo-700; }
.badge-red { @apply bg-red-50 text-red-800; }
th { @apply whitespace-nowrap bg-gray-50 px-5 py-3 text-xs font-medium uppercase tracking-wide text-gray-500; }
td { @apply border-t border-gray-100 px-5 py-4 align-top text-gray-700; }
.empty { @apply px-5 py-7 text-sm text-gray-500; }
button:focus-visible, summary:focus-visible { @apply outline outline-2 outline-offset-2 outline-indigo-600; }
</style>
