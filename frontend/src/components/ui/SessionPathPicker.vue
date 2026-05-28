<template>
  <div v-if="items.length > 0" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div class="text-sm font-medium text-slate-900">{{ title }}</div>
        <div v-if="description" class="mt-1 text-xs text-slate-500">{{ description }}</div>
      </div>
      <div v-if="bulkActions.length > 0" class="flex flex-wrap gap-2">
        <button
          v-for="action in bulkActions"
          :key="action.id"
          type="button"
          class="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-white disabled:opacity-50"
          :disabled="filteredItems.length === 0"
          :data-testid="buildTestId(`bulk-${action.id}`)"
          @click="$emit('bulk-action', { id: action.id, items: filteredItems })"
        >
          {{ action.label }}
        </button>
      </div>
    </div>

    <div class="mt-3">
      <input
        v-model.trim="searchText"
        type="text"
        class="block w-full rounded-xl border-slate-300 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
        :placeholder="searchPlaceholder"
        :data-testid="buildTestId('search')"
      >
      <div class="mt-2 text-xs text-slate-500">
        {{ filteredItems.length }} matching {{ filteredLabel }}
      </div>
    </div>

    <div v-if="filteredItems.length === 0" class="mt-3 rounded-xl border border-dashed border-slate-300 px-3 py-6 text-center text-xs text-slate-500">
      {{ emptyFilterText }}
    </div>

    <div v-else class="mt-3 max-h-56 space-y-2 overflow-y-auto pr-1">
      <button
        v-for="(item, index) in filteredItems"
        :key="`${dataTestidPrefix || title}-${item}`"
        type="button"
        class="flex w-full items-start justify-between gap-3 rounded-xl border px-3 py-2 text-left text-xs transition"
        :class="isSelected(item) ? selectedClass : unselectedClass"
        :data-testid="buildTestId(`item-${index}`)"
        @click="handleItemClick(item)"
      >
        <span class="break-all">{{ item }}</span>
        <span class="shrink-0 font-semibold">{{ isSelected(item) ? selectedActionLabel : itemActionLabel }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  title: {
    type: String,
    default: 'Session Paths',
  },
  description: {
    type: String,
    default: '',
  },
  items: {
    type: Array,
    default: () => [],
  },
  selectionMode: {
    type: String,
    default: 'single',
    validator: (value) => ['single', 'multiple'].includes(value),
  },
  selectedItem: {
    type: String,
    default: '',
  },
  selectedItems: {
    type: Array,
    default: () => [],
  },
  itemLabel: {
    type: String,
    default: 'paths',
  },
  itemActionLabel: {
    type: String,
    default: 'Use',
  },
  selectedActionLabel: {
    type: String,
    default: 'Selected',
  },
  searchPlaceholder: {
    type: String,
    default: 'Filter session paths',
  },
  bulkActions: {
    type: Array,
    default: () => [],
  },
  dataTestidPrefix: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['select', 'toggle', 'bulk-action'])

const searchText = ref('')

const filteredItems = computed(() => {
  const query = String(searchText.value || '').trim().toLowerCase()
  if (!query) {
    return props.items
  }
  return props.items.filter((item) => String(item || '').toLowerCase().includes(query))
})

const filteredLabel = computed(() => {
  const base = props.itemLabel || 'paths'
  return filteredItems.value.length === 1 ? base.replace(/s$/, '') : base
})

const emptyFilterText = computed(() => {
  if (searchText.value) {
    return `No ${props.itemLabel} match the current filter.`
  }
  return `No ${props.itemLabel} are available in this session.`
})

const selectedClass = 'border-indigo-300 bg-indigo-50 text-indigo-700'
const unselectedClass = 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'

function buildTestId(suffix) {
  return props.dataTestidPrefix ? `${props.dataTestidPrefix}-${suffix}` : undefined
}

function isSelected(item) {
  if (props.selectionMode === 'multiple') {
    return props.selectedItems.includes(item)
  }
  return props.selectedItem === item
}

function handleItemClick(item) {
  if (props.selectionMode === 'multiple') {
    emit('toggle', item)
    return
  }
  emit('select', item)
}
</script>
