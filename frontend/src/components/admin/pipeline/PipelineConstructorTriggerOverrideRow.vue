<template>
  <div
    class="rounded-2xl border border-slate-200 bg-white p-4"
    :data-testid="`trigger-override-${step.id}-${ruleIndex}-${overrideIndex}`"
  >
    <div class="grid gap-3 md:grid-cols-2">
      <div>
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Parameter</label>
        <select aria-label="Parameter" v-model="overrideRow.name" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" @change="actions.resetParameterOverrideValue(step, overrideRow)">
          <option value="">Select parameter</option>
          <option v-for="field in getAllParameterFields()" :key="field.name" :value="field.name">
            {{ field.label }}
          </option>
        </select>
      </div>
      <div>
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Value</label>
        <template v-if="getParameterField(overrideRow.name)">
          <PlaygroundFieldRenderer
            :field="getParameterField(overrideRow.name)"
            :model-value="overrideRow.value"
            :session-id="preflightSessionId"
            :suggested-files="constructorSessionFiles"
            :suggested-directories="constructorSessionDirectories"
            compact
            @update:model-value="overrideRow.value = $event"
          />
        </template>
      </div>
    </div>
    <div class="mt-3 text-right">
      <button type="button" class="rounded-xl border border-rose-300 bg-white px-3 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50" @click="actions.removeParameterOverride(rule, overrideIndex)">
        Remove Override
      </button>
    </div>
  </div>
</template>

<script setup>
import PlaygroundFieldRenderer from '@/components/tools/playground/PlaygroundFieldRenderer.vue'

const props = defineProps({
  step: {
    type: Object,
    required: true,
  },
  rule: {
    type: Object,
    required: true,
  },
  ruleIndex: {
    type: Number,
    required: true,
  },
  overrideRow: {
    type: Object,
    required: true,
  },
  overrideIndex: {
    type: Number,
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

function getAllParameterFields() {
  return props.helpers.getAllParameterFields(props.step)
}

function getParameterField(fieldName) {
  return props.helpers.getParameterField(props.step, fieldName)
}
</script>
