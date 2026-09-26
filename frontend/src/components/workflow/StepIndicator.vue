<template>
  <div class="py-4 mb-4">
    <nav aria-label="Workflow progress">
      <p class="mb-3 text-sm font-medium text-indigo-900 md:hidden">
        Step {{ currentStep }} of {{ steps.length }} · {{ steps[currentStep - 1]?.name }}
      </p>
      <ol class="grid gap-2" :style="{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }">
        <li
          v-for="(step, index) in steps"
          :key="step.id"
          :aria-current="index === currentStep - 1 ? 'step' : undefined"
          class="min-w-0 text-center"
        >
          <div class="h-1.5 rounded-full mb-3" :class="index < currentStep ? 'bg-indigo-600' : 'bg-gray-200'" aria-hidden="true"></div>
          <span class="sr-only">Step {{ index + 1 }}: </span>
          <span class="sr-only md:not-sr-only md:block text-xs leading-5 font-medium" :class="index === currentStep - 1 ? 'text-indigo-800' : 'text-gray-600'">
            {{ step.name }}
          </span>
          <span class="sr-only">{{ index < currentStep - 1 ? ', previous step' : index === currentStep - 1 ? ', current step' : ', upcoming step' }}</span>
        </li>
      </ol>
    </nav>
    <div v-if="currentLabel || currentHint" class="mt-4 border-l-2 border-indigo-300 pl-3">
      <p v-if="currentLabel" class="text-sm font-semibold text-gray-900">{{ currentLabel }}</p>
      <p v-if="currentHint" class="mt-1 text-sm text-gray-600">{{ currentHint }}</p>
    </div>
  </div>
</template>

<script setup>
defineProps({
  currentStep: { type: Number, required: true },
  currentLabel: { type: String, default: '' },
  currentHint: { type: String, default: '' },
  steps: {
    type: Array,
    default: () => [
      { id: 1, name: 'Upload' },
      { id: 2, name: 'MSF QA' },
      { id: 3, name: 'Review Files' },
      { id: 4, name: 'Submission Metadata' },
      { id: 5, name: 'EDM & LOD' },
      { id: 6, name: 'Pipeline' },
      { id: 7, name: 'Submit' },
    ]
  }
})
</script>
