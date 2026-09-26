<!-- src/views/workflow/EdmSelectionView.vue -->
<template>
  <div class="min-h-screen bg-gray-50 py-8">
    <div class="max-w-5xl mx-auto px-4">
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900">Linked Metadata</h1>
        <p class="mt-2 text-gray-600">Choose how your descriptions become linked metadata for reuse.</p>
      </div>

      <StepIndicator :batch-mode="workflowStore.isBatchMode" :current-step="5" />

      <div class="bg-white shadow rounded-lg p-6">

        <!-- Error Alert -->
        <Alert v-if="saveError" :model-value="true" variant="error" title="Could not save selection" class="mb-6" @update:model-value="saveError = null">
            {{ saveError }}
        </Alert>

        <div v-if="loading" class="text-center py-12">
            <LoadingSpinner size="lg" text="Loading templates..." />
        </div>

        <div v-else>
            <div v-if="templateLoadError" class="mb-6">
                <Alert :model-value="true" :dismissible="false" variant="error" title="Template Loading Failed">
                    {{ templateLoadError }}
                </Alert>
            </div>

            <div
              v-else-if="edmTemplates.length === 0"
              class="mb-8 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
            >
              No EDM templates are currently available. Create or restore at least one EDM template before continuing.
            </div>

            <div v-else class="mb-8">
                <div class="mb-3 flex items-center justify-between">
                    <div>
                        <h2 class="text-lg font-semibold text-gray-900">EDM Template</h2>
                        <p class="text-sm text-gray-500">
                          {{ workflowStore.isBatchMode
                            ? 'Choose the EDM template used by the LOD Mapper and preview generation.'
                            : 'Choose the EDM template used for preview and submission.' }}
                        </p>
                    </div>
                    <p v-if="selectedTemplate" class="text-xs font-medium text-indigo-700">
                      Selected: {{ selectedTemplate.name }}
                    </p>
                </div>

                <fieldset class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <legend class="sr-only">EDM template</legend>
                    <label
                        v-for="tpl in edmTemplates"
                        :key="tpl.id"
                        :class="[
                          'border rounded-lg p-4 cursor-pointer transition-all',
                          selectedTemplate?.id === tpl.id
                            ? 'border-indigo-600 ring-2 ring-indigo-500 ring-opacity-50 bg-indigo-50'
                            : 'border-gray-200 hover:border-indigo-300'
                        ]"
                    >
                        <div class="flex justify-between items-start">
                            <span class="flex items-start gap-2">
                              <input type="radio" name="edm-template" :value="tpl.id" :checked="selectedTemplate?.id === tpl.id" :aria-label="tpl.name" class="mt-1 text-indigo-600 focus:ring-indigo-500" @change="selectTemplate(tpl)" />
                              <span class="font-medium text-gray-900">{{ tpl.name }}</span>
                            </span>
                            <span
                              v-if="tpl.is_default"
                              class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800"
                            >
                              Default
                            </span>
                        </div>
                        <p class="text-sm text-gray-500 mt-2 line-clamp-2">{{ tpl.description || 'No description' }}</p>
                    </label>
                </fieldset>
            </div>

                <!-- EDM Provider Input -->
                <div class="mb-6">
                    <label for="edm-provider" class="block text-sm font-medium text-gray-700 mb-1">EDM Provider</label>
                    <input
                        id="edm-provider" v-model="edmProvider"
                        type="text"
                        class="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm p-2 border"
                        placeholder="WebHDP"
                    >
                    <p class="text-xs text-gray-400 mt-1">The organization providing the data (edm:provider, edm:dataProvider fallbacks).</p>
                </div>


            <!-- Batch Mode LOD-Mapper -->
            <div v-if="workflowStore.isBatchMode && selectedTemplate" class="mb-8 space-y-6">
                <LodMapper
                  :msf-path="workflowStore.msfPath"
                  :template-id="selectedTemplate.id"
                  :initial-mapping="workflowStore.submissionMetadata?.lod_mapping"
                  :provider="edmProvider"
                  @update:mapping="handleMappingUpdate"
                />
            </div>

            <!-- Preview & Validation Area -->
            <div v-if="selectedTemplate && !workflowStore.isBatchMode" class="border-t border-gray-200 pt-6">

                <!-- Asset Thumbnails (Hide in batch mode) -->
                <div v-if="!workflowStore.isBatchMode && uploadedAssets.length > 0" class="mb-6">
                    <h3 class="text-sm font-medium text-gray-700 mb-3">Uploaded Assets (Select Main File)</h3>
                    <div class="space-y-3">
                        <!-- Horizontal Scroll list if many, or grid -->
                        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                            <div
                                v-for="(asset, idx) in uploadedAssets"
                                :key="idx"
                                @click="selectedFile = asset"
                                :class="['flex items-center gap-3 p-2 rounded-lg border cursor-pointer transition-colors', selectedFile?.name === asset.name ? 'border-indigo-600 bg-indigo-50 ring-1 ring-indigo-600' : 'border-gray-200 hover:bg-gray-50']"
                            >
                                <div class="w-10 h-10 rounded border border-gray-200 bg-gray-100 flex-shrink-0 flex items-center justify-center overflow-hidden">
                                     <img
                                        v-if="isImageAsset(asset)"
                                        :src="asset.thumbnail || asset.url"
                                        :alt="asset.name"
                                        class="w-full h-full object-cover"
                                    />
                                    <span v-else class="text-lg">{{ getAssetIcon(asset) }}</span>
                                </div>
                                <div class="min-w-0 flex-1">
                                    <p class="text-sm font-medium text-gray-900 truncate" :title="asset.name">{{ asset.name }}</p>
                                    <p class="text-xs text-gray-500">{{ ((asset.size ?? asset.size_bytes ?? 0) / 1024).toFixed(1) }} KB</p>
                                </div>
                                <div class="flex-shrink-0">
                                    <div :class="['w-4 h-4 rounded-full border flex items-center justify-center', selectedFile?.name === asset.name ? 'border-indigo-600' : 'border-gray-300']">
                                        <div v-if="selectedFile?.name === asset.name" class="w-2 h-2 rounded-full bg-indigo-600"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <p class="text-xs text-gray-400 mt-2">The selected file will be used as the primary object (edm:ProvidedCHO, ore:Aggregation) in the XML.</p>
                </div>

                <!-- Data Source Toggle -->
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-lg font-medium text-gray-900">Preview (Live)</h3>
                    <div class="flex items-center gap-4">
                        <label class="flex items-center gap-2 text-sm text-gray-600">
                            <input
                                type="checkbox"
                                v-model="useLiveData"
                                class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                            />
                            Use live session data
                        </label>
                        <button @click="refreshPreview" class="text-sm text-indigo-600 hover:text-indigo-800">Refresh Preview</button>
                    </div>
                </div>

                <!-- Validation Status Info -->
                <div v-if="systemConfig" class="mb-6 p-4 bg-gray-50 rounded-xl border border-gray-100">
                    <h4 class="text-[10px] uppercase font-bold text-gray-400 tracking-widest mb-3">Validation Engines</h4>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div class="flex items-center space-x-2">
                            <div :class="['w-2 h-2 rounded-full', localValidatorEnabled ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-gray-300']"></div>
                            <span class="text-xs font-medium text-gray-600">Local EDM Validator</span>
                            <span class="text-[9px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-500 font-bold uppercase">{{ localValidatorEnabled ? 'Active' : 'Skipped' }}</span>
                        </div>
                        <div class="flex items-center space-x-2">
                            <div :class="['w-2 h-2 rounded-full', systemConfig.enable_xsd_validation ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-gray-300']"></div>
                            <span class="text-xs font-medium text-gray-600">EDM XSD</span>
                            <span class="text-[9px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-500 font-bold uppercase">{{ systemConfig.enable_xsd_validation ? 'Active' : 'Skipped' }}</span>
                        </div>
                        <div class="flex items-center space-x-2">
                            <div :class="['w-2 h-2 rounded-full', systemConfig.enable_schematron_validation ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-gray-300']"></div>
                            <span class="text-xs font-medium text-gray-600">Schematron</span>
                            <span class="text-[9px] px-1.5 py-0.5 rounded bg-gray-200 text-gray-500 font-bold uppercase">{{ systemConfig.enable_schematron_validation ? 'Active' : 'Skipped' }}</span>
                        </div>
                    </div>
                    <p v-if="!localValidatorEnabled" class="mt-3 text-[10px] text-gray-400 italic">
                        External validation is optional. The report below identifies checks that ran and checks that were skipped.
                    </p>
                </div>

                <!-- Validation Report -->
                <div v-if="validationResult" class="mb-6">
                    <div class="flex items-center justify-between mb-3">
                        <h4 class="font-bold text-gray-900 tracking-tight flex items-center">
                            <svg class="h-5 w-5 text-amber-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                            EDM Validation Report
                        </h4>
                    </div>

                    <div class="space-y-4">
                        <!-- Summary Status -->
                        <div :class="['p-4 rounded-xl border flex items-center', validationResult.valid ? 'bg-green-50 border-green-100 text-green-800' : 'bg-red-50 border-red-100 text-red-800']">
                            <svg v-if="validationResult.valid" class="h-6 w-6 mr-3 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                            </svg>
                            <svg v-else class="h-6 w-6 mr-3 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                            <div>
                                <p class="font-bold text-sm">{{ validationResult.valid ? 'Available checks passed' : 'Issues Found' }}</p>
                                <p class="text-xs opacity-80">{{ validationResult.valid ? 'The generated XML passed the checks listed below. Skipped checks have not been performed.' : 'Your submission has some issues that should be addressed.' }}</p>
                            </div>
                        </div>

                        <!-- Error List -->
                        <div v-if="validationResult.errors?.length > 0" class="space-y-2">
                            <h5 class="text-[10px] uppercase text-red-500 font-bold tracking-widest pl-1">Errors</h5>
                            <div v-for="(error, idx) in validationResult.errors" :key="idx" class="p-3 bg-white border-l-4 border-red-500 rounded-lg shadow-sm text-xs text-gray-700">
                                {{ error }}
                            </div>
                        </div>

                        <!-- Warning List -->
                        <div v-if="validationResult.warnings?.length > 0" class="space-y-2">
                            <div class="flex items-center justify-between">
                                <h5 class="text-[10px] uppercase text-amber-500 font-bold tracking-widest pl-1">Warnings</h5>
                                <button @click="showWarnings = !showWarnings" class="text-[10px] font-bold text-gray-400 hover:text-gray-600 uppercase">{{ showWarnings ? 'Hide' : 'Show' }}</button>
                            </div>
                            <div v-if="showWarnings" class="space-y-2">
                                <div v-for="(warn, idx) in validationResult.warnings" :key="idx" class="p-3 bg-white border-l-4 border-amber-500 rounded-lg shadow-sm text-xs text-gray-700">
                                    {{ warn }}
                                </div>
                            </div>
                        </div>

                        <div v-if="localValidatorSteps.length > 0" class="mt-4 border-t border-gray-100 pt-4">
                            <div class="flex items-center justify-between mb-3">
                                <h5 class="text-[10px] uppercase text-gray-400 font-bold tracking-widest pl-1">Local Validator Steps</h5>
                                <span v-if="localValidatorDuration !== null" class="text-[10px] font-bold text-gray-400">{{ localValidatorDuration }} ms</span>
                            </div>
                            <div class="space-y-2">
                                <div v-for="step in localValidatorSteps" :key="step.step" class="rounded-lg border border-gray-100 bg-white p-3">
                                    <div class="flex items-center justify-between gap-3">
                                        <span class="text-[11px] font-bold text-gray-700">{{ formatValidationStep(step.step) }}</span>
                                        <span :class="['text-[9px] px-1.5 py-0.5 rounded font-bold uppercase', step.valid ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700']">
                                            {{ step.status || (step.valid ? 'PASSED' : 'FAILED') }}
                                        </span>
                                    </div>
                                    <div v-if="step.messages?.length" class="mt-2 space-y-1">
                                        <div v-for="(message, messageIdx) in step.messages" :key="`${step.step}-${messageIdx}`" class="flex gap-2 text-[11px] text-gray-600">
                                            <span :class="['font-bold uppercase', message.type === 'ERROR' ? 'text-red-500' : message.type === 'WARN' ? 'text-amber-500' : 'text-gray-400']">{{ message.type }}</span>
                                            <span>{{ message.message }}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Details (Horizontal Grid) -->
                        <div class="mt-4 border-t border-gray-100 pt-4">
                            <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
                                <div v-for="(res, type) in validationResult.details" :key="type" class="flex flex-col items-center justify-center p-2 bg-gray-50 rounded-lg border border-gray-100">
                                    <span class="text-[9px] uppercase font-bold text-gray-400">{{ formatValidationStep(type) }}</span>
                                    <span :class="['text-[10px] font-bold', !res || res.skipped ? 'text-gray-500' : validationDetailPassed(res) ? 'text-green-600' : 'text-red-600']">
                                        {{ !res || res.skipped ? 'SKIPPED' : validationDetailPassed(res) ? 'PASS' : 'FAIL' }}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Preview Content -->
                <div v-if="previewLoading" class="h-48 bg-gray-50 flex items-center justify-center border rounded">
                    <span class="text-gray-400">Rendering preview...</span>
                </div>
                <div v-else-if="previewError" class="p-4 bg-red-50 text-red-700 rounded text-sm">
                    {{ previewError }}
                </div>
                <pre v-else class="bg-gray-900 text-green-400 p-4 rounded-lg overflow-x-auto text-xs font-mono h-64">{{ previewContent }}</pre>
            </div>
        </div>

        <div class="mt-8 flex justify-between">
          <button
            @click="handleBack"
            class="px-6 py-2 border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 transition-colors"
          >
            ← Back
          </button>
          <button
            @click="handleNext"
            :disabled="!selectedTemplate || isSaving"
            class="px-6 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {{ isSaving ? 'Saving selection…' : 'Continue to Pipeline →' }}
          </button>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkflowStore } from '@/stores/workflow'
import api from '@/services/api'
import StepIndicator from '@/components/workflow/StepIndicator.vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import Alert from '@/components/ui/Alert.vue'
import LodMapper from '@/components/workflow/LodMapper.vue'
import { persistWorkflowState, restoreWorkflowContext, shouldRestoreWorkflowContext } from '@/utils/workflowState'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()

const loading = ref(true)
const isSaving = ref(false) // NEW
const saveError = ref(null) // NEW
const templateLoadError = ref('')

const templates = ref([])
const selectedTemplate = ref(null)
const selectedFile = ref(null) // NEW: Selected main file
const edmProvider = ref(workflowStore.submissionMetadata?.edm_provider ?? "WebHDP")
const lodMapping = ref(null) // NEW: LOD mapping configuration



const previewLoading = ref(false)
const previewContent = ref('')
const previewError = ref(null)

const systemConfig = ref(null)
const validationResult = ref(null)
const showWarnings = ref(false)
const useLiveData = ref(true)
const localValidatorEnabled = computed(() => Boolean(systemConfig.value?.enable_local_edm_validation ?? systemConfig.value?.enable_metis_validation))
const localValidatorResult = computed(() => validationResult.value?.details?.remote || null)
const localValidatorSteps = computed(() => {
    const result = localValidatorResult.value
    if (!result) return []
    return Array.isArray(result.validation_results) ? result.validation_results : []
})
const localValidatorDuration = computed(() => {
    const duration = localValidatorResult.value?.total_duration_millis
    return Number.isFinite(Number(duration)) ? Number(duration) : null
})
const edmTemplates = computed(() => {
    return (templates.value || []).filter(template => {
        const standard = String(template?.standard || '').toLowerCase()
        return standard === 'edm'
    })
})

function formatValidationStep(step) {
    return String(step || '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, char => char.toUpperCase())
}

function validationDetailPassed(detail) {
    return detail?.valid === true && !detail.skipped
}

// Get uploaded assets from workflow store
const uploadedAssets = computed(() => {
    return workflowStore.uploadedFiles || []
})

// Auto-select largest file on mount or when assets change
watch(uploadedAssets, (files) => {
    if (files && files.length > 0 && !selectedFile.value) {
        const draftMainFileKey = workflowStore.submissionMetadata?.edm_main_file_key
        if (draftMainFileKey) {
            const matchingFile = files.find(file => file.name === draftMainFileKey)
            if (matchingFile) {
                selectedFile.value = matchingFile
                return
            }
        }

        // Find largest file
        const largest = files.reduce((prev, current) => {
             return (prev.size > current.size) ? prev : current
        }, files[0])
        selectedFile.value = largest
    }
}, { immediate: true })

function isImageAsset(asset) {
    const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg']
    const ext = asset.name?.split('.').pop()?.toLowerCase()
    return imageExts.includes(ext)
}

function getAssetIcon(asset) {
    const ext = asset.name?.split('.').pop()?.toLowerCase()
    const icons = {
        'glb': '🎨',
        'gltf': '🎨',
        'obj': '🎨',
        'fbx': '🎨',
        'stl': '🎨',
        'pdf': '📄',
        'doc': '📄',
        'docx': '📄',
        'mp4': '🎬',
        'mov': '🎬',
        'avi': '🎬',
        'mp3': '🎵',
        'wav': '🎵',
        'zip': '📦',
        'rar': '📦',
    }
    return icons[ext] || '📁'
}

async function fetchTemplates() {
    try {
        const res = await api.get('/templates')
        if (res.success) {
            templateLoadError.value = ''
            templates.value = res.data.templates || []
            const draftTemplateId = Number.parseInt(workflowStore.submissionMetadata?.edm_template_id, 10)
            const preferred = edmTemplates.value.find(t => t.id === draftTemplateId)
              || edmTemplates.value.find(t => t.is_default)
              || edmTemplates.value[0]
            if (preferred) selectTemplate(preferred)
            else selectedTemplate.value = null
        }
    } catch (e) {
        console.error(e)
        templates.value = []
        selectedTemplate.value = null
        templateLoadError.value = e?.error?.message || e?.message || 'Failed to load EDM templates.'
    }
}

const fetchHealthConfig = async () => {
    try {
        const response = await api.get('/health')
        if (response.success && response.data?.config) {
            systemConfig.value = response.data.config
        }
    } catch (err) {
        console.warn('Failed to fetch health config:', err)
    }
}

onMounted(async () => {
    loading.value = true
    try {
        const resumeSessionId = Number.parseInt(route.query.sessionId, 10)
        if (shouldRestoreWorkflowContext(workflowStore, resumeSessionId, {
          force: route.query.resume === 'workflow',
          requireSelectedFiles: true,
          requireUploadedFiles: true,
          requireBatchMetadata: true,
          requireSubmissionMetadata: !workflowStore.isBatchMode,
          requireMsfPath: workflowStore.isBatchMode
        })) {
          await restoreWorkflowContext(workflowStore, resumeSessionId)
        }
        edmProvider.value = workflowStore.submissionMetadata?.edm_provider ?? "WebHDP"
        await Promise.all([
            fetchTemplates(),
            fetchHealthConfig()
        ])
        if (workflowStore.sessionId) {
          await persistWorkflowState(workflowStore, 'edm_selection')
        }
    } finally {
        loading.value = false
    }
})

function selectTemplate(tpl) {
    selectedTemplate.value = tpl
    refreshPreview()
}

function handleMappingUpdate(mapping) {
  lodMapping.value = mapping
}

let previewEpoch = 0
onBeforeUnmount(() => { previewEpoch++ })
async function refreshPreview() {
    const epoch = ++previewEpoch
    previewContent.value = ''
    validationResult.value = null
    if (!selectedTemplate.value || workflowStore.isBatchMode) return

    previewLoading.value = true
    previewError.value = null
    validationResult.value = null

    try {
        // Build metadata based on toggle
        let metadata = {}

        if (useLiveData.value && workflowStore.isBatchMode && workflowStore.fileMetadataMap && selectedFile.value) {
            // In batch mode, metadata is per-file. Use the metadata for the currently selected file.
            metadata = { ...workflowStore.fileMetadataMap[selectedFile.value.name] }
        } else if (useLiveData.value && workflowStore.submissionMetadata) {
            metadata = { ...workflowStore.submissionMetadata }
        } else {
            // Mock/placeholder data
            metadata = {
                title: "[Your Title]",
                description: "[Your Description]",
                creators: [{name: "[Creator Name]"}],
                upload_type: "dataset",
                license: "cc-by",
                publication_date: "2024-01-01"
            }
        }

        // Add provider override
        metadata.edm_provider = edmProvider.value

        // Mock zenodo record for preview purposes
        const zenodoMock = {
            id: 12345,
            metadata: { prereserve_doi: { doi: "10.5072/example-doi" } },
            links: { html: "https://sandbox.zenodo.org/records/12345" }
        }

        const res = await api.post('/templates/preview', {
            template_id: selectedTemplate.value.id,
            metadata: metadata,
            zenodo: zenodoMock,
            main_file_key: selectedFile.value ? selectedFile.value.name : null // NEW
        })

        if (epoch !== previewEpoch) return
        if (res.success) {
            previewContent.value = res.data.xml

            // Run validation on the generated XML
            await validatePreview(res.data.xml, metadata, epoch)
        } else {
            previewError.value = "Failed to render preview"
        }
    } catch (e) {
        if (epoch === previewEpoch) previewError.value = e.error?.message || "Preview failed"
    } finally {
        if (epoch === previewEpoch) previewLoading.value = false
    }
}

async function validatePreview(xmlContent, metadata = {}, epoch = previewEpoch) {
    try {
        const res = await api.post('/templates/validate', {
            xml: xmlContent,
            metadata
        })

        if (epoch !== previewEpoch) return
        if (!res.success || typeof res.data?.valid !== 'boolean') throw new Error("Validation returned no result")
        validationResult.value = res.data
    } catch (e) {
        if (epoch !== previewEpoch) return
        validationResult.value = {
            valid: false,
            status: "unavailable",
            errors: ["Validation is unavailable. Refresh the preview to retry; this document has not passed validation."],
            warnings: []
        }
    }
}

// Watch for data toggle changes
watch([useLiveData, selectedFile, edmProvider], () => {
    refreshPreview()
})

function handleBack() {
    workflowStore.goToStep(4)
    persistWorkflowState(workflowStore, 'metadata').catch((err) => {
        console.warn('Failed to persist metadata workflow state:', err)
    })
    router.push('/workflow/metadata')
}

async function handleNext() {
    if (isSaving.value) return
    isSaving.value = true
    saveError.value = null
    // Save selection to draft metadata (we need to inject it)
    try {
        // We need to update the draft with the selected template ID.
        // We'll append it to the metadata payload.
        const currentMeta = JSON.parse(JSON.stringify(workflowStore.submissionMetadata || {}))

        if (selectedTemplate.value) {
            currentMeta.edm_template_id = selectedTemplate.value.id
        }

        if (workflowStore.isBatchMode) {
          delete currentMeta.edm_main_file_key
        } else if (selectedFile.value) {
          currentMeta.edm_main_file_key = selectedFile.value.name
        }

        currentMeta.edm_provider = edmProvider.value
        currentMeta.lod_minimum_viable = {
          ...workflowStore.lodMinimumViablePrefs
        }

        // Save LOD Mapping to workflow store/session
        if (workflowStore.isBatchMode) {
           currentMeta.msf_path = workflowStore.msfPath
           if (lodMapping.value) {
             currentMeta.lod_mapping = lodMapping.value
           }
        }

        // Only save if we strictly need to. In batch mode, we rely on MSF generally,
        // but sticking the template ID into the session metadata is still good practice.
        // Use the draft endpoint to avoid strict validation of potentially partial metadata.
        await api.put(`/metadata/user/${workflowStore.sessionId}/draft`, currentMeta)
        workflowStore.setSubmissionMetadata(currentMeta)


        await persistWorkflowState(workflowStore, 'pipeline')
        workflowStore.nextStep()
        router.push('/workflow/pipeline')
    } catch (e) {
        console.error("Save selection error:", e)
        // api.js interceptor returns the data object directly on error
        const errMsg = e.error?.message || e.message || e.response?.data?.error?.message || "Please retry saving your selection."
        saveError.value = "Failed to save selection: " + errMsg
    } finally {
        isSaving.value = false
    }
}

</script>
