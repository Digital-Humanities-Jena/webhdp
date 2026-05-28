<template>
  <div class="min-h-screen bg-gradient-to-b from-emerald-50 via-white to-slate-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <router-link
            :to="`/sessions/${route.params.sessionId}/records`"
            class="text-sm font-medium text-indigo-600 hover:text-indigo-800"
          >
            &larr; Back to Session Records
          </router-link>
          <h1 class="mt-2 text-3xl font-bold text-slate-900">Session Provenance Report</h1>
          <p class="mt-1 text-sm text-slate-600">Session #{{ route.params.sessionId }}</p>
        </div>

        <div class="flex gap-2">
          <button
            type="button"
            class="px-3 py-2 text-sm font-medium border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50"
            @click="downloadJson"
            :disabled="!payload"
          >
            Export JSON
          </button>
          <button
            type="button"
            class="px-3 py-2 text-sm font-medium border border-emerald-200 rounded-lg text-emerald-700 hover:bg-emerald-50"
            @click="copySummary"
            :disabled="!payload"
          >
            Copy Summary
          </button>
        </div>
      </div>

      <LoadingSpinner v-if="loading" size="lg" text="Building provenance report..." />

      <div v-else-if="error" class="bg-white rounded-xl border border-rose-200 p-6">
        <Alert v-model="showError" variant="error" :message="error" :dismissible="false" />
      </div>

      <div v-else-if="payload" class="space-y-6">
        <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div class="bg-white rounded-xl border border-slate-200 p-4">
            <p class="text-xs uppercase tracking-wide text-slate-500">Records</p>
            <p class="text-2xl font-bold text-slate-900">{{ report.records_total || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-indigo-200 p-4">
            <p class="text-xs uppercase tracking-wide text-indigo-600">Mapped Records</p>
            <p class="text-2xl font-bold text-indigo-700">{{ report.records_with_mapped_metadata || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-cyan-200 p-4">
            <p class="text-xs uppercase tracking-wide text-cyan-600">Lineage Records</p>
            <p class="text-2xl font-bold text-cyan-700">{{ report.records_with_pipeline_lineage || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-rose-200 p-4">
            <p class="text-xs uppercase tracking-wide text-rose-600">Records With Errors</p>
            <p class="text-2xl font-bold text-rose-700">{{ report.records_with_errors || 0 }}</p>
          </div>
          <div class="bg-white rounded-xl border border-emerald-200 p-4">
            <p class="text-xs uppercase tracking-wide text-emerald-600">Generated</p>
            <p class="text-sm font-semibold text-emerald-700 mt-2">{{ formatDate(report.generated_at) }}</p>
          </div>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <section class="bg-white rounded-xl border border-slate-200 p-5">
            <h2 class="text-sm font-semibold text-slate-900">Overview</h2>
            <div class="mt-3 text-sm space-y-2">
              <p><span class="text-slate-500">MSF Path:</span> <span class="font-medium text-slate-800 break-all">{{ provenanceOverview.msf_path || 'Not set' }}</span></p>
              <p><span class="text-slate-500">Mapping Fields:</span> <span class="font-medium text-slate-800">{{ provenanceOverview.mapping_field_count || 0 }}</span></p>
              <p><span class="text-slate-500">Batch Metadata Files:</span> <span class="font-medium text-slate-800">{{ provenanceOverview.batch_metadata_file_count || 0 }}</span></p>
            </div>
            <div v-if="provenanceOverview.mapping_fields?.length" class="mt-3 flex flex-wrap gap-2">
              <span
                v-for="field in provenanceOverview.mapping_fields.slice(0, 10)"
                :key="field"
                class="px-2 py-1 text-xs rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100"
              >
                {{ field }}
              </span>
            </div>
          </section>

          <section class="bg-white rounded-xl border border-slate-200 p-5 xl:col-span-2">
            <h2 class="text-sm font-semibold text-slate-900">Status Distribution</h2>
            <div class="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3">
              <div
                v-for="(count, status) in report.status_distribution || {}"
                :key="status"
                class="p-3 rounded-lg border border-slate-200 bg-slate-50"
              >
                <p class="text-xs uppercase tracking-wide text-slate-500">{{ status }}</p>
                <p class="text-xl font-bold text-slate-900">{{ count }}</p>
              </div>
            </div>
          </section>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <section class="bg-white rounded-xl border border-slate-200 p-5">
            <h2 class="text-sm font-semibold text-slate-900">Top Mapped Fields</h2>
            <div v-if="!(report.mapped_fields?.length)" class="mt-3 text-sm text-slate-500">No mapped fields found.</div>
            <ul v-else class="mt-3 divide-y divide-slate-100 border border-slate-200 rounded-lg overflow-hidden">
              <li v-for="field in report.mapped_fields.slice(0, 20)" :key="field.field" class="p-3 flex items-center justify-between gap-2">
                <span class="text-sm text-slate-800 break-all">{{ field.field }}</span>
                <span class="text-xs font-semibold text-indigo-700 bg-indigo-50 border border-indigo-100 px-2 py-1 rounded-full">{{ field.record_count }}</span>
              </li>
            </ul>
          </section>

          <section class="bg-white rounded-xl border border-slate-200 p-5">
            <h2 class="text-sm font-semibold text-slate-900">Pipeline Lineage Frequency</h2>
            <div v-if="!(report.pipeline_lineage?.length)" class="mt-3 text-sm text-slate-500">No lineage entries found.</div>
            <ul v-else class="mt-3 divide-y divide-slate-100 border border-slate-200 rounded-lg overflow-hidden">
              <li
                v-for="lineage in report.pipeline_lineage.slice(0, 20)"
                :key="`${lineage.pipeline}-${lineage.step}`"
                class="p-3 flex items-center justify-between gap-2"
              >
                <span class="text-sm text-slate-800">{{ lineage.pipeline }} / {{ lineage.step }}</span>
                <span class="text-xs font-semibold text-cyan-700 bg-cyan-50 border border-cyan-100 px-2 py-1 rounded-full">{{ lineage.occurrences }}</span>
              </li>
            </ul>
          </section>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <section class="bg-white rounded-xl border border-slate-200 p-5">
            <h2 class="text-sm font-semibold text-slate-900">File Type Distribution</h2>
            <ul class="mt-3 divide-y divide-slate-100 border border-slate-200 rounded-lg overflow-hidden">
              <li v-for="item in report.file_type_distribution || []" :key="item.file_type" class="p-3 flex items-center justify-between">
                <span class="text-sm text-slate-800">{{ item.file_type }}</span>
                <span class="text-xs font-semibold text-slate-700 bg-slate-100 px-2 py-1 rounded-full">{{ item.count }}</span>
              </li>
            </ul>
          </section>
          <section class="bg-white rounded-xl border border-slate-200 p-5">
            <h2 class="text-sm font-semibold text-slate-900">File Purpose Distribution</h2>
            <ul class="mt-3 divide-y divide-slate-100 border border-slate-200 rounded-lg overflow-hidden">
              <li v-for="item in report.file_purpose_distribution || []" :key="item.file_purpose" class="p-3 flex items-center justify-between">
                <span class="text-sm text-slate-800">{{ item.file_purpose }}</span>
                <span class="text-xs font-semibold text-slate-700 bg-slate-100 px-2 py-1 rounded-full">{{ item.count }}</span>
              </li>
            </ul>
          </section>
        </div>

        <section class="bg-white rounded-xl border border-slate-200 p-5">
          <h2 class="text-sm font-semibold text-slate-900">Record Snapshots</h2>
          <div v-if="!(report.record_snapshots?.length)" class="mt-3 text-sm text-slate-500">No record snapshots found.</div>
          <div v-else class="mt-3 overflow-x-auto">
            <table class="min-w-full divide-y divide-slate-200">
              <thead class="bg-slate-50">
                <tr>
                  <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Local ID</th>
                  <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Title</th>
                  <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Status</th>
                  <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Mapped</th>
                  <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Warnings</th>
                  <th class="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-100 bg-white">
                <tr v-for="snapshot in report.record_snapshots" :key="snapshot.local_record_id">
                  <td class="px-4 py-3 text-sm text-slate-900">{{ snapshot.local_record_id }}</td>
                  <td class="px-4 py-3 text-sm text-slate-700">{{ snapshot.record_title }}</td>
                  <td class="px-4 py-3 text-sm text-slate-700">{{ snapshot.record_status }}</td>
                  <td class="px-4 py-3 text-sm text-slate-700">{{ snapshot.mapping_field_count }}</td>
                  <td class="px-4 py-3 text-sm text-slate-700">
                    <span :class="snapshot.has_error ? 'text-rose-700' : 'text-slate-700'">
                      {{ snapshot.warning_count }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-sm">
                    <router-link
                      :to="`/sessions/${route.params.sessionId}/records/${snapshot.local_record_id}`"
                      class="text-indigo-600 hover:text-indigo-800 font-medium"
                    >
                      Open Detail
                    </router-link>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import submissionService from '@/services/submission.service.js'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import { useToast } from '@/composables/useToast'

const route = useRoute()
const toast = useToast()

const loading = ref(true)
const payload = ref(null)
const error = ref('')
const showError = computed(() => !!error.value)

const report = computed(() => payload.value?.report || {})
const provenanceOverview = computed(() => payload.value?.provenance_overview || {})

const formatDate = (dateString) => {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return Number.isNaN(date.getTime()) ? String(dateString) : date.toLocaleString()
}

const downloadJson = () => {
  if (!payload.value) return
  const blob = new Blob([JSON.stringify(payload.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `session_${route.params.sessionId}_provenance_report.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

const copySummary = async () => {
  if (!payload.value) return
  const lines = [
    `Session ${route.params.sessionId} provenance report`,
    `Generated: ${formatDate(report.value.generated_at)}`,
    `Records total: ${report.value.records_total || 0}`,
    `Records with mapped metadata: ${report.value.records_with_mapped_metadata || 0}`,
    `Records with pipeline lineage: ${report.value.records_with_pipeline_lineage || 0}`,
    `Records with errors: ${report.value.records_with_errors || 0}`,
  ]

  try {
    await navigator.clipboard.writeText(lines.join('\n'))
    toast.success('Provenance summary copied to clipboard')
  } catch {
    toast.error('Could not copy provenance summary')
  }
}

onMounted(async () => {
  try {
    const sessionId = Number(route.params.sessionId)
    const response = await submissionService.getSessionProvenanceReport(sessionId)
    payload.value = response.data
  } catch (err) {
    console.error('Failed to load provenance report:', err)
    error.value = err.error?.message || err.error || err.message || 'Failed to load provenance report.'
  } finally {
    loading.value = false
  }
})
</script>
