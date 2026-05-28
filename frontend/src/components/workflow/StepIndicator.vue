<template>
  <div class="py-4">
    <nav aria-label="Progress">
      <ol class="flex items-center">
        <li
          v-for="(step, index) in steps"
          :key="step.id"
          :class="[
            'relative',
            index !== steps.length - 1 ? 'pr-8 sm:pr-20' : '',
            'flex-1'
          ]"
        >
          <div
            v-if="index !== steps.length - 1"
            class="absolute inset-0 flex items-center"
            aria-hidden="true"
          >
            <div
              :class="[
                'h-0.5 w-full',
                index < currentStep - 1 ? 'bg-indigo-600' : 'bg-gray-200'
              ]"
            ></div>
          </div>

          <div class="relative flex items-center justify-center">
            <div
              :class="[
                'h-8 w-8 rounded-full flex items-center justify-center',
                index < currentStep - 1
                  ? 'bg-indigo-600'
                  : index === currentStep - 1
                  ? 'bg-indigo-600 ring-4 ring-indigo-100'
                  : 'bg-gray-200'
              ]"
            >
              <svg
                v-if="index < currentStep - 1"
                class="h-5 w-5 text-white"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
              </svg>

              <span
                v-else-if="index === currentStep - 1"
                class="text-white font-medium text-sm"
              >
                {{ index + 1 }}
              </span>

              <span v-else class="text-gray-500 font-medium text-sm">
                {{ index + 1 }}
              </span>
            </div>
          </div>

          <div class="absolute -bottom-8 left-1/2 transform -translate-x-1/2 w-32 text-center">
            <span
              :class="[
                'text-xs font-medium',
                index <= currentStep - 1 ? 'text-indigo-600' : 'text-gray-500'
              ]"
            >
              {{ step.name }}
            </span>
          </div>
        </li>
      </ol>
    </nav>
    <div v-if="currentLabel || currentHint" class="mt-10 rounded-xl border border-indigo-100 bg-indigo-50 px-4 py-3">
      <p v-if="currentLabel" class="text-sm font-semibold text-indigo-950">{{ currentLabel }}</p>
      <p v-if="currentHint" class="mt-1 text-sm text-indigo-900">{{ currentHint }}</p>
    </div>
  </div>
</template>

<script setup>
defineProps({
  currentStep: {
    type: Number,
    required: true
  },
  currentLabel: {
    type: String,
    required: false,
    default: ''
  },
  currentHint: {
    type: String,
    required: false,
    default: ''
  },
  steps: {
    type: Array,
    required: false,
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
