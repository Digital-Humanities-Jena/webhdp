<template>
  <div class="min-w-0 text-sm text-slate-700" data-testid="metadata-review">
    <dl class="space-y-2 break-words">
      <div v-for="field in fields" :key="field.key">
        <dt class="text-xs font-medium text-slate-500">{{ field.label }}<span v-if="provenance[field.key]"> · {{ provenanceLabel(provenance[field.key]) }}</span></dt>
        <dd class="whitespace-pre-wrap">{{ field.value || 'Not supplied' }}</dd>
      </div>
    </dl>
    <details class="mt-3">
      <summary class="cursor-pointer text-xs text-indigo-700">Technical metadata</summary>
      <pre class="mt-2 overflow-auto rounded border bg-white p-3 text-xs">{{ JSON.stringify(metadata, null, 2) }}</pre>
    </details>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { metadataText } from '@/utils/metadataReview'

const props = defineProps({
  metadata: { type: Object, default: () => ({}) },
  provenance: { type: Object, default: () => ({}) },
  sourceName: { type: String, default: '' },
})
const fields = computed(() => [
  { key: 'title', label: 'Title', value: metadataText(props.metadata.title) },
  { key: 'description', label: 'Description', value: metadataText(props.metadata.description) },
  { key: 'creators', label: 'Creators', value: metadataText(props.metadata.creators || props.metadata.creator) },
  { key: 'license', label: 'Rights', value: metadataText(props.metadata.license || props.metadata.rights || props.metadata.edm_rights) },
  { key: 'source', label: 'Source file', value: props.sourceName },
])
function provenanceLabel(value) {
  const entry = typeof value === 'string' ? { source: value } : value
  const labels = { mapped: 'Mapped', entered: 'Entered', inferred: 'Inferred', default: 'Default', shared: 'Shared metadata', batch: 'Record metadata' }
  return [labels[entry.source] || entry.source, entry.field].filter(Boolean).join(' · ')
}
</script>
