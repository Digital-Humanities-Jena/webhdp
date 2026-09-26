<template>
  <div
    class="rounded-2xl border border-slate-200 bg-white p-4"
    :data-testid="`trigger-condition-${step.id}-${ruleIndex}-${conditionIndex}`"
  >
    <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <div>
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Source</label>
        <select aria-label="Source" v-model="condition.source_type" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" @change="actions.handleTriggerSourceTypeChange(condition)">
          <option value="file_fact">File property</option>
          <option value="classifier_output">Classification result</option>
        </select>
      </div>

      <div v-if="condition.source_type === 'classifier_output'">
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Classifier Step</label>
        <select aria-label="Classifier Step" v-model="condition.source_step" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" @change="actions.handleTriggerSourceStepChange(step, condition)">
          <option value="">Select step</option>
          <option v-for="option in getEarlierClassifierStepOptions()" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>

      <div v-if="condition.source_type === 'classifier_output'">
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Output</label>
        <select aria-label="Output" v-model="condition.source_output" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
          <option value="">Select output</option>
          <option v-for="option in getClassifierOutputOptions(condition.source_step)" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>

      <div>
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Field</label>
        <select aria-label="Field" v-model="condition.field" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
          <option value="">Select field</option>
          <option v-for="option in getTriggerFieldOptions(condition)" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </div>

      <div>
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Operator</label>
        <select aria-label="Operator" v-model="condition.operator" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
          <option v-for="option in getTriggerOperatorOptions(condition)" :key="option.id" :value="option.id">
            {{ option.label }}
          </option>
        </select>
      </div>
    </div>

    <div v-if="!['exists', 'truthy'].includes(condition.operator)" class="mt-3">
      <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Value</label>
      <div v-if="condition.operator === 'between'" class="grid gap-3 md:grid-cols-2">
        <input aria-label="Minimum value" v-model="condition.value_from" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" placeholder="From">
        <input aria-label="Maximum value" v-model="condition.value_to" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" placeholder="To">
      </div>
      <input
        v-else
        v-model="condition.value_text"
        aria-label="Condition value"
        type="text"
        class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
        :placeholder="condition.operator === 'in' || condition.operator === 'not_in' ? 'Comma-separated values' : 'Value'"
      >
    </div>

    <div class="mt-3 text-right">
      <button type="button" class="rounded-xl border border-rose-300 bg-white px-3 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50" @click="actions.removeTriggerCondition(rule, conditionIndex)">
        Remove Condition
      </button>
    </div>
  </div>
</template>

<script setup>
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
  condition: {
    type: Object,
    required: true,
  },
  conditionIndex: {
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
})

function getEarlierClassifierStepOptions() {
  return props.helpers.getEarlierClassifierStepOptions(props.step)
}

function getClassifierOutputOptions(sourceStepId) {
  return props.helpers.getClassifierOutputOptions(sourceStepId)
}

function getTriggerFieldOptions(condition) {
  return props.helpers.getTriggerFieldOptions(props.step, condition)
}

function getTriggerOperatorOptions(condition) {
  return props.helpers.getTriggerOperatorOptions(condition)
}
</script>
