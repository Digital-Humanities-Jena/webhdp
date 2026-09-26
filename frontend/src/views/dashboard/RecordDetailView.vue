<template>
  <div class="min-h-screen bg-gradient-to-b from-slate-50 via-white to-gray-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <router-link
            :to="`/sessions/${route.params.sessionId}/records`"
            class="text-sm font-medium text-indigo-600 hover:text-indigo-800"
          >
            &larr; Back to Session Records
          </router-link>
          <h1 class="mt-2 text-3xl font-bold text-slate-900">Record Detail</h1>
          <p class="mt-1 text-sm text-slate-600">
            Session #{{ route.params.sessionId }} · Local Record #{{ route.params.recordId }}
          </p>
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="px-3 py-2 text-sm font-medium border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50"
            @click="downloadJson"
            :disabled="!detail"
          >
            Export JSON
          </button>
          <a
            v-if="record?.record_link"
            :href="record.record_link"
            target="_blank"
            rel="noopener noreferrer"
            class="px-3 py-2 text-sm font-medium border border-indigo-200 rounded-lg text-indigo-700 hover:bg-indigo-50"
          >
            Open Zenodo Record
          </a>
          <button
            v-if="health.can_repair_missing_thumbnails || health.can_create_new_version"
            type="button"
            class="px-3 py-2 text-sm font-medium border border-emerald-200 rounded-lg text-emerald-700 hover:bg-emerald-50 disabled:opacity-60 disabled:cursor-not-allowed"
            :disabled="versioning"
            @click="createVersion"
          >
            {{ versioning ? 'Creating…' : 'Create New Version Draft' }}
          </button>
        </div>
      </div>

      <LoadingSpinner v-if="loading" size="lg" text="Loading record detail..." />

      <div v-else-if="error" class="bg-white rounded-xl border border-rose-200 p-6">
        <Alert v-model="showError" variant="error" :message="error" :dismissible="false" />
      </div>

      <div v-else-if="detail" class="space-y-6">
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div class="bg-white rounded-xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-wide text-slate-500">Status</p>
            <p class="mt-1 text-xl font-bold" :class="statusColor(record?.record_status)">{{ record?.record_status || 'unknown' }}</p>
          </div>
          <div class="bg-white rounded-xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-wide text-slate-500">Files</p>
            <p class="mt-1 text-xl font-bold text-slate-900">{{ health.total_files || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-wide text-slate-500">Uploaded Files</p>
            <p class="mt-1 text-xl font-bold text-emerald-700">{{ health.uploaded_files || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-wide text-slate-500">Mapped Metadata</p>
            <p class="mt-1 text-xl font-bold text-indigo-700">{{ record?.provenance?.mapping_field_count || 0 }}</p>
          </div>
        </div>

        <div class="bg-white rounded-xl border border-slate-200 p-5">
          <h2 class="text-xl font-semibold text-slate-900">{{ record?.record_title || 'Untitled record' }}</h2>
          <div class="mt-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 text-sm">
            <div>
              <p class="text-slate-500">Zenodo record ID</p>
              <p class="font-medium text-slate-800">{{ record?.zenodo_record_id || 'N/A' }}</p>
            </div>
            <div>
              <p class="text-slate-500">Concept record ID</p>
              <p class="font-medium text-slate-800">{{ record?.concept_rec_id || 'N/A' }}</p>
            </div>
            <div>
              <p class="text-slate-500">DOI</p>
              <p class="font-medium text-slate-800 break-all">{{ record?.zenodo_doi || 'N/A' }}</p>
            </div>
            <div>
              <p class="text-slate-500">Environment</p>
              <p class="font-medium text-slate-800">{{ record?.is_sandbox === true ? 'Sandbox' : record?.is_sandbox === false ? 'Production' : 'Unknown' }}</p>
            </div>
          </div>

          <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
            <div>
              <p class="text-slate-500">Source file</p>
              <p class="font-medium text-slate-800">{{ record?.source_file_name || 'N/A' }}</p>
              <p class="text-xs text-slate-500 break-all">{{ record?.source_file_path || 'N/A' }}</p>
            </div>
            <div>
              <p class="text-slate-500">MSF path</p>
              <p class="font-medium text-slate-800 break-all">{{ record?.provenance?.msf_path || 'Not set' }}</p>
            </div>
          </div>
        </div>

        <section v-if="modelPreview.is_3d_record" class="bg-white rounded-xl border border-slate-200 p-5">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 class="text-lg font-semibold text-slate-900">3D Preview</h3>
              <p class="mt-1 text-sm text-slate-600 break-all">
                {{ modelPreview.filename || record?.source_file_name || '3D model' }}
              </p>
            </div>
            <span
              class="px-2.5 py-1 text-xs font-semibold rounded-full border"
              :class="modelPreview.can_inline_preview ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-50 text-slate-600 border-slate-200'"
            >
              {{ modelPreview.format ? modelPreview.format.toUpperCase() : '3D' }}
            </span>
          </div>

          <div v-if="modelPreview.can_inline_preview" class="mt-4">
            <PlaygroundModelViewer
              v-if="previewLoaded"
              :src="modelPreview.url"
              :alt="record?.record_title || modelPreview.filename || '3D model preview'"
            />
            <div v-else class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p class="text-sm text-slate-700">
                Inline preview is available for this published Zenodo model.
              </p>
              <div class="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  class="px-3 py-2 text-sm font-medium border border-indigo-200 rounded-lg text-indigo-700 bg-white hover:bg-indigo-50"
                  @click="previewLoaded = true"
                >
                  Load 3D Preview
                </button>
                <a
                  :href="modelPreview.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="px-3 py-2 text-sm font-medium border border-slate-200 rounded-lg text-slate-700 bg-white hover:bg-slate-50"
                >
                  Open Model File
                </a>
              </div>
            </div>
          </div>

          <div v-else class="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
            <p class="text-sm text-slate-700">
              Inline 3D preview is not available for this record.
            </p>
            <p v-if="modelPreview.reason" class="mt-1 text-xs text-slate-500">
              {{ previewReasonLabel(modelPreview.reason) }}
            </p>
          </div>
        </section>

        <section class="bg-white rounded-xl border border-slate-200 p-5" aria-labelledby="lod-recovery-title">
          <h2 id="lod-recovery-title" class="font-semibold text-slate-900">Metadata exports</h2>
          <p class="mt-1 text-sm text-slate-600">Each format is validated before upload. Retry uses the saved settings, reuses this draft, and keeps unchanged successful exports. To apply edited mappings or templates, start a new pipeline run.</p>
          <p v-if="lodError" role="alert" class="mt-2 text-red-700">{{ lodError }}</p>
          <p v-if="lodBusy" role="status" class="mt-3 text-sm text-slate-600">Generating and validating metadata. This can take a minute…</p>
          <progress v-if="lodBusy" aria-label="Metadata validation in progress" class="mt-2 w-full" />
          <ul v-if="lodReport?.available" class="mt-3 space-y-3">
            <li v-for="(item, standard) in lodReport.formats" :key="standard" class="rounded-lg border p-3">
              <span class="font-medium">{{ standard.toUpperCase() }}</span>
              <span class="ml-2 text-sm" :class="item.success ? 'text-green-700' : 'text-red-700'">{{ item.status === 'generated' ? 'Validated' : item.status === 'skipped_disabled' ? 'Disabled' : 'Needs attention' }}</span>
              <button v-if="item.status === 'generated'" type="button" :disabled="lodBusy" class="ml-3 text-sm text-indigo-700 underline" @click="downloadLod(standard)">Download {{ standard.toUpperCase() }}</button>
              <p v-if="item.error" class="mt-1 text-sm text-red-700">{{ item.error }}</p>
              <p v-if="item.minimum_viable_applied" class="mt-1 text-sm text-amber-700">Required fields were completed using record data or defaults. Review the export before sharing.</p>
              <details v-if="item.validation" class="mt-2 text-sm"><summary class="cursor-pointer">Validation report</summary><pre class="mt-2 overflow-auto whitespace-pre-wrap">{{ JSON.stringify(item.validation, null, 2) }}</pre></details>
            </li>
          </ul>
          <p v-else-if="!lodError && !lodBusy" class="mt-3 text-sm text-slate-500">No metadata generation report is available yet.</p>
          <div class="mt-3 flex gap-3">
            <button type="button" :disabled="lodBusy" class="text-sm text-indigo-700 underline disabled:opacity-50" @click="loadLod(false)">Refresh report</button>
            <button v-if="lodReport?.available && Object.values(lodReport.formats).some(item => !item.success)" type="button" :disabled="lodBusy" class="text-sm text-indigo-700 underline disabled:opacity-50" @click="loadLod(true)">Retry failed formats</button>
            <button v-if="lodReport?.available" type="button" class="text-sm text-indigo-700 underline" @click="downloadLodReport">Download report</button>
          </div>
        </section>
        <div class="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <section class="bg-white rounded-xl border border-slate-200 p-5">
            <h3 class="text-sm font-semibold text-slate-900">Zenodo Status</h3>
            <div class="mt-3 grid grid-cols-2 gap-3 text-sm">
              <div>
                <p class="text-slate-500">Files uploaded</p>
                <p class="font-medium text-slate-800">
                  {{ zenodoSummary.uploaded_file_count || 0 }} / {{ zenodoSummary.file_count || 0 }}
                </p>
              </div>
              <div>
                <p class="text-slate-500">HTML link</p>
                <p class="font-medium text-slate-800">{{ zenodoSummary.has_html_link ? 'Available' : 'Missing' }}</p>
              </div>
              <div>
                <p class="text-slate-500">Latest snapshot</p>
                <p class="font-medium text-slate-800">{{ zenodoSummary.latest_snapshot_stage || 'n/a' }}</p>
              </div>
              <div>
                <p class="text-slate-500">Communities</p>
                <p class="font-medium text-slate-800">{{ zenodoCommunitiesLabel }}</p>
              </div>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <span
                v-for="(enabled, label) in zenodoActionLabels"
                :key="label"
                class="px-2 py-1 text-xs rounded-full border"
                :class="enabled ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-50 text-slate-500 border-slate-200'"
              >
                {{ label }}
              </span>
            </div>
            <p v-if="zenodoSummary.last_api_error" class="mt-3 text-xs text-rose-700">
              Last API error: {{ zenodoSummary.last_api_error }}
            </p>
          </section>

          <section class="bg-white rounded-xl border border-slate-200 p-5">
            <h3 class="text-sm font-semibold text-slate-900">Lineage Summary</h3>
            <div class="mt-3 grid grid-cols-2 gap-3 text-sm">
              <div>
                <p class="text-slate-500">Snapshots</p>
                <p class="font-medium text-slate-800">{{ lineageSummary.snapshot_count || 0 }}</p>
              </div>
              <div>
                <p class="text-slate-500">Same concept latest</p>
                <p class="font-medium text-slate-800">{{ latestConceptRecordLabel }}</p>
              </div>
            </div>
            <div class="mt-4">
              <p class="text-slate-500 text-sm">Source hierarchy root</p>
              <p class="font-medium text-slate-800 text-sm break-all">
                {{ lineageRootLabel }}
              </p>
            </div>
          </section>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <section class="xl:col-span-2 bg-white rounded-xl border border-slate-200 p-5">
            <h3 class="text-lg font-semibold text-slate-900">Included Files</h3>
            <div v-if="!(record?.files?.length)" class="mt-3 text-sm text-slate-500">No file entries found.</div>
            <ul v-else class="mt-3 divide-y divide-slate-100 border border-slate-200 rounded-lg overflow-hidden">
              <li
                v-for="file in record.files"
                :key="`${record.local_record_id}-${file.file_id}-${file.filename}`"
                class="p-3"
              >
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p class="text-sm font-medium text-slate-900">{{ file.filename || file.mapped_file_path }}</p>
                    <p class="text-xs text-slate-500 break-all">{{ file.absolute_path || file.mapped_file_path || 'N/A' }}</p>
                    <p class="mt-1 text-xs text-slate-500">
                      {{ file.file_purpose || 'unknown purpose' }}
                      <span v-if="file.file_type">• {{ file.file_type }}</span>
                      <span v-if="file.size_bytes">• {{ formatBytes(file.size_bytes) }}</span>
                    </p>
                  </div>
                  <div class="text-right text-xs text-slate-500">
                    <p>{{ file.upload_status || file.status || 'pending' }}</p>
                    <p v-if="file.pipeline_source || file.step_source">{{ file.pipeline_source || 'unknown' }} / {{ file.step_source || 'unknown' }}</p>
                  </div>
                </div>
              </li>
            </ul>
          </section>

          <section class="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">Record Health</h3>
              <ul class="mt-2 text-sm text-slate-700 space-y-1">
                <li>{{ yesNo(health.has_record_link) }} Zenodo record link</li>
                <li>{{ yesNo(health.has_doi) }} DOI</li>
                <li>{{ yesNo(health.has_source_file) }} Source file</li>
                <li>{{ yesNo(health.has_mapped_metadata) }} Mapped metadata</li>
                <li>{{ yesNo(!health.has_processing_error) }} No processing error</li>
                <li v-if="health.is_3d_record">{{ yesNo(!health.missing_uploaded_thumbnails) }} Uploaded thumbnails present</li>
                <li v-if="health.is_3d_record">Local rendered thumbnails: {{ health.local_rendered_thumbnail_count || 0 }}</li>
                <li v-if="health.is_3d_record">Uploaded thumbnails: {{ health.uploaded_thumbnail_count || 0 }}</li>
                <li v-if="health.is_3d_record">Linked thumbnails in record map: {{ health.linked_thumbnail_count || 0 }}</li>
              </ul>
            </div>

            <div>
              <h3 class="text-sm font-semibold text-slate-900">Pipeline Status</h3>
              <ul class="mt-2 text-sm text-slate-700 space-y-1">
                <li>Render: {{ record?.processing?.render_status || 'n/a' }}</li>
                <li>USDZ: {{ record?.processing?.usdz_status || 'n/a' }}</li>
                <li>EDM: {{ record?.processing?.edm_status || 'n/a' }}</li>
                <li>IIIF: {{ record?.processing?.iiif_status || 'n/a' }}</li>
                <li>METS: {{ record?.processing?.mets_status || 'n/a' }}</li>
              </ul>
              <p v-if="record?.processing?.error" class="mt-2 text-xs text-rose-700">Error: {{ record.processing.error }}</p>
            </div>

            <div v-if="record?.provenance?.pipeline_lineage?.length">
              <h3 class="text-sm font-semibold text-slate-900">Lineage</h3>
              <div class="mt-2 flex flex-wrap gap-2">
                <span
                  v-for="lineage in record.provenance.pipeline_lineage"
                  :key="`${lineage.pipeline}-${lineage.step}`"
                  class="px-2 py-1 text-xs rounded-full bg-slate-100 text-slate-700 border border-slate-200"
                >
                  {{ lineage.pipeline }} / {{ lineage.step }}
                </span>
              </div>
            </div>
          </section>
        </div>

        <section
          v-if="metadataValidationReports.length"
          data-testid="record-validation-reports"
          class="bg-white rounded-xl border border-slate-200 p-5"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 class="text-lg font-semibold text-slate-900">Metadata Validation Reports</h3>
              <p class="mt-1 text-sm text-slate-600">
                Persisted validation reports recovered from this session `.hdpc`.
              </p>
            </div>
            <span class="px-2.5 py-1 text-xs font-semibold rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">
              {{ metadataValidationReports.length }} report{{ metadataValidationReports.length === 1 ? '' : 's' }}
            </span>
          </div>

          <div class="mt-4 space-y-4">
            <article
              v-for="item in metadataValidationReports"
              :key="`${item.fileId}-${item.filename}`"
              data-testid="record-validation-report"
              class="rounded-lg border border-slate-200 bg-slate-50 p-4"
            >
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p class="text-sm font-semibold text-slate-900">{{ item.filename }}</p>
                  <p class="mt-1 text-xs text-slate-500 break-all">{{ item.relativePath || item.absolutePath || 'Session file' }}</p>
                </div>
                <span
                  class="px-2 py-1 text-xs font-semibold rounded-full border"
                  :class="item.valid === false ? 'bg-rose-50 text-rose-700 border-rose-200' : 'bg-emerald-50 text-emerald-700 border-emerald-200'"
                >
                  {{ item.statusLabel }}
                </span>
              </div>

              <dl class="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div>
                  <dt class="text-slate-500">Validator</dt>
                  <dd class="font-medium text-slate-800">{{ item.validatorLabel }}</dd>
                </div>
                <div>
                  <dt class="text-slate-500">Profile</dt>
                  <dd class="font-medium text-slate-800">{{ item.profileLabel }}</dd>
                </div>
                <div>
                  <dt class="text-slate-500">Errors</dt>
                  <dd class="font-medium" :class="item.errorCount ? 'text-rose-700' : 'text-emerald-700'">{{ item.errorCount }}</dd>
                </div>
                <div>
                  <dt class="text-slate-500">Warnings</dt>
                  <dd class="font-medium" :class="item.warningCount ? 'text-amber-700' : 'text-slate-800'">{{ item.warningCount }}</dd>
                </div>
              </dl>

              <pre class="mt-3 p-3 text-xs bg-white border border-slate-200 rounded-lg overflow-auto max-h-72">{{ formatJson(item.report) }}</pre>
            </article>
          </div>
        </section>

        <div class="bg-white rounded-xl border border-slate-200 p-5">
          <h3 class="text-sm font-semibold text-slate-900">Mapped Metadata Payload</h3>
          <pre class="mt-3 p-3 text-xs bg-slate-50 border border-slate-200 rounded-lg overflow-auto max-h-72">{{ formatJson(record?.provenance?.mapped_metadata || {}) }}</pre>
        </div>

        <div class="bg-white rounded-xl border border-slate-200 p-5">
          <h3 class="text-sm font-semibold text-slate-900">Full Record Metadata JSON</h3>
          <pre class="mt-3 p-3 text-xs bg-slate-50 border border-slate-200 rounded-lg overflow-auto max-h-96">{{ formatJson(record?.record_metadata || {}) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import api from '@/services/api'
import submissionService from '@/services/submission.service.js'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import { useToast } from '@/composables/useToast'
import PlaygroundModelViewer from '@/components/tools/playground/PlaygroundModelViewer.vue'

const route = useRoute()
const toast = useToast()

const loading = ref(true)
const detail = ref(null)
const error = ref('')
const versioning = ref(false)
const previewLoaded = ref(false)
const lodReport = ref(null)
const lodError = ref('')
const lodBusy = ref(false)
async function loadLod(retry = false) {
  if (lodBusy.value) return
  const url = `/sessions/${Number(route.params.sessionId)}/records/${Number(route.params.recordId)}/lod`
  lodBusy.value = true
  lodError.value = ''
  try {
    const response = retry ? await api.post(url, {}, { timeout: 300000 }) : await api.get(url, { suppressGlobalError: true })
    lodReport.value = response.data
  } catch (err) {
    lodError.value = err?.error?.message || err?.message || 'Metadata report is unavailable. Refresh to reconnect.'
  } finally { lodBusy.value = false }
}
async function downloadLod(standard) {
  try {
    const blob = await api.get(`/sessions/${Number(route.params.sessionId)}/records/${Number(route.params.recordId)}/lod`, { params: { format: standard }, responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = ({ edm: 'edm.xml', iiif: 'iiif.json', mets: 'mets.xml', cidoc_crm: 'cidoc-crm.xml', jsonld: 'metadata.jsonld' })[standard]
    link.click()
    URL.revokeObjectURL(url)
  } catch { lodError.value = 'The export could not be downloaded. Refresh the report or retry generation if the file changed.' }
}
function downloadLodReport() {
  const url = URL.createObjectURL(new Blob([JSON.stringify(lodReport.value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'metadata-validation.json'
  link.click()
  URL.revokeObjectURL(url)
}
const showError = computed(() => !!error.value)

const record = computed(() => detail.value?.record || null)
const modelPreview = computed(() => record.value?.model_preview || {})
const health = computed(() => detail.value?.health || {})
const lineageSummary = computed(() => detail.value?.lineage?.summary || {})
const lineageRootLabel = computed(() => detail.value?.lineage?.source_hierarchy?.filename || record.value?.source_file_name || 'Unavailable')
const latestConceptRecordLabel = computed(() => {
  const latest = detail.value?.lineage?.latest_same_concept
  if (!latest?.record_id) return 'No published sibling'
  return `#${latest.record_id} · v${latest.version || 'n/a'}`
})
const zenodoSummary = computed(() => detail.value?.zenodo_status?.summary || {})
const zenodoCommunitiesLabel = computed(() => {
  const communities = detail.value?.zenodo_status?.communities || []
  if (!communities.length) return 'None'
  return communities.map((item) => item?.identifier || item?.id || 'unknown').join(', ')
})
const zenodoActionLabels = computed(() => ({
  'Create Draft': !!detail.value?.zenodo_status?.actions?.can_create_draft,
  'Discard Draft': !!detail.value?.zenodo_status?.actions?.can_discard_draft,
  'Upload Files': !!detail.value?.zenodo_status?.actions?.can_upload_files,
  Publish: !!detail.value?.zenodo_status?.actions?.can_publish,
}))
const metadataValidationReports = computed(() => {
  const files = [
    ...(record.value?.files || []),
    ...(detail.value?.lineage?.traceability?.files || []),
  ]
  const seen = new Set()
  return files
    .map((file) => {
      const report = file?.validation_report_json || {}
      if (!report || typeof report !== 'object' || !Object.keys(report).length) {
        return null
      }
      const key = `${file.file_id || ''}:${file.filename || file.relative_path || file.absolute_path || ''}`
      if (seen.has(key)) {
        return null
      }
      seen.add(key)
      const errors = Array.isArray(report.errors) ? report.errors : []
      const warnings = Array.isArray(report.warnings) ? report.warnings : []
      const steps = Array.isArray(report.steps) ? report.steps : []
      const failingSteps = steps.filter((step) => step?.valid === false || step?.passed === false)
      const warningSteps = steps.filter((step) => Array.isArray(step?.warnings) && step.warnings.length)
      const valid = report.valid ?? report.is_valid
      return {
        fileId: file.file_id || file.filename || file.relative_path || file.absolute_path,
        filename: file.filename || file.relative_path || file.absolute_path || 'Validation report',
        relativePath: file.relative_path || file.mapped_file_path,
        absolutePath: file.absolute_path,
        report,
        valid,
        statusLabel: valid === false ? 'Validation issues' : 'Valid',
        validatorLabel: report.validator || report.validator_name || report.service || report.source || 'Local EDM Validator',
        profileLabel: report.profile || report.schema || report.format || 'EDM',
        errorCount: Number(report.error_count ?? errors.length + failingSteps.length) || 0,
        warningCount: Number(report.warning_count ?? warnings.length + warningSteps.length) || 0,
      }
    })
    .filter(Boolean)
})

const formatJson = (value) => {
  try {
    return JSON.stringify(value || {}, null, 2)
  } catch {
    return String(value)
  }
}

const formatBytes = (bytes) => {
  if (!bytes || Number.isNaN(Number(bytes))) return 'N/A'
  const value = Number(bytes)
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${(value / 1024 ** 3).toFixed(2)} GB`
}

const statusColor = (status) => {
  if (status === 'published') return 'text-emerald-700'
  if (status === 'draft') return 'text-amber-700'
  return 'text-slate-800'
}

const yesNo = (condition) => (condition ? 'Yes' : 'No')

const previewReasonLabel = (reason) => ({
  inline_preview_unsupported_format: 'This 3D format falls back to direct file access.',
  record_not_published: 'Only public published Zenodo record files are previewed inline.',
  missing_zenodo_record_id: 'No Zenodo record ID is available for a public direct file URL.',
  missing_model_file: 'No previewable model file is listed in the record metadata.',
  missing_valid_zenodo_direct_url: 'No public Zenodo direct file URL could be resolved.',
  not_3d_record: 'This record is not classified as a 3D asset.',
}[reason] || 'Preview unavailable.')

const downloadJson = () => {
  if (!detail.value) return
  const blob = new Blob([JSON.stringify(detail.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `session_${route.params.sessionId}_record_${route.params.recordId}.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const loadDetail = async () => {
  const sessionId = Number(route.params.sessionId)
  const recordId = Number(route.params.recordId)
  const detailResponse = await submissionService.getSessionRecordDetail(sessionId, recordId)
  detail.value = detailResponse.data
  await loadLod(false)
}

const createVersion = async () => {
  const sessionId = Number(route.params.sessionId)
  const recordId = Number(route.params.recordId)
  if (!window.confirm(`Create a new Zenodo version draft for "${record.value?.record_title || record.value?.source_file_name}" using the complete local file set?`)) {
    return
  }

  versioning.value = true
  try {
    const response = await submissionService.createSessionRecordVersion(sessionId, recordId, { publish: false })
    const newLocalRecordId = response.data?.new_version?.new_local_record_id
    toast.success(newLocalRecordId ? `New version draft created as local record #${newLocalRecordId}` : 'New version draft created')
    await loadDetail()
  } catch (err) {
    console.error('Failed to create new version:', err)
    toast.error(err.error?.message || err.error || err.message || 'Failed to create new Zenodo version')
  } finally {
    versioning.value = false
  }
}

onMounted(async () => {
  try {
    await loadDetail()
  } catch (err) {
    console.error('Failed to load record detail:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load record detail.'
  } finally {
    loading.value = false
  }
})

watch(
  () => modelPreview.value?.url,
  () => {
    previewLoaded.value = false
  }
)
</script>
