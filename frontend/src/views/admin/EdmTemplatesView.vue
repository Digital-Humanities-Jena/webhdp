<!-- src/views/admin/EdmTemplatesView.vue -->
<template>
  <div class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
    <div class="px-4 py-6 sm:px-0">
      <div class="flex items-center justify-between mb-6">
        <h1 class="text-2xl font-semibold text-gray-900">EDM Templates</h1>
        <button
          @click="openCreateModal"
          class="inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
        >
          <svg class="-ml-1 mr-2 h-5 w-5" xmlns="http://www.w3.org/2000/02/svg" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd" />
          </svg>
          New Template
        </button>
      </div>

      <!-- Template List -->
      <div class="bg-white shadow overflow-hidden sm:rounded-lg">
        <ul v-if="loading" class="divide-y divide-gray-200">
          <li class="px-6 py-12 text-center text-gray-500">
            <div class="animate-pulse flex flex-col items-center">
              <div class="h-8 w-8 bg-gray-200 rounded-full mb-2"></div>
              <p>Loading templates...</p>
            </div>
          </li>
        </ul>
        <ul v-else-if="templates.length === 0" class="divide-y divide-gray-200">
          <li class="px-6 py-12 text-center text-gray-500">
            <p>No templates found. Create one to get started.</p>
          </li>
        </ul>
        <ul v-else class="divide-y divide-gray-200">
          <li v-for="template in templates" :key="template.id" class="hover:bg-gray-50 transition-colors">
            <div class="px-6 py-4 flex items-center justify-between">
              <div class="flex-1 min-w-0">
                <div class="flex items-center space-x-3">
                  <h3 class="text-sm font-medium text-indigo-600 truncate">{{ template.name }}</h3>
                  <span v-if="template.is_default" class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-green-100 text-green-800 uppercase tracking-wider">
                    Default
                  </span>
                </div>
                <p class="mt-1 text-sm text-gray-500 line-clamp-1">{{ template.description || 'No description provided' }}</p>
              </div>
              <div class="flex items-center space-x-4 ml-4">
                <button @click="editTemplate(template)" class="text-sm font-medium text-indigo-600 hover:text-indigo-900">Edit</button>
                <button @click="deleteTemplate(template.id)" class="text-sm font-medium text-red-600 hover:text-red-900 border-l border-gray-200 pl-4">Delete</button>
              </div>
            </div>
          </li>
        </ul>
      </div>

      <!-- Editor Modal -->
      <div v-if="showModal" class="fixed inset-0 z-[100] overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
        <div class="flex items-center justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0">
          <div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity backdrop-blur-sm" aria-hidden="true" @click="closeModal"></div>

          <span class="hidden sm:inline-block sm:align-middle sm:h-screen" aria-hidden="true">&#8203;</span>

          <div class="inline-block align-bottom bg-white rounded-xl text-left overflow-hidden shadow-2xl transform transition-all sm:my-8 sm:align-middle sm:max-w-6xl sm:w-full border border-gray-200">
            <div class="bg-white px-6 py-5 border-b border-gray-100 flex justify-between items-center">
              <h3 class="text-xl font-semibold text-gray-900" id="modal-title">
                {{ isEditing ? 'Edit Template' : 'Create New Template' }}
              </h3>
              <button @click="closeModal" class="text-gray-400 hover:text-gray-500 transition-colors p-1 rounded-full hover:bg-gray-100">
                <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div class="bg-white px-6 pt-5 pb-4 h-[75vh] flex flex-col">
              <div class="flex flex-1 gap-6 overflow-hidden">
                <!-- Left: Form & Editor -->
                <div class="flex-1 flex flex-col gap-6 overflow-y-auto pr-2">
                  <div class="grid grid-cols-1 sm:grid-cols-2 gap-6">
                    <div>
                      <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Template Name</label>
                      <input v-model="form.name" type="text" placeholder="e.g. Standard EDM v2.4" class="block w-full border border-gray-300 rounded-lg shadow-sm py-2 px-3 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm">
                    </div>
                    <div class="flex items-end pb-2">
                      <label class="flex items-center cursor-pointer group">
                        <input id="is_default" v-model="form.is_default" type="checkbox" class="h-5 w-5 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded-md transition-all">
                        <span class="ml-3 text-sm font-medium text-gray-700 group-hover:text-gray-900">Set as Primary Default Template</span>
                      </label>
                    </div>
                  </div>

                  <div>
                    <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Description</label>
                    <input v-model="form.description" type="text" placeholder="Briefly describe what this template is for..." class="block w-full border border-gray-300 rounded-lg shadow-sm py-2 px-3 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm">
                  </div>

                  <div class="flex-1 flex flex-col min-h-0">
                    <div class="flex justify-between items-center mb-2">
                      <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wider">Content (Jinja2 XML)</label>
                      <div class="flex items-center space-x-2">
                        <button @click="toggleSampleData" :class="['text-xs px-3 py-1 rounded-full transition-colors', useSampleData ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-700 hover:bg-gray-200']">
                          {{ useSampleData ? '📋 Showing Sample Data' : '📝 Use Sample Data' }}
                        </button>
                        <button @click="isEditorExpanded = !isEditorExpanded" class="text-xs bg-gray-100 text-gray-700 px-3 py-1 rounded-full hover:bg-gray-200 transition-colors shadow-sm flex items-center">
                          <svg v-if="!isEditorExpanded" class="h-3 w-3 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
                          </svg>
                          <svg v-else class="h-3 w-3 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4l5 5m11-5l-5 5M4 20l5-5m11 5l-5-5" />
                          </svg>
                          {{ isEditorExpanded ? 'Minimize' : 'Expand Editor' }}
                        </button>
                        <button @click="validateTemplate" :disabled="validating" :class="['text-xs px-3 py-1 rounded-full transition-colors flex items-center shadow-sm', activeRightTab === 'validation' ? 'bg-amber-100 text-amber-700' : 'bg-amber-600 text-white hover:bg-amber-700']">
                           <svg v-if="validating" class="animate-spin -ml-1 mr-1.5 h-3 w-3 text-current" fill="none" viewBox="0 0 24 24">
                             <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                             <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                           </svg>
                           Validate
                        </button>
                        <button @click="preview" class="text-xs bg-indigo-600 text-white px-3 py-1 rounded-full hover:bg-indigo-700 transition-colors shadow-sm">
                          Preview Render
                        </button>
                      </div>
                    </div>
                    <!-- CodeMirror Editor Container -->
                    <div ref="editorContainer" :class="['flex-1 border border-gray-300 rounded-xl shadow-inner overflow-hidden bg-gray-900 transition-all duration-300', isEditorExpanded ? 'h-[600px] min-h-[500px]' : 'h-full min-h-[300px]']"></div>
                  </div>

                  <!-- Snippets Bar -->
                  <div class="border-t border-gray-100 pt-4">
                    <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Quick Snippets</h4>
                    <div class="flex flex-wrap gap-2">
                      <button
                        v-for="snippet in snippets"
                        :key="snippet.name"
                        @click="insertSnippet(snippet.code)"
                        class="inline-flex items-center px-3 py-1.5 text-xs font-medium bg-gray-50 text-gray-700 border border-gray-200 rounded-lg hover:bg-indigo-50 hover:text-indigo-700 hover:border-indigo-200 transition-all shadow-sm"
                        :title="snippet.description"
                      >
                        {{ snippet.name }}
                      </button>
                    </div>
                  </div>
                </div>

                <!-- Right: Helpers & Preview -->
                <div class="w-1/3 bg-gray-50 border border-gray-100 rounded-xl flex flex-col overflow-hidden">
                  <!-- Tabs for Guide/Validation -->
                  <div class="flex border-b border-gray-200">
                    <button @click="activeRightTab = 'guide'" :class="['flex-1 py-3 text-xs font-bold uppercase tracking-widest transition-all', activeRightTab === 'guide' ? 'bg-white text-indigo-600 border-b-2 border-indigo-600' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100']">
                      Guide
                    </button>
                    <button @click="activeRightTab = 'validation'" :class="['flex-1 py-3 text-xs font-bold uppercase tracking-widest transition-all', activeRightTab === 'validation' ? 'bg-white text-indigo-600 border-b-2 border-indigo-600' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100']">
                      Validation
                      <span v-if="validationResults" :class="['ml-1.5 px-1.5 py-0.5 rounded-full text-[10px]', validationResults.valid ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700']">
                        {{ validationResults.valid ? 'OK' : 'ERR' }}
                      </span>
                    </button>
                  </div>

                  <div class="flex-1 overflow-y-auto p-5">
                    <!-- Guide Tab -->
                    <div v-if="activeRightTab === 'guide'">
                      <div class="flex items-center mb-4">
                        <svg class="h-5 w-5 text-indigo-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <h4 class="font-bold text-gray-900 tracking-tight">Metadata Guide</h4>
                      </div>
                  <p class="text-xs text-gray-500 mb-6 italic">Click any code block to insert at cursor position.</p>

                  <div class="space-y-8">
                    <div v-for="(group, name) in placeholders" :key="name">
                      <h5 class="font-bold text-[10px] uppercase text-gray-400 tracking-widest mb-3 flex items-center">
                        <span class="w-1 h-1 bg-gray-300 rounded-full mr-2"></span>
                        {{ name }}
                      </h5>
                      <ul class="space-y-2">
                        <li v-for="ph in group" :key="ph.code">
                          <button
                            @click="insertPlaceholder(ph.code)"
                            class="group block w-full text-left p-2.5 bg-white border border-gray-200 rounded-lg hover:bg-indigo-50 hover:border-indigo-200 transition-all shadow-sm"
                            :title="ph.desc"
                          >
                            <code class="text-xs text-indigo-700 break-all font-mono">{{ ph.code }}</code>
                            <p class="mt-1 text-[10px] text-gray-400 group-hover:text-indigo-400 font-medium">{{ ph.desc }}</p>
                          </button>
                        </li>
                      </ul>
                      </div>
                    </div>
                  </div>

                  <!-- Validation Tab -->
                    <div v-else-if="activeRightTab === 'validation'" class="space-y-6">
                      <div class="flex items-center justify-between">
                        <h4 class="font-bold text-gray-900 tracking-tight flex items-center">
                          <svg class="h-5 w-5 text-amber-500 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                          Validation Report
                        </h4>
                        <button @click="validateTemplate" class="text-xs text-indigo-600 hover:underline font-medium">Re-run</button>
                      </div>

                      <div v-if="!validationResults && !validating" class="text-center py-12">
                        <svg class="mx-auto h-12 w-12 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                        </svg>
                        <p class="mt-4 text-sm text-gray-500">Run validation to check your template.</p>
                        <button @click="validateTemplate" class="mt-4 inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700">
                          Start Validation
                        </button>
                      </div>

                      <div v-if="validating" class="flex flex-col items-center py-12">
                        <div class="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600 mb-4"></div>
                        <p class="text-sm text-gray-500">Processing EDM rules...</p>
                      </div>

                      <div v-if="validationResults" class="space-y-4">
                        <!-- Summary Status -->
                        <div :class="['p-4 rounded-xl border flex items-center', validationResults.valid ? 'bg-green-50 border-green-100 text-green-800' : 'bg-red-50 border-red-100 text-red-800']">
                          <svg v-if="validationResults.valid" class="h-6 w-6 mr-3 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                          </svg>
                          <svg v-else class="h-6 w-6 mr-3 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                          <div>
                            <p class="font-bold text-sm">{{ validationResults.valid ? 'Strictly Compliant' : 'Issues Found' }}</p>
                            <p class="text-xs opacity-80">{{ validationResults.valid ? 'No structural or business rule violations detected.' : 'Please address the errors below to ensure EDM validity.' }}</p>
                          </div>
                        </div>

                        <!-- Error List -->
                        <div v-if="validationResults.errors.length > 0" class="space-y-3">
                          <h5 class="text-[10px] uppercase text-red-500 font-bold tracking-widest pl-1">Errors</h5>
                          <div v-for="(error, idx) in validationResults.errors" :key="idx" class="p-3 bg-white border-l-4 border-red-500 rounded-r-lg shadow-sm text-xs text-gray-700">
                            {{ error }}
                          </div>
                        </div>

                        <!-- Warning List -->
                        <div v-if="validationResults.warnings.length > 0" class="space-y-3">
                          <h5 class="text-[10px] uppercase text-amber-500 font-bold tracking-widest pl-1">Warnings</h5>
                          <div v-for="(warn, idx) in validationResults.warnings" :key="idx" class="p-3 bg-white border-l-4 border-amber-500 rounded-r-lg shadow-sm text-xs text-gray-700">
                            {{ warn }}
                          </div>
                        </div>

                        <div v-if="localValidatorSteps.length > 0" class="mt-6 border-t border-gray-100 pt-4">
                           <div class="flex items-center justify-between mb-3">
                             <h5 class="text-[10px] uppercase text-gray-400 font-bold tracking-widest">Local Validator Steps</h5>
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

                        <!-- Details (Collapsed) -->
                        <div class="mt-6 border-t border-gray-100 pt-4">
                           <h5 class="text-[10px] uppercase text-gray-400 font-bold tracking-widest mb-3">Validation Details</h5>
                           <div class="space-y-2">
                             <div v-for="(res, type) in validationResults.details" :key="type" class="flex items-center justify-between text-[11px] p-2 bg-gray-100 rounded-lg">
                               <span class="capitalize text-gray-600">{{ formatValidationStep(type) }}</span>
                               <span :class="validationDetailPassed(res) ? 'text-green-600 font-bold' : 'text-red-600 font-bold'">
                                 {{ validationDetailPassed(res) ? 'PASSED' : 'FAILED' }}
                               </span>
                             </div>
                           </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="bg-gray-50 px-6 py-4 flex flex-row-reverse space-x-3 space-x-reverse border-t border-gray-100">
              <button
                @click="saveTemplate"
                type="button"
                class="inline-flex justify-center rounded-lg border border-transparent shadow-sm px-6 py-2.5 bg-indigo-600 text-sm font-semibold text-white hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-all"
                :disabled="saving"
              >
                <span v-if="saving" class="flex items-center">
                  <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Saving...
                </span>
                <span v-else>Save Template</span>
              </button>
              <button
                @click="closeModal"
                type="button"
                class="inline-flex justify-center rounded-lg border border-gray-300 shadow-sm px-6 py-2.5 bg-white text-sm font-semibold text-gray-700 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-all"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive, nextTick, watch, onUnmounted, shallowRef, computed } from 'vue'

import api from '@/services/api'
import { useToast } from '@/composables/useToast'

// CodeMirror imports
import { EditorState } from '@codemirror/state'
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view'
import { xml } from '@codemirror/lang-xml'
import { autocompletion } from '@codemirror/autocomplete'
import { syntaxHighlighting, defaultHighlightStyle, HighlightStyle } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

const toast = useToast()

const loading = ref(true)
const saving = ref(false)
const templates = ref([])
const showModal = ref(false)
const isEditing = ref(false)
const useSampleData = ref(false)
const isEditorExpanded = ref(false)
const activeRightTab = ref('guide') // 'guide' or 'validation'
const validationResults = ref(null)
const validating = ref(false)
const localValidatorResult = computed(() => validationResults.value?.details?.remote || null)
const localValidatorSteps = computed(() => {
    const result = localValidatorResult.value
    if (!result) return []
    return Array.isArray(result.validation_results) ? result.validation_results : []
})
const localValidatorDuration = computed(() => {
    const duration = localValidatorResult.value?.total_duration_millis
    return Number.isFinite(Number(duration)) ? Number(duration) : null
})

function formatValidationStep(step) {
    return String(step || '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, char => char.toUpperCase())
}

function validationDetailPassed(detail) {
    if (!detail) return true
    return detail.valid !== false
}

// CodeMirror refs
const editorContainer = ref(null)
const editorView = shallowRef(null)

const form = reactive({
    id: null,
    name: '',
    description: '',
    content: '',
    is_default: false
})

const placeholders = {
    "Basic Metadata (Step 3)": [
        { code: "{{ metadata.title }}", desc: "Title" },
        { code: "{{ metadata.description }}", desc: "Description" },
        { code: "{{ metadata.publication_date }}", desc: "YYYY-MM-DD" },
        { code: "{{ metadata.cho_created }}", desc: "Original object creation date (YYYY-MM-DD)" },
        { code: "{{ metadata.license }}", desc: "License ID (e.g. cc-by)" },
    ],
    "Zenodo Record": [
         { code: "{{ zenodo.id }}", desc: "Record ID" },
         { code: "{{ zenodo.metadata.prereserve_doi.doi }}", desc: "DOI" },
         { code: "{{ zenodo.links.html }}", desc: "Landing Page URL" },
    ],
    "Helpers": [
        { code: "{{ helpers.map_type(metadata.upload_type) }}", desc: "Map Zenodo type to EDM" },
        { code: "{{ helpers.map_license(metadata.license) }}", desc: "Map License to URI" },
        { code: "{{ helpers.now().isoformat() }}", desc: "Current Timestamp" },
        { code: "{{ helpers.iso_date(metadata.cho_created) }}", desc: "ISO 8601 CHO creation date" },
        { code: "{{ helpers.iso_date(metadata.publication_date) }}", desc: "ISO 8601 publication date" },
        { code: "{{ helpers.generate_uri('agent') }}", desc: "Generate Agent URI" },
    ],
    "Collections (Loops)": [
        { code: "{% for creator in metadata.creators %}\n  <dc:creator>{{ creator.name }}</dc:creator>\n{% endfor %}", desc: "Loop Creators" },
        { code: "{% if metadata.access_right == 'open' %}\n  ...\n{% endif %}", desc: "Conditional Block" },
    ]
}

// Pre-defined snippets for common EDM structures
const snippets = [
    {
        name: "📄 WebResource",
        description: "Standard EDM WebResource block",
        code: `<edm:WebResource rdf:about="{{ main_file.content_url }}">
    <dc:format>{{ main_file.mime_type }}</dc:format>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </edm:WebResource>`
    },
    {
        name: "👤 Agent Loop",
        description: "Loop through creators as EDM Agents",
        code: `{% for creator in metadata.creators %}
  <edm:Agent rdf:about="#agent_{{ loop.index }}">
    <skos:prefLabel>{{ creator.name }}</skos:prefLabel>
  </edm:Agent>
  {% endfor %}`
    },
    {
        name: "📍 Place",
        description: "EDM Place node",
        code: `<edm:Place rdf:about="{{ helpers.generate_uri('place') }}">
    <skos:prefLabel>{{ metadata.location }}</skos:prefLabel>
  </edm:Place>`
    },
    {
        name: "🔗 Aggregation",
        description: "ore:Aggregation block",
        code: `<ore:Aggregation rdf:about="{{ zenodo.links.html }}#aggregation">
    <edm:aggregatedCHO rdf:resource="http://data.europeana.eu/item/{{ zenodo.metadata.prereserve_doi.doi }}"/>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html }}"/>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
    <edm:dataProvider>{{ metadata.provider | default('Zenodo') }}</edm:dataProvider>
  </ore:Aggregation>`
    },
    {
        name: "📜 Full Template",
        description: "Complete EDM document wrapper",
        code: `<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/"
         xmlns:skos="http://www.w3.org/2004/02/skos/core#"
         xmlns:foaf="http://xmlns.com/foaf/0.1/">

  <edm:ProvidedCHO rdf:about="http://data.europeana.eu/item/{{ zenodo.metadata.prereserve_doi.doi }}">
    <dc:title>{{ metadata.title }}</dc:title>
    <dc:description>{{ metadata.description }}</dc:description>
    <edm:type>{{ helpers.map_type(metadata.upload_type) }}</edm:type>
  </edm:ProvidedCHO>

  <ore:Aggregation rdf:about="{{ zenodo.links.html }}#aggregation">
    <edm:aggregatedCHO rdf:resource="http://data.europeana.eu/item/{{ zenodo.metadata.prereserve_doi.doi }}"/>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html }}"/>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>`
    }
]

const defaultTemplate = `<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:edm="http://www.europeana.eu/schemas/edm/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         xmlns:dcterms="http://purl.org/dc/terms/"
         xmlns:ore="http://www.openarchives.org/ore/terms/">

  <edm:ProvidedCHO rdf:about="http://data.europeana.eu/item/{{ zenodo.metadata.prereserve_doi.doi }}">
    <dc:title>{{ metadata.title }}</dc:title>
    <dc:description>{{ metadata.description }}</dc:description>

    {% for creator in metadata.creators %}
    <dc:creator>{{ creator.name }}</dc:creator>
    {% endfor %}

    <edm:type>{{ helpers.map_type(metadata.upload_type) }}</edm:type>
  </edm:ProvidedCHO>

  <ore:Aggregation rdf:about="{{ zenodo.links.html }}#aggregation">
    <edm:aggregatedCHO rdf:resource="http://data.europeana.eu/item/{{ zenodo.metadata.prereserve_doi.doi }}"/>
    <edm:isShownAt rdf:resource="{{ zenodo.links.html }}"/>
    <edm:rights rdf:resource="{{ helpers.map_license(metadata.license) }}"/>
  </ore:Aggregation>

</rdf:RDF>`

// Autocompletion for metadata placeholders
function edmCompletions(context) {
    let word = context.matchBefore(/\{\{?\s*[\w.]*/)
    if (!word) return null

    const completions = [
        // Metadata
        { label: "{{ metadata.title }}", type: "variable", info: "Document title" },
        { label: "{{ metadata.description }}", type: "variable", info: "Document description" },
        { label: "{{ metadata.creators }}", type: "variable", info: "List of creators" },
        { label: "{{ metadata.publication_date }}", type: "variable", info: "Publication date" },
        { label: "{{ metadata.cho_created }}", type: "variable", info: "Original object creation date" },
        { label: "{{ metadata.license }}", type: "variable", info: "License ID" },
        { label: "{{ metadata.upload_type }}", type: "variable", info: "Upload type" },
        // Zenodo
        { label: "{{ zenodo.id }}", type: "variable", info: "Zenodo record ID" },
        { label: "{{ zenodo.metadata.prereserve_doi.doi }}", type: "variable", info: "DOI" },
        { label: "{{ zenodo.links.html }}", type: "variable", info: "Record URL" },
        // Helpers
        { label: "{{ helpers.map_type(metadata.upload_type) }}", type: "function", info: "Map to EDM type" },
        { label: "{{ helpers.map_license(metadata.license) }}", type: "function", info: "Map to Rights URI" },
        { label: "{{ helpers.iso_date(metadata.cho_created) }}", type: "function", info: "ISO 8601 CHO creation date" },
        { label: "{{ helpers.iso_date(metadata.publication_date) }}", type: "function", info: "ISO 8601 date" },
        { label: "{{ helpers.generate_uri('agent') }}", type: "function", info: "Generate URI" },
        { label: "{{ helpers.now().isoformat() }}", type: "function", info: "Current timestamp" },
    ]

    return {
        from: word.from,
        options: completions,
        validFor: /^[\w.{}]*$/
    }
}

function initEditor() {
    if (!editorContainer.value) return

    // Destroy existing editor
    if (editorView.value) {
        editorView.value.destroy()
    }

    const xmlHighlightStyle = HighlightStyle.define([
        { tag: t.tagName, color: "#7aa2f7" },
        { tag: t.attributeName, color: "#e0af68" },
        { tag: t.attributeValue, color: "#9ece6a" },
        { tag: t.comment, color: "#565f89", fontStyle: "italic" },
        { tag: t.processingInstruction, color: "#bb9af7" },
        { tag: t.string, color: "#9ece6a" },
        { tag: t.angleBracket, color: "#89ddff" },
        { tag: t.namespace, color: "#f7768e" },
    ])

    const state = EditorState.create({
        doc: form.content,
        extensions: [
            lineNumbers(),
            highlightActiveLine(),
            highlightActiveLineGutter(),
            xml(),
            syntaxHighlighting(xmlHighlightStyle),
            autocompletion({ override: [edmCompletions] }),
            EditorView.updateListener.of((update) => {
                if (update.docChanged) {
                    form.content = update.state.doc.toString()
                }
            }),
            EditorView.theme({
                "&": { height: "100%", fontSize: "14px", backgroundColor: "#1a1b26", color: "#a9b1d6" },
                "&.cm-focused": { outline: "none" },
                ".cm-scroller": { overflow: "auto" },
                ".cm-content": {
                    fontFamily: "'Fira Code', 'JetBrains Mono', monospace",
                    padding: "16px 0",
                    lineHeight: "1.6"
                },
                ".cm-gutters": {
                    backgroundColor: "#1a1b26",
                    color: "#565f89",
                    border: "none",
                },
                ".cm-activeLine": { backgroundColor: "rgba(255, 255, 255, 0.05)" },
                ".cm-activeLineGutter": { backgroundColor: "rgba(255, 255, 255, 0.1)" },
                ".cm-selectionBackground": { backgroundColor: "rgba(255, 255, 255, 0.15) !important" },
            })
        ]
    })

    editorView.value = new EditorView({
        state,
        parent: editorContainer.value
    })
}

function updateEditorContent(content) {
    if (editorView.value) {
        const currentContent = editorView.value.state.doc.toString()
        if (currentContent !== content) {
            editorView.value.dispatch({
                changes: { from: 0, to: currentContent.length, insert: content }
            })
        }
    }
}

function insertAtCursor(text) {
    if (!editorView.value) return

    const pos = editorView.value.state.selection.main.head
    editorView.value.dispatch({
        changes: { from: pos, insert: text },
        selection: { anchor: pos + text.length }
    })
    editorView.value.focus()
}

function insertPlaceholder(code) {
    insertAtCursor(code)
}

function insertSnippet(code) {
    insertAtCursor("\n" + code + "\n")
}

function toggleSampleData() {
    useSampleData.value = !useSampleData.value
}

async function loadTemplates() {
    loading.value = true
    try {
        const res = await api.get('/templates')
        if (res.success) {
            templates.value = res.data.templates
        }
    } catch (e) {
        console.error(e)
        toast.error("Failed to load templates")
    } finally {
        loading.value = false
    }
}


function openCreateModal() {
    isEditing.value = false
    form.id = null
    form.name = ''
    form.description = ''
    form.content = defaultTemplate
    form.is_default = false
    showModal.value = true
    nextTick(() => initEditor())
}

function editTemplate(template) {
    isEditing.value = true
    form.id = template.id
    form.name = template.name
    form.description = template.description
    form.content = template.content
    form.is_default = template.is_default
    showModal.value = true
    nextTick(() => initEditor())
}

function closeModal() {
    showModal.value = false
    if (editorView.value) {
        editorView.value.destroy()
        editorView.value = null
    }
}

async function saveTemplate() {
    saving.value = true
    try {
        if (isEditing.value) {
            await api.put(`/templates/${form.id}`, form)
            toast.success("Template updated successfully")
        } else {
            await api.post('/templates', form)
            toast.success("Template created successfully")
        }
        await loadTemplates()
        closeModal()
    } catch (e) {
        toast.error("Failed to save template: " + (e.error?.message || e.message))
    } finally {
        saving.value = false
    }
}

async function deleteTemplate(id) {
    if (!confirm("Are you sure you want to delete this template?")) return
    try {
        await api.delete(`/templates/${id}`)
        toast.success("Template deleted")
        await loadTemplates()
    } catch (e) {
        toast.error("Failed to delete template")
    }
}

async function preview() {
    try {
       const sampleMeta = useSampleData.value ? {
           title: "Heritage Artifact Collection",
           description: "A comprehensive collection of 3D scanned heritage artifacts from the museum archive.",
           creators: [{name: "Dr. Maria Schmidt"}, {name: "Prof. John Williams"}],
           upload_type: "dataset",
           license: "cc-by",
           publication_date: "2024-06-15"
       } : {
           title: "Test Title",
           description: "Test Description",
           creators: [{name: "Author 1"}],
           upload_type: "dataset",
           license: "cc-by"
       }

       const res = await api.post('/templates/preview', {
           content: form.content,
           metadata: sampleMeta,
           zenodo: { id: 12345, metadata: { prereserve_doi: { doi: "10.5072/12345" } }, links: { html: "http://zenodo.org/record/12345" } }
       })
       if(res.success) {
           console.log(res.data.xml)
           toast.info("Rendered XML logged to console. Check browser inspector.")
       }
    } catch (e) {
        toast.error("Render Error: " + (e.error?.message || e.message))
    }
}

async function validateTemplate() {
    validating.value = true
    validationResults.value = null
    activeRightTab.value = 'validation'

    try {
        const sampleMeta = useSampleData.value ? {
            title: "Heritage Artifact Collection",
            description: "A comprehensive collection of 3D scanned heritage artifacts from the museum archive.",
            creators: [{name: "Dr. Maria Schmidt"}, {name: "Prof. John Williams"}],
            upload_type: "dataset",
            license: "cc-by",
            publication_date: "2024-06-15",
            language: "en",
            country: "EU"
        } : {
            title: "Test Title",
            description: "Test Description",
            creators: [{name: "Author 1"}],
            upload_type: "dataset",
            license: "cc-by",
            language: "en",
            country: "EU"
        }
        const sampleMainFile = {
            key: "sample_model.glb",
            filename: "sample_model.glb",
            content_url: "https://zenodo.org/api/records/12345/files/sample_model.glb/content",
            url: "https://zenodo.org/api/records/12345/files/sample_model.glb/content",
            viewer_url: "",
            mime_type: "model/gltf-binary",
            format: "model/gltf-binary",
            content_type: "3D",
            edm_type: "3D",
            is_3d: true,
            size: 0
        }

        // 1. Preview first to get the XML
        const previewRes = await api.post('/templates/preview', {
            content: form.content,
            metadata: sampleMeta,
            zenodo: { id: 12345, metadata: { prereserve_doi: { doi: "10.5072/12345" } }, links: { html: "http://zenodo.org/record/12345" } },
            main_file: sampleMainFile,
            main_file_key: sampleMainFile.key
        })

        if (!previewRes.success) {
            throw new Error(previewRes.error?.message || "Preview failed")
        }

        const xml = previewRes.data.xml

        // 2. Validate the XML
        const validateRes = await api.post('/templates/validate', { xml, metadata: sampleMeta })

        if (validateRes.success) {
            validationResults.value = validateRes.data
            if (validateRes.data.valid) {
                toast.success("Validation passed!")
            } else {
                toast.warning("Validation found issues.")
            }
        }
    } catch (e) {
        toast.error("Validation Error: " + (e.error?.message || e.message))
        activeRightTab.value = 'guide'
    } finally {
        validating.value = false
    }
}


onMounted(() => {
    loadTemplates()
})

onUnmounted(() => {
    if (editorView.value) {
        editorView.value.destroy()
    }
})
</script>
