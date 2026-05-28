<template>
  <div class="space-y-3">
    <textarea
      :value="modelValue"
      rows="5"
      class="block w-full rounded-xl border-slate-300 font-mono text-xs text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
      :placeholder="field.placeholder || '/absolute/path/to/file.glb'"
      @input="$emit('update:modelValue', $event.target.value)"
    />

    <SessionPathPicker
      v-if="filteredFiles.length > 0"
      title="Session Files"
      description="Filter and toggle matching files into the manifest-backed list."
      :items="filteredFiles"
      :selected-items="parseLines()"
      item-label="files"
      selection-mode="multiple"
      item-action-label="Add"
      selected-action-label="Added"
      search-placeholder="Filter session files"
      :bulk-actions="bulkActions"
      :data-testid-prefix="`session-file-list-${field.name}`"
      @toggle="toggleFile"
      @bulk-action="handleBulkAction"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import SessionPathPicker from '@/components/ui/SessionPathPicker.vue'
import { filterSessionPathsForField } from '@/utils/playgroundManifest'

const props = defineProps({
  field: {
    type: Object,
    required: true
  },
  modelValue: {
    type: String,
    default: ''
  },
  suggestedFiles: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:modelValue'])

const filteredFiles = computed(() => filterSessionPathsForField(props.field, props.suggestedFiles))
const bulkActions = [
  { id: 'append_all_matching', label: 'Append All Matching' },
  { id: 'replace_all_matching', label: 'Replace With Matching' },
]

function parseLines() {
  return String(props.modelValue || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

function toggleFile(path) {
  const values = new Set(parseLines())
  if (values.has(path)) {
    values.delete(path)
  } else {
    values.add(path)
  }
  emit('update:modelValue', Array.from(values).join('\n'))
}

function appendFiles(paths) {
  const values = new Set(parseLines())
  paths.forEach((path) => values.add(path))
  emit('update:modelValue', Array.from(values).join('\n'))
}

function replaceWithFiles(paths) {
  emit('update:modelValue', paths.join('\n'))
}

function handleBulkAction({ id, items }) {
  if (id === 'append_all_matching') {
    appendFiles(items)
    return
  }
  if (id === 'replace_all_matching') {
    replaceWithFiles(items)
  }
}
</script>
