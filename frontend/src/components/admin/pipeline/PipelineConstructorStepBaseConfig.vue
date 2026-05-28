<template>
  <section class="mt-5 rounded-2xl border border-white bg-white p-4 shadow-sm">
    <div class="flex items-center justify-between">
      <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Base Config</h3>
      <span class="text-xs text-slate-500">Reused Playground widgets</span>
    </div>
    <div v-if="getParameterGroups().length === 0" class="mt-4 rounded-2xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
      This component does not expose configurable parameters.
    </div>
    <div v-else class="mt-4 space-y-4">
      <section
        v-for="group in getParameterGroups()"
        :key="`${step.localKey}-${group.title}`"
        class="rounded-xl border border-slate-200 bg-slate-50 p-4"
      >
        <div class="mb-4">
          <h4 class="text-sm font-semibold text-slate-900">{{ group.title }}</h4>
          <p v-if="group.description" class="mt-1 text-sm text-slate-500">{{ group.description }}</p>
        </div>
        <div class="space-y-3">
          <PlaygroundFieldRenderer
            v-for="field in group.fields"
            :key="`${step.localKey}-${field.name}`"
            :field="field"
            :model-value="step.parameterForm[field.name]"
            :session-id="preflightSessionId"
            :suggested-files="constructorSessionFiles"
            :suggested-directories="constructorSessionDirectories"
            compact
            @update:model-value="actions.updateParameterValue(step, field.name, $event)"
          />
        </div>
      </section>
    </div>
  </section>
</template>

<script setup>
import PlaygroundFieldRenderer from '@/components/tools/playground/PlaygroundFieldRenderer.vue'

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
  preflightSessionId: {
    type: String,
    required: true,
  },
  constructorSessionFiles: {
    type: Array,
    required: true,
  },
  constructorSessionDirectories: {
    type: Array,
    required: true,
  },
})

function getParameterGroups() {
  return props.helpers.getParameterGroups(props.step)
}
</script>
