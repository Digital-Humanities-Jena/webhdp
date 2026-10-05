<template>
  <div class="py-4 mb-4">
    <nav aria-label="Workflow progress">
      <p class="mb-3 text-sm font-medium text-indigo-900">
        Step {{ displayStep }} of {{ visibleSteps.length }} · {{ activeStep?.name }}
      </p>
      <ol class="grid gap-2" :style="{ gridTemplateColumns: `repeat(${visibleSteps.length}, minmax(0, 1fr))` }">
        <li
          v-for="(step, index) in visibleSteps"
          :key="step.id"
          :aria-current="step.id === currentStep ? 'step' : undefined"
          class="min-w-0 text-center"
        >
          <div class="h-1.5 rounded-full mb-3" :class="index < displayStep ? 'bg-indigo-600' : 'bg-gray-200'" aria-hidden="true"></div>
          <span class="sr-only">Step {{ index + 1 }}: </span>
          <span class="sr-only md:not-sr-only md:block text-xs leading-5 font-medium" :class="step.id === currentStep ? 'text-indigo-800' : 'text-gray-600'">
            {{ step.name }}
          </span>
          <span class="sr-only">{{ index < displayStep - 1 ? ', previous step' : step.id === currentStep ? ', current step' : ', upcoming step' }}</span>
        </li>
      </ol>
    </nav>
    <div v-if="currentLabel || currentHint || guidance" class="mt-4 border-l-2 border-indigo-300 pl-3">
      <p v-if="currentLabel || guidance" class="text-sm font-semibold text-gray-900">{{ currentLabel || guidance?.title }}</p>
      <p v-if="currentHint || guidance" class="mt-1 text-sm text-gray-600">{{ currentHint || guidance?.hint }}</p>
    </div>
    <details v-if="guidance" class="mt-3 text-sm text-gray-600">
      <summary class="cursor-pointer font-medium text-indigo-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600">Help with this step</summary>
      <p class="mt-2 max-w-3xl leading-relaxed">{{ guidance.detail }}</p>
      <a href="/docs/common-workflow-recipes" target="_blank" rel="noopener" class="mt-2 inline-block text-indigo-700 underline">Workflow recipes<span class="sr-only"> (opens in a new tab)</span></a>
    </details>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { workflowSteps, workflowGuidance } from '@/utils/workflowGuidance'

const props = defineProps({
  currentStep: { type: Number, required: true },
  currentLabel: { type: String, default: '' },
  currentHint: { type: String, default: '' },
  batchMode: { type: Boolean, default: true },
  steps: { type: Array, default: () => workflowSteps },
})
const visibleSteps = computed(() => props.steps.filter(step => props.batchMode || step.id !== 2))
const displayStep = computed(() => visibleSteps.value.findIndex(step => step.id === props.currentStep) + 1)
const activeStep = computed(() => visibleSteps.value.find(step => step.id === props.currentStep))
const guidance = computed(() => workflowGuidance[props.currentStep])
</script>
