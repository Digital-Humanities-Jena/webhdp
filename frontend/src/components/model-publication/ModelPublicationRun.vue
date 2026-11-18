<template>
  <div class="space-y-4">
    <section class="overflow-hidden rounded-xl border border-slate-200 bg-white" aria-labelledby="model-publication-result">
      <div class="flex flex-wrap items-start gap-4 p-4 sm:p-6">
        <div class="min-w-0 flex-1 basis-60">
          <p class="text-sm font-semibold" :class="job.status === 'failed' ? 'text-rose-800' : 'text-teal-800'">{{ statusText }}</p>
          <h2 id="model-publication-result" tabindex="-1" class="mt-1 break-words text-2xl font-semibold tracking-tight">
            {{ job.draft?.title || job.title || 'Your model' }}
          </h2>
          <p aria-live="polite" class="mt-2 text-sm leading-6 text-slate-700">
            {{ progressText }}
          </p>
          <p v-if="job.status === 'running' && job.detail" class="mt-1 text-xs font-medium text-slate-600">{{ job.detail }}</p>
          <div v-if="refreshError" role="status" class="mt-3 rounded-md bg-amber-50 p-3 text-sm text-amber-950">
            {{ refreshError }}
            <button type="button" class="ml-1 font-semibold underline" @click="$emit('refresh')">Check now</button>
          </div>
          <p v-if="job.status === 'failed' && errorMessage" role="alert" class="mt-3 rounded-md bg-rose-50 p-3 text-sm text-rose-900">
            {{ errorMessage }}
          </p>
        </div>
        <img v-if="job.sample_id && !previewFailed" :src="sampleUrl(job.sample_id, true)" alt="Sample model illustration"
          class="aspect-video w-40 max-w-full rounded-lg bg-slate-100 object-cover" @error="previewFailed = true" />
      </div>
      <ol v-if="job.status !== 'failed'" class="grid gap-2 border-t border-slate-200 bg-slate-50 p-4 sm:grid-cols-3 sm:px-6" aria-label="Processing stages">
        <li v-for="(step, index) in steps" :key="step"
          class="flex items-center gap-2 text-sm"
          :aria-current="index === currentStep ? 'step' : undefined"
          :class="index <= currentStep ? 'font-semibold text-slate-900' : 'text-slate-600'">
          <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs"
            :class="index < currentStep
              ? 'border-teal-200 bg-teal-50 text-teal-800'
              : index === currentStep
                ? 'border-indigo-200 bg-indigo-50 text-indigo-800'
                : 'border-slate-200 bg-white text-slate-600'">
            <CheckIcon v-if="index < currentStep" class="h-4 w-4" aria-hidden="true" />
            <span v-else aria-hidden="true">{{ index + 1 }}</span>
          </span>
          <span v-if="index < currentStep" class="sr-only">Completed</span>
          {{ step }}
        </li>
      </ol>
    </section>

    <section v-if="job.draft" aria-labelledby="draft-heading" class="rounded-xl border border-teal-200 bg-teal-50 p-4 text-teal-950 sm:p-6">
      <h3 id="draft-heading" class="text-lg font-semibold">Zenodo Sandbox draft</h3>
      <p class="mt-1 text-sm">
        Draft {{ job.draft.id }} · {{ draftFileCount }} {{ draftFileCount === 1 ? 'file' : 'files' }} uploaded
      </p>
      <a v-if="demoAccount && previewUrl" :href="previewUrl" target="_blank" rel="noopener noreferrer"
        class="mt-2 inline-flex items-center gap-1 rounded-md bg-white px-3 py-2 text-sm font-semibold text-teal-900 hover:underline">
        Preview this draft in Zenodo Sandbox
        <ArrowTopRightOnSquareIcon aria-hidden="true" class="h-4 w-4" />
      </a>
      <p v-else-if="demoAccount" class="mt-2 text-sm leading-6">The Sandbox owner can open this draft. Your files and repairs are available here in WebHDP.</p>
      <a v-else-if="draftUrl" :href="draftUrl" target="_blank" rel="noopener noreferrer"
        class="mt-2 inline-flex items-center gap-1 rounded-md bg-white px-3 py-2 text-sm font-semibold text-teal-900 hover:underline">
        Open private draft in Zenodo Sandbox
        <ArrowTopRightOnSquareIcon aria-hidden="true" class="h-4 w-4" />
      </a>
      <p v-if="!demoAccount && draftUrl" class="mt-2 text-xs text-teal-900">Sign in to Sandbox with the account that owns the draft.</p>
      <p v-if="publishedExample" class="mt-2">
        <a :href="publishedExample" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-sm font-semibold underline underline-offset-4">
          View a published Sandbox example
          <ArrowTopRightOnSquareIcon aria-hidden="true" class="h-4 w-4" />
        </a>
      </p>
    </section>

    <section v-if="job.metadata" aria-labelledby="mapped-metadata-heading" class="rounded-xl border border-slate-200 bg-white p-4 sm:p-6">
      <h3 id="mapped-metadata-heading" class="text-lg font-semibold">Metadata used in this draft</h3>
      <dl class="mt-3 grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt class="font-semibold text-slate-800">Source</dt>
          <dd class="mt-1 text-slate-700">{{ job.metadata.source === 'msf' ? 'Metadata spreadsheet (MSF)' : 'Entered in WebHDP' }}</dd>
        </div>
        <div v-if="job.metadata.title">
          <dt class="font-semibold text-slate-800">Title</dt>
          <dd class="mt-1 break-words text-slate-700">{{ job.metadata.title }}</dd>
        </div>
        <div v-if="creatorNames">
          <dt class="font-semibold text-slate-800">Creators</dt>
          <dd class="mt-1 break-words text-slate-700">{{ creatorNames }}</dd>
        </div>
        <div v-if="job.metadata.license">
          <dt class="font-semibold text-slate-800">License</dt>
          <dd class="mt-1 text-slate-700">{{ job.metadata.license === 'cc0-1.0' ? 'CC0 1.0' : job.metadata.license }}</dd>
        </div>
      </dl>
    </section>

    <section v-if="job.repairs?.length" aria-labelledby="repair-heading" class="rounded-xl border border-slate-200 bg-white p-4 sm:p-6">
      <h3 id="repair-heading" class="text-lg font-semibold">Texture repairs</h3>
      <ul class="mt-3 space-y-3">
        <li v-for="(repair, index) in job.repairs" :key="index" class="break-words rounded-lg bg-slate-50 p-3 text-sm">
          <p class="font-semibold">
            {{ repair.kind === 'relinked' ? 'Texture relinked' : repair.reason === 'unreadable_texture' ? 'Unreadable texture replaced' : 'Material color used' }}
          </p>
          <p v-if="repair.kind === 'relinked'" class="mt-1 text-slate-700">
            <code>{{ repair.reference }}</code> now points to <code>{{ repair.replacement }}</code>.
          </p>
          <p v-else-if="repair.reason === 'unreadable_texture'" class="mt-1 text-slate-700">
            WebHDP could not decode <code>{{ repair.reference }}</code>. The prepared model keeps its material settings and other usable textures.
          </p>
          <p v-else class="mt-1 text-slate-700">
            WebHDP could not find a unique image for <code>{{ repair.reference }}</code>. The prepared model uses a solid material color in its place.
          </p>
        </li>
      </ul>
    </section>

    <section v-if="job.files?.length" aria-labelledby="files-heading" class="rounded-xl border border-slate-200 bg-white p-4 sm:p-6">
      <h3 id="files-heading" class="text-lg font-semibold">Prepared files</h3>
      <ul class="mt-2 divide-y divide-slate-100">
        <li v-for="file in job.files" :key="file.name" class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
          <div class="min-w-0">
            <p class="break-all text-sm font-medium text-slate-900">{{ file.name }}</p>
            <p class="mt-0.5 text-xs text-slate-600">{{ formatLabels[file.format] || file.format }}<span v-if="file.size"> · {{ sizeLabel(file.size) }}</span></p>
          </div>
          <button type="button" :disabled="downloading.includes(file.name)" :aria-label="'Download ' + file.name"
            class="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-sm font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
            @click="download(file.name)">
            <ArrowDownTrayIcon class="h-4 w-4" aria-hidden="true" />
            {{ downloading.includes(file.name) ? 'Downloading…' : 'Download' }}
          </button>
        </li>
      </ul>
      <p v-if="downloadError" role="alert" class="mt-2 text-sm text-rose-900">{{ downloadError }}</p>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ArrowDownTrayIcon, ArrowTopRightOnSquareIcon, CheckIcon } from '@heroicons/vue/24/outline'
import publicationService, { sampleUrl, sandboxDraftPreviewUrl, sandboxDraftUrl } from '@/services/modelPublication.service'

const props = defineProps({
  job: { type: Object, required: true },
  refreshError: { type: String, default: '' },
  publishedExample: { type: String, default: '' },
  demoAccount: { type: Boolean, default: false }
})
defineEmits(['refresh'])

const steps = ['Check and repair model', 'Map metadata and generate files', 'Create Sandbox draft']
const formatLabels = { edm: 'EDM', iiif: 'IIIF', mets: 'METS/MODS', cidoc_crm: 'CIDOC CRM', jsonld: 'JSON-LD' }
const stageIndex = { preparing_model: 0, mapping_metadata: 1, creating_draft: 1, generating_metadata: 1, uploading: 2 }
const currentStep = computed(() => props.job.status === 'completed'
  ? steps.length
  : (props.job.status === 'queued' ? -1 : (stageIndex[props.job.stage] ?? 0)))
const statusText = computed(() => ({
  queued: 'In the queue',
  running: 'Processing model',
  completed: 'Draft ready',
  failed: 'This request needs attention',
}[props.job.status] || 'Waiting for an update'))
const stageText = {
  preparing_model: 'Checking the model and repairing its texture references.',
  mapping_metadata: 'Matching the model to its metadata and validating the description.',
  creating_draft: 'Reserving a Sandbox draft to identify your linked data files.',
  generating_metadata: 'Generating and validating the linked data files.',
  uploading: 'Uploading the prepared files to Zenodo Sandbox.',
}
const progressText = computed(() => {
  if (props.job.status === 'queued') {
    if (props.job.ahead === 0) return 'Your request is next and will start when a worker is free.'
    if (Number.isInteger(props.job.ahead) && props.job.ahead > 0) {
      return `${props.job.ahead} ${props.job.ahead === 1 ? 'request is' : 'requests are'} ahead of yours. WebHDP will start yours automatically.`
    }
    return 'WebHDP accepted your request. Processing will start automatically.'
  }
  if (props.job.status === 'completed') return 'Your model and linked data files are ready to review and download.'
  if (props.job.status === 'failed') return 'Review the details below and prepare another request when ready.'
  return stageText[props.job.stage] || 'WebHDP is preparing your files.'
})
const draftUrl = computed(() => sandboxDraftUrl(props.job.draft?.url))
const previewUrl = computed(() => sandboxDraftPreviewUrl(props.job.draft?.preview_url, props.job.draft?.id))
const draftFileCount = computed(() => Array.isArray(props.job.draft?.files)
  ? props.job.draft.files.length
  : (props.job.draft?.files ?? 0))
const errorMessage = computed(() => typeof props.job.error === 'string' ? props.job.error : props.job.error?.message || '')
const creatorNames = computed(() => props.job.metadata?.creators?.map(creator => creator.name).filter(Boolean).join(', '))
const downloading = ref([])
const downloadError = ref('')
const previewFailed = ref(false)

function sizeLabel(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function download(filename) {
  if (downloading.value.includes(filename)) return
  downloading.value = [...downloading.value, filename]
  downloadError.value = ''
  try {
    const blob = await publicationService.file(props.job.id, filename)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch {
    downloadError.value = `Could not download ${filename}. Try again.`
  } finally {
    downloading.value = downloading.value.filter(name => name !== filename)
  }
}
</script>
