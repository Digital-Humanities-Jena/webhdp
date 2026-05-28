<template>
  <section class="mt-5 rounded-2xl border border-white bg-white p-4 shadow-sm">
    <div class="flex items-center justify-between">
      <div>
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Output Mapping</h3>
        <p class="mt-1 text-sm text-slate-500">
          Structured outputs can map into publication and EDM metadata fields. Other output actions stay in advanced JSON.
        </p>
      </div>
      <button
        v-if="getJsonOutputs().length > 0"
        type="button"
        class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
        :data-testid="`output-mapping-manage-${step.id}`"
        @click="actions.openOutputMappingModal(step)"
      >
        Manage Mappings
      </button>
    </div>
    <div v-if="getJsonOutputs().length === 0" class="mt-4 rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
      This component does not expose structured outputs for metadata mapping.
    </div>
    <div v-else-if="step.outputMappings.length === 0" class="mt-4 rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
      No structured output mappings yet.
    </div>
    <div v-else class="mt-4 space-y-3">
      <div
        v-for="mapping in step.outputMappings"
        :key="mapping.localKey"
        class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600"
      >
        <div class="font-medium text-slate-900">{{ mapping.source_output }} -> {{ mapping.target_field }}</div>
        <div class="mt-1">Selector: {{ mapping.selector || 'entire output' }}</div>
        <div class="mt-1">Transform: {{ mapping.transform || 'identity' }} | Policy: {{ mapping.overwrite_policy || 'overwrite' }}</div>
      </div>
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  step: {
    type: Object,
    required: true,
  },
  helpers: {
    type: Object,
    required: true,
  },
  actions: {
    type: Object,
    required: true,
  },
})

function getJsonOutputs() {
  return props.helpers.getJsonOutputs(props.step)
}
</script>
