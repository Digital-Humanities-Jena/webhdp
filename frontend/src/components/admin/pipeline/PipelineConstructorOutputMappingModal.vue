<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4">
    <div class="max-h-[90vh] w-full max-w-4xl overflow-auto rounded-3xl bg-white p-6 shadow-2xl">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h2 class="text-xl font-semibold text-slate-900">Output Mapping</h2>
          <p class="mt-1 text-sm text-slate-500">
            Map structured outputs from {{ step.name }} into publication and EDM metadata fields.
          </p>
        </div>
        <button type="button" class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="$emit('close')">
          Close
        </button>
      </div>

      <div class="mt-6 flex items-center justify-between">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Mappings</h3>
        <button type="button" class="rounded-xl bg-slate-900 px-3 py-2 text-xs font-medium text-white hover:bg-slate-800" data-testid="output-mapping-add" @click="$emit('add-output-mapping', step)">
          Add Mapping
        </button>
      </div>

      <div v-if="step.outputMappings.length === 0" class="mt-4 rounded-2xl border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">
        No output mappings configured yet.
      </div>

      <div v-else class="mt-4 space-y-4">
        <article
          v-for="(mapping, index) in step.outputMappings"
          :key="mapping.localKey"
          class="rounded-2xl border border-slate-200 bg-slate-50 p-4 transition"
          :class="isDropTarget(mapping) ? 'ring-2 ring-indigo-200 ring-offset-2 ring-offset-white' : ''"
          :data-testid="`output-mapping-row-${index}`"
          @dragover.prevent="$emit('set-output-mapping-drop-target', step, mapping)"
          @drop.prevent="$emit('drop-output-mapping-on', step, mapping)"
        >
          <div class="mb-4 flex items-center gap-2">
            <div
              class="cursor-grab rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-600 shadow-sm active:cursor-grabbing"
              draggable="true"
              :data-testid="`output-mapping-drag-handle-${index}`"
              @dragstart="$emit('start-output-mapping-drag', step, mapping)"
              @dragend="$emit('end-output-mapping-drag')"
            >
              Drag
            </div>
            <span class="inline-flex h-9 min-w-9 items-center justify-center rounded-xl bg-white px-3 text-xs font-semibold text-slate-600">
              {{ index + 1 }}
            </span>
          </div>
          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <div>
              <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Source Output</label>
              <select v-model="mapping.source_output" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
                <option value="">Select output</option>
                <option v-for="output in getJsonOutputs(step)" :key="output.name" :value="output.name">
                  {{ output.label }}
                </option>
              </select>
            </div>
            <div>
              <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Selector</label>
              <input v-model.trim="mapping.selector" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" placeholder="$.path.to.value" />
            </div>
            <div>
              <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Transform</label>
              <select v-model="mapping.transform" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
                <option value="">identity</option>
                <option v-for="transform in supportData.transforms" :key="transform.id" :value="transform.id">
                  {{ transform.id }}
                </option>
              </select>
            </div>
            <div class="md:col-span-2">
              <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Metadata Target Path</label>
              <select v-model="mapping.target_field" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
                <option value="">Select target</option>
                <option v-for="target in targetPaths" :key="`${target.scope || 'metadata'}:${target.path}`" :value="target.path">
                  {{ target.path }} - {{ target.label }}
                </option>
              </select>
            </div>
            <div>
              <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Overwrite Policy</label>
              <select v-model="mapping.overwrite_policy" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
                <option value="">overwrite</option>
                <option v-for="policy in supportData.overwrite_policies" :key="policy.id" :value="policy.id">
                  {{ policy.id }}
                </option>
              </select>
            </div>
          </div>

          <div class="mt-4 flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              :disabled="index === 0"
              :data-testid="`output-mapping-up-${index}`"
              @click="$emit('move-output-mapping', step, index, -1)"
            >
              Up
            </button>
            <button
              type="button"
              class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              :disabled="index === step.outputMappings.length - 1"
              :data-testid="`output-mapping-down-${index}`"
              @click="$emit('move-output-mapping', step, index, 1)"
            >
              Down
            </button>
            <button type="button" class="rounded-xl border border-rose-300 bg-white px-3 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50" @click="$emit('remove-output-mapping', step, index)">
              Remove Mapping
            </button>
          </div>
        </article>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  step: {
    type: Object,
    required: true,
  },
  supportData: {
    type: Object,
    required: true,
  },
  getJsonOutputs: {
    type: Function,
    required: true,
  },
  isDropTarget: {
    type: Function,
    required: true,
  },
})

const targetPaths = computed(() => {
  return props.supportData.metadata_target_paths?.length
    ? props.supportData.metadata_target_paths
    : props.supportData.zenodo_target_paths || []
})

defineEmits([
  'close',
  'add-output-mapping',
  'move-output-mapping',
  'remove-output-mapping',
  'start-output-mapping-drag',
  'set-output-mapping-drop-target',
  'drop-output-mapping-on',
  'end-output-mapping-drag',
])
</script>
