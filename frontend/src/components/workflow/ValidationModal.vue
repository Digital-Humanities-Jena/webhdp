<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center bg-gray-900 bg-opacity-50"
    @click.self="closeModal"
  >
    <div class="modal-content bg-white p-6 rounded-lg shadow-xl w-full max-w-3xl">
      <h3 id="validation-modal-title" class="text-xl font-semibold mb-2 break-words">
        {{ fileNode.name || fileNode.filename || 'File Details' }}
      </h3>

      <div class="mb-3 flex flex-wrap items-center gap-2">
        <span
          v-if="validationStatus"
          :class="['inline-block px-3 py-1 rounded-full font-medium text-sm', statusBadgeClassForNode(validationStatus)]"
        >
          VALIDATION: {{ validationStatus }}
        </span>
        <span
          v-if="uploadStatus"
          :class="['inline-block px-3 py-1 rounded-full font-medium text-sm', uploadStatusBadgeClass(uploadStatus)]"
        >
          UPLOAD: {{ uploadStatus }}
        </span>
      </div>

      <p class="text-xs text-gray-500 mb-4">
        VALIDATION indicates file checks. UPLOAD indicates ingestion state.
      </p>

      <div class="mb-4 flex flex-wrap gap-2">
        <button
          v-if="hasValidationDetails"
          @click="activeSection = 'issues'"
          :class="tabClass('issues')"
        >
          Validation Details
        </button>
        <button
          v-if="assetRows.length > 0"
          @click="activeSection = 'assets'"
          :class="tabClass('assets')"
        >
          Bundled Assets
        </button>
        <button
          v-if="textureAssetRows.length > 0"
          @click="activeSection = 'textures'"
          :class="tabClass('textures')"
        >
          Textured Assets
        </button>
      </div>

      <div
        id="validation-modal-details-container"
        v-if="activeSection === 'issues' && hasValidationDetails"
        class="mb-6"
      >
        <p id="validation-modal-details-title" class="text-left font-semibold mb-2">
          Validation Details:
        </p>
        <ul
          id="validation-modal-details-list"
          class="text-left list-none p-4 bg-gray-50 border border-gray-200 rounded-md max-h-56 overflow-y-auto"
        >
          <li v-for="(error, index) in validationErrors" :key="`err-${index}`" class="text-red-600 pb-1">
            {{ error }}
          </li>
          <li v-for="(tex, index) in missingTextures" :key="`tex-${index}`" class="text-yellow-700 pb-1">
            Missing texture: {{ tex }}
          </li>
          <li v-for="(con, index) in conflicts" :key="`con-${index}`" class="text-red-600 pb-1">
            File conflict: {{ conflictLabel(con) }}
          </li>
        </ul>
      </div>

      <div
        id="validation-modal-children-container"
        v-if="activeSection === 'assets' && assetRows.length > 0"
        class="mb-6"
      >
        <p id="validation-modal-children-title" class="text-left font-semibold mb-2">
          Bundled Assets (with paths and validation):
        </p>
        <div
          id="validation-modal-children"
          class="text-left space-y-2 max-h-72 overflow-y-auto p-4 bg-gray-50 border border-gray-200 rounded-lg"
        >
          <div
            v-for="asset in assetRows"
            :key="asset.key"
            class="border-b border-gray-100 last:border-0 pb-2 mb-2 last:pb-0 last:mb-0"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="text-xs text-gray-400" :style="{ marginLeft: `${asset.depth * 14}px` }">↳</span>
                  <span class="text-sm font-medium text-gray-700 break-all">{{ asset.name }}</span>
                  <span class="ml-1 text-[10px] text-gray-400 uppercase tracking-tighter bg-gray-100 px-1 rounded">{{ asset.type }}</span>
                </div>
                <p class="text-xs text-gray-500 mt-1 break-all" :style="{ marginLeft: `${asset.depth * 14 + 20}px` }">
                  {{ asset.path || 'No path available' }}
                </p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span :class="['text-[10px] px-2 py-0.5 rounded-full font-bold uppercase', statusBadgeClassForNode(asset.validation_result)]">
                  {{ asset.validation_result }}
                </span>
                <span :class="['text-[10px] px-2 py-0.5 rounded-full font-bold uppercase', statusBadgeClassForNode(asset.status)]">
                  {{ asset.status }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div
        id="validation-modal-textured-assets-container"
        v-if="activeSection === 'textures' && textureAssetRows.length > 0"
        class="mb-6"
      >
        <p class="text-left font-semibold mb-2">Textured Assets:</p>
        <div class="text-left space-y-2 max-h-72 overflow-y-auto p-4 bg-gray-50 border border-gray-200 rounded-lg">
          <div
            v-for="asset in textureAssetRows"
            :key="`tex-${asset.key}`"
            class="border-b border-gray-100 last:border-0 pb-2 mb-2 last:pb-0 last:mb-0"
          >
            <div class="flex items-center justify-between gap-4">
              <div class="min-w-0">
                <p class="text-sm font-medium text-gray-700 break-all">{{ asset.name }}</p>
                <p class="text-xs text-gray-500 break-all">{{ asset.path || 'No path available' }}</p>
              </div>
              <span :class="['text-[10px] px-2 py-0.5 rounded-full font-bold uppercase', statusBadgeClassForNode(asset.validation_result)]">
                {{ asset.validation_result }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div id="validation-modal-buttons" class="flex justify-end mt-8">
        <button
          @click="closeModal"
          class="px-6 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 transition-colors"
        >
          Close
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { normalizeSourceFileState, sourceFileStateClass } from '@/utils/workflowState'

const props = defineProps({
  show: {
    type: Boolean,
    default: false
  },
  fileNode: {
    type: Object,
    default: () => ({})
  },
  focusSection: {
    type: String,
    default: 'overview'
  }
})

const emit = defineEmits(['update:show'])
const activeSection = ref('issues')

const closeModal = () => {
  emit('update:show', false)
}

const validationReport = computed(() => props.fileNode?.validation_report || {})
const bundledFiles = computed(() => props.fileNode?.children || [])
const validationStatus = computed(() => props.fileNode?.validation_status || props.fileNode?.status || 'N/A')
const uploadStatus = computed(() => props.fileNode?.upload_status || '')

const validationErrors = computed(() => validationReport.value.errors || [])
const missingTextures = computed(() => validationReport.value.missing_textures || [])
const conflicts = computed(() => validationReport.value.conflicts || [])

const hasValidationDetails = computed(() => {
  return validationErrors.value.length > 0 ||
         missingTextures.value.length > 0 ||
         conflicts.value.length > 0
})

const assetRows = computed(() => {
  const rows = []
  const walk = (nodes, depth = 0) => {
    nodes.forEach((node, index) => {
      const name = node.name || node.filename || `asset-${index}`
      const path = node.relative_path || node.absolute_path || node.path || ''
      rows.push({
        key: `${node.file_id || path || name}-${depth}-${index}`,
        name,
        path,
        type: node.type || node.file_type || 'file',
        status: node.status || node.validation_status || 'N/A',
        validation_result: getValidationResultLabel(node),
        depth
      })

      if (node.children && node.children.length > 0) {
        walk(node.children, depth + 1)
      }
    })
  }

  walk(bundledFiles.value || [])
  return rows
})

const textureAssetRows = computed(() => {
  return assetRows.value.filter(asset => isTextureAsset(asset))
})

watch(
  () => [props.show, props.focusSection, hasValidationDetails.value, assetRows.value.length, textureAssetRows.value.length],
  () => {
    if (!props.show) return
    if (props.focusSection === 'assets' && assetRows.value.length > 0) {
      activeSection.value = 'assets'
      return
    }
    if (props.focusSection === 'textures' && textureAssetRows.value.length > 0) {
      activeSection.value = 'textures'
      return
    }
    if (props.focusSection === 'issues' && hasValidationDetails.value) {
      activeSection.value = 'issues'
      return
    }
    if (hasValidationDetails.value) {
      activeSection.value = 'issues'
    } else if (assetRows.value.length > 0) {
      activeSection.value = 'assets'
    } else if (textureAssetRows.value.length > 0) {
      activeSection.value = 'textures'
    } else {
      activeSection.value = 'issues'
    }
  },
  { immediate: true }
)

const tabClass = (section) => {
  const isActive = activeSection.value === section
  return [
    'px-3 py-1.5 text-xs font-semibold rounded-md border transition-colors',
    isActive ? 'bg-indigo-100 text-indigo-800 border-indigo-300' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
  ]
}

const getValidationResultLabel = (node) => {
  const report = node?.validation_report || {}
  if (report?.is_valid === true) return 'VALID'
  if (report?.is_valid === false) return 'INVALID'

  const status = normalizeSourceFileState(node?.validation_status || node?.status || '')
  if (['registered', 'processed', 'selected'].includes(status)) return 'VALID'
  if (['missing', 'failed'].includes(status)) {
    return 'INVALID'
  }
  return 'N/A'
}

const isTextureAsset = (asset) => {
  const type = (asset.type || '').toLowerCase()
  if (['secondary', 'archived_file', 'texture'].includes(type)) return true
  const filename = (asset.name || '').toLowerCase()
  return /\.(png|jpe?g|tga|tiff?|bmp|dds|webp|ktx2?)$/.test(filename)
}

const conflictLabel = (conflict) => {
  if (typeof conflict === 'string') return conflict
  if (conflict?.filename) return conflict.filename
  return JSON.stringify(conflict)
}

const statusBadgeClassForNode = (status) => {
  return sourceFileStateClass(status)
}

const uploadStatusBadgeClass = (status) => {
  return sourceFileStateClass(status)
}
</script>
