<template>
  <section class="mt-5 rounded-2xl border border-white bg-white p-4 shadow-sm">
    <div class="flex items-center justify-between">
      <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Inputs</h3>
      <span class="text-xs text-slate-500">Manifest-defined input mappings</span>
    </div>
    <div class="mt-4 space-y-4">
      <div
        v-for="field in getConstructorInputs()"
        :key="`${step.localKey}-${field.name}`"
        class="rounded-xl border border-slate-200 bg-slate-50 p-4"
      >
        <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div class="flex flex-wrap items-center gap-2">
              <h4 class="text-sm font-semibold text-slate-900">{{ field.label }}</h4>
              <span class="rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600">{{ field.type }}</span>
              <span v-if="field.required" class="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-700">Required</span>
            </div>
            <p v-if="field.description" class="mt-1 text-sm text-slate-500">{{ field.description }}</p>
          </div>
          <label class="inline-flex items-center gap-2 text-xs font-medium text-slate-600">
            <input type="checkbox" v-model="getStepBinding(field.name).enabled" :data-testid="`binding-enabled-${step.id}-${field.name}`">
            Structured mapping
          </label>
        </div>

        <div v-if="getStepBinding(field.name).enabled" class="mt-4 grid gap-3 md:grid-cols-2">
          <div>
            <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Source Kind</label>
            <select
              v-model="getStepBinding(field.name).type"
              class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              :data-testid="`binding-type-${step.id}-${field.name}`"
              @change="actions.handleBindingTypeChange(step, field.name)"
            >
              <option v-for="option in getBindingTypeOptions(field)" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </div>

          <div v-if="bindingNeedsSourceStep(field.name)">
            <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Source Step</label>
            <select
              v-model="getStepBinding(field.name).source_step"
              class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              :data-testid="`binding-source-step-${step.id}-${field.name}`"
              @change="actions.handleBindingSourceStepChange(step, field.name)"
            >
              <option value="">Select step</option>
              <option
                v-for="option in getCompatibleSourceStepOptions(field)"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </option>
            </select>
          </div>

          <div v-if="bindingNeedsSourceOutput(field.name)">
            <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Source Output</label>
            <select
              v-model="getStepBinding(field.name).source_output"
              class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              :data-testid="`binding-source-output-${step.id}-${field.name}`"
            >
              <option value="">Select output</option>
              <option
                v-for="option in getCompatibleSourceOutputOptions(field, getStepBinding(field.name).source_step)"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </option>
            </select>
          </div>

          <div v-if="getStepBinding(field.name).type === 'artifact_json_value'" class="md:col-span-2">
            <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">JSONPath Selector</label>
            <input
              v-model.trim="getStepBinding(field.name).selector"
              type="text"
              class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
              placeholder="$.value.path"
            >
            <p v-if="getCompatibleSelectorExamples(field, getStepBinding(field.name)).length > 0" class="mt-2 text-xs text-slate-500">
              Examples:
              {{ getCompatibleSelectorExamples(field, getStepBinding(field.name)).join(', ') }}
            </p>
          </div>
        </div>
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

function getConstructorInputs() {
  return props.helpers.getConstructorInputs(props.step)
}

function getStepBinding(fieldName) {
  return props.helpers.getStepBinding(props.step, fieldName)
}

function getBindingTypeOptions(field) {
  return props.helpers.getBindingTypeOptions(field)
}

function bindingNeedsSourceStep(fieldName) {
  return props.helpers.bindingNeedsSourceStep(getStepBinding(fieldName))
}

function bindingNeedsSourceOutput(fieldName) {
  return props.helpers.bindingNeedsSourceOutput(getStepBinding(fieldName))
}

function getCompatibleSourceStepOptions(field) {
  return props.helpers.getCompatibleSourceStepOptions(props.step, field)
}

function getCompatibleSourceOutputOptions(field, sourceStepId) {
  return props.helpers.getCompatibleSourceOutputOptions(props.step, field, sourceStepId)
}

function getCompatibleSelectorExamples(field, binding) {
  return props.helpers.getCompatibleSelectorExamples(props.step, field, binding)
}
</script>
