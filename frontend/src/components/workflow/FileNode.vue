<template>
  <div class="border border-gray-200 rounded-lg">
    <div
      :class="[
        'border-b border-gray-200 p-4 hover:bg-gray-50 transition-colors',
        node.children && node.children.length > 0 ? 'rounded-t-lg' : 'rounded-lg'
      ]"
    >
      <div class="flex items-center justify-between">
        <div class="flex items-center space-x-3">
          <input
            type="checkbox"
            :id="`file-${node.file_id || index}`"
            :value="node"
            v_model="selectedFiles"

            class="h-4 w-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
          />
          <label :for="`file-${node.file_id || index}`" class="flex items-center cursor-pointer">
            <svg class="h-8 w-8 text-gray-400 mr-3" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd" />
            </svg>
            <div>
              <p class="text-sm font-medium text-gray-900">{{ node.name || node.filename || 'Unknown File' }}</p>
              <p class="text-xs text-gray-500">{{ node.absolute_path || '' }}</p>
            </div>
          </label>
        </div>

        <button
          type="button"
          v-if="node.status"
          @click="$emit('showDetails', node)"
          :class="[
            'text-xs px-2 py-1 rounded-full transition-all',
            'hover:shadow-md hover:scale-105 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2',
            statusClass(node.status)
          ]"
        >
          {{ node.status }}
        </button>
        <span v-else class="px-2 py-1"></span>
      </div>
    </div>

    <div v-if="node.children && node.children.length > 0" class="bg-gray-50/50 rounded-b-lg">
      <div
        v-for="(child, childIndex) in node.children"
        :key="child.file_id || childIndex"
        class="p-3 pl-12 border-t border-gray-200"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center space-x-3">
            <span class="text-gray-400">↳</span>
            <svg class="h-6 w-6 text-gray-400 mr-2" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd" />
            </svg>
            <div>
              <p class="text-sm font-medium text-gray-800">{{ child.name || child.filename || 'Unknown File' }}</p>
              <p class="text-xs text-gray-500">{{ child.absolute_path || '' }}</p>
            </div>
          </div>

          <button
            type="button"
            v-if="child.status"
            @click="$emit('showDetails', child)"
            :class="[
              'text-xs px-2 py-1 rounded-full transition-all',
              'hover:shadow-md hover:scale-105 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2',
              statusClass(child.status)
            ]"
          >
            {{ child.status }}
          </button>
          <span v-else class="px-2 py-1"></span>

        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useWorkflowStore } from '@/stores/workflow'
import { sourceFileStateClass } from '@/utils/workflowState'

defineEmits(['showDetails'])

const props = defineProps({
  node: {
    type: Object,
    required: true
  },
  index: {
    type: Number,
    required: true
  }
})

const workflowStore = useWorkflowStore()

// Get a writable computed property for v-model
const selectedFiles = computed({
  get: () => workflowStore.selectedFiles,
  set: (value) => {
    workflowStore.selectedFiles = value
  }
})

// Logic to determine badge color (from previous app's CSS)
const statusClass = (status) => {
  return sourceFileStateClass(status)
}
</script>
