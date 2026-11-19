<template>
  <button type="button" aria-haspopup="dialog"
    class="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-indigo-800 hover:bg-indigo-50"
    @click="dialog.showModal()">
    {{ repairOnly ? 'Inspect texture repairs' : 'Pipeline details' }}
  </button>
  <Teleport to="body">
    <dialog ref="dialog" :aria-label="repairOnly ? 'Texture repair details' : 'Model publication pipeline'"
      class="m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto overscroll-contain rounded-xl bg-white p-0 text-slate-900 shadow-xl backdrop:bg-slate-950/50"
      @click.self="dialog.close()">
      <div class="sticky top-0 z-10 flex items-start justify-between gap-4 border-b bg-white px-5 py-4">
        <div>
          <h2 class="text-lg font-semibold">{{ repairOnly ? 'Texture repair details' : 'Model publication pipeline' }}</h2>
          <p v-if="job?.model" class="mt-1 break-all text-sm text-slate-600">{{ job.model }}</p>
        </div>
        <button type="button" class="rounded-md px-3 py-2 text-sm font-semibold text-indigo-800 hover:bg-indigo-50" autofocus
          @click="dialog.close()">Close</button>
      </div>
      <div class="space-y-5 p-5 text-sm">
        <ol v-if="!repairOnly" class="space-y-3">
          <li v-for="(step, index) in steps" :key="step.title" class="rounded-lg border border-slate-200 p-3">
            <div class="flex flex-wrap justify-between gap-1">
              <h3 class="font-semibold">{{ index + 1 }}. {{ step.title }}</h3>
              <span v-if="job?.status" class="text-xs font-medium text-slate-600">{{ state(index) }}</span>
            </div>
            <p class="mt-1 text-slate-600">{{ step.description }}</p>
          </li>
        </ol>
        <div v-if="job?.model">
          <h3 v-if="!repairOnly" class="font-semibold">Repair report</h3>
          <p v-if="!job.repairs?.length" class="mt-2 text-slate-700">No texture changes were needed.</p>
          <dl v-for="(repair, index) in job.repairs" :key="index" class="mt-2 rounded-lg bg-slate-50 p-3">
            <dt class="font-semibold">{{ repair.kind === 'relinked' ? 'Relinked texture' : 'Omitted texture reference' }}</dt>
            <dd class="mt-1 break-all text-slate-700"><code>{{ repair.reference }}</code></dd>
            <dd v-if="repair.replacement" class="mt-1 break-all text-slate-700">
              File used <code>{{ repair.replacement }}</code>
            </dd>
            <dd v-else class="mt-1 text-slate-700">
              {{ repair.reason === 'unreadable_texture' ? 'The image could not be decoded.' : 'No unique matching image was found.' }}
              The model keeps its material and usable textures.
            </dd>
          </dl>
          <details v-if="job.source_files?.length" class="mt-4">
            <summary class="cursor-pointer font-semibold">Files used to prepare the model</summary>
            <ul class="mt-2 space-y-1 text-slate-700">
              <li v-for="source in job.source_files" :key="source" class="break-all"><code>{{ source }}</code></li>
            </ul>
          </details>
        </div>
        <p v-if="!repairOnly && job?.metadata?.model_path" class="break-all text-slate-700">
          Matched <code>{{ job.metadata.model_path }}</code><template v-if="job.metadata.spreadsheet"> to its row in <code>{{ job.metadata.spreadsheet }}</code></template>.
        </p>
        <p v-if="job?.status === 'failed' && job.error" class="text-rose-900">{{ job.error }}</p>
      </div>
    </dialog>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  job: { type: Object, default: null },
  repairOnly: { type: Boolean, default: false },
})
const dialog = ref(null)
const steps = [
  { title: 'Check the source model', description: 'Read the geometry and included assets. Resolve misplaced or misnamed texture references and omit unreadable images.' },
  { title: 'Export a model and match its metadata', description: 'Write a self-contained GLB, then match the source filename to the spreadsheet row.' },
  { title: 'Validate metadata files', description: 'Generate Europeana EDM, IIIF, METS/MODS, CIDOC-CRM RDF/XML and JSON-LD.' },
  { title: 'Create a reviewable Sandbox draft', description: 'Upload the GLB and its metadata files, then verify each attachment against the local file.' },
]
const stages = { preparing_model: 0, mapping_metadata: 1, creating_draft: 2, generating_metadata: 2, uploading: 3 }
function state(index) {
  const job = props.job
  if (job.status === 'completed') return 'Completed'
  if (job.status === 'queued') return 'Waiting'
  if (job.status === 'failed') return 'See error'
  const active = stages[job.stage] ?? 0
  return index === active ? 'In progress' : index < active ? 'Completed' : 'Waiting'
}
</script>
