<template>
  <div class="space-y-6">
    <section class="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
      <div class="border-b border-slate-200 px-6 py-6">
        <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.22em] text-emerald-700">Tools</p>
            <h2 class="mt-2 text-3xl font-semibold text-slate-950">Playground</h2>
            <p class="mt-2 max-w-3xl text-sm text-slate-600">
              Test one HDP Component with files from an uploaded session. Review its inputs and outputs here before adding it to a pipeline.
            </p>
          </div>

          <div class="flex flex-wrap items-center gap-3">
            <span
              class="rounded-full px-3 py-1 text-xs font-semibold"
              :class="isEnabled ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'"
            >
              {{ isEnabled ? 'Enabled' : 'Disabled' }}
            </span>
            <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              {{ components.length }} {{ components.length === 1 ? 'component' : 'components' }}
            </span>
          </div>
        </div>
      </div>

      <div class="px-6 py-6">
        <div v-if="!isEnabled" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-800">
          {{ disabledReason || 'Playground requires an authenticated session.' }}
        </div>

        <div v-else class="space-y-6">
          <div class="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div class="max-w-2xl text-sm text-slate-600">
              Choose a component, select session files and review its settings. A test form being available does not confirm that its runtime or HPC resources are ready.
            </div>

            <div class="flex flex-wrap items-center gap-3">
              <input
                aria-label="Filter components" v-model.trim="searchQuery"
                type="search"
                class="w-full rounded-2xl border-slate-300 text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:w-72"
                placeholder="Filter components"
              >
              <select
                aria-label="Component category" v-model="selectedCategory"
                class="rounded-2xl border-slate-300 bg-white text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
              >
                <option value="">All categories</option>
                <option v-for="category in categoryOptions" :key="category" :value="category">{{ category }}</option>
              </select>
              <select
                aria-label="Component tag" v-model="selectedTag"
                class="rounded-2xl border-slate-300 bg-white text-sm text-slate-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
              >
                <option value="">All tags</option>
                <option v-for="tag in tagOptions" :key="tag" :value="tag">{{ tag }}</option>
              </select>
            </div>
          </div>

          <div v-if="componentsError" role="alert" class="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">{{ componentsError }} <button type="button" class="font-semibold underline" @click="loadComponents">Retry components</button></div>
          <div v-if="sessionsError" role="alert" class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">{{ sessionsError }} <button type="button" class="font-semibold underline" @click="loadSessions">Retry sessions</button></div>
          <div v-if="loadingComponents" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6">
            <LoadingSpinner text="Loading Playground components..." />
          </div>

          <div v-else-if="!componentsError && filteredComponents.length === 0" class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-6 py-10 text-center">
            <h3 class="text-lg font-semibold text-slate-900">No Playground components available</h3>
            <p class="mt-2 text-sm text-slate-500">
              {{ hasActiveFilters ? 'No components match the current filters.' : 'No components are currently marked as Playground-capable.' }}
            </p>
          </div>

          <div v-else class="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <button
              v-for="component in filteredComponents"
              :key="component.key"
              type="button"
              class="group rounded-3xl border border-slate-200 bg-white px-5 py-5 text-left transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
              @click="openComponent(component)"
            >
              <div class="flex items-start justify-between gap-4">
                <div class="min-w-0">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-600">
                      {{ component.source_type }}
                    </span>
                    <span
                      v-if="componentCategory(component)"
                      class="rounded-full bg-indigo-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-indigo-700"
                    >
                      {{ componentCategory(component) }}
                    </span>
                    <span class="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-emerald-700">
                      Test form available
                    </span>
                  </div>
                  <h3 class="mt-3 text-xl font-semibold text-slate-950">{{ componentLabel(component) }}</h3>
                  <p class="mt-1 text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
                    {{ component.key }} · v{{ component.version }}
                  </p>
                </div>

                <span class="rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold text-white transition group-hover:bg-indigo-600">
                  Open
                </span>
              </div>

              <p class="mt-4 text-sm leading-6 text-slate-600">
                {{ componentDescription(component) }}
              </p>

              <div class="mt-5 flex flex-wrap gap-2">
                <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                  {{ component.profiles?.length || 0 }} {{ component.profiles?.length === 1 ? 'profile' : 'profiles' }}
                </span>
                <span
                  v-for="tag in componentTags(component)"
                  :key="`${component.key}-${tag}`"
                  class="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700"
                >
                  {{ tag }}
                </span>
              </div>
            </button>
          </div>
        </div>
      </div>
    </section>

    <PlaygroundRunnerModal
      :show="Boolean(activeComponent)"
      :component="activeComponent"
      :sessions="sessions"
      :loading-sessions="loadingSessions"
      @close="closeModal"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import PlaygroundRunnerModal from '@/components/tools/PlaygroundRunnerModal.vue'
import fileService from '@/services/file.service'
import pipelineService from '@/services/pipeline.service'
import toolsService from '@/services/tools.service'

const featureState = ref({
  enabled: false,
  reason: ''
})
const components = ref([])
const sessions = ref([])
const activeComponent = ref(null)
const loadingComponents = ref(false)
const componentsError = ref('')
const sessionsError = ref('')
const loadingSessions = ref(false)
const searchQuery = ref('')
const selectedCategory = ref('')
const selectedTag = ref('')

const isEnabled = computed(() => featureState.value.enabled === true)
const disabledReason = computed(() => featureState.value.reason || '')
const hasActiveFilters = computed(() => Boolean(searchQuery.value.trim() || selectedCategory.value || selectedTag.value))

function componentLabel(component) {
  return component?.playground_schema?.title || component?.manifest?.metadata?.label || component?.name || component?.key
}

function componentDescription(component) {
  return component?.playground_schema?.description || component?.manifest?.metadata?.description || component?.description || 'No component description available.'
}

function componentCategory(component) {
  return component?.playground_schema?.metadata?.category || component?.manifest?.metadata?.category || ''
}

function componentTags(component) {
  const tags = Array.isArray(component?.playground_schema?.metadata?.tags)
    ? component.playground_schema.metadata.tags
    : (Array.isArray(component?.manifest?.metadata?.tags) ? component.manifest.metadata.tags : [])
  return tags.slice(0, 5)
}

const categoryOptions = computed(() => Array.from(new Set(
  components.value.map((component) => componentCategory(component)).filter(Boolean)
)).sort())

const tagOptions = computed(() => Array.from(new Set(
  components.value.flatMap((component) => componentTags(component))
)).sort())

const filteredComponents = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()

  return components.value.filter((component) => {
    const matchesCategory = !selectedCategory.value || componentCategory(component) === selectedCategory.value
    const matchesTag = !selectedTag.value || componentTags(component).includes(selectedTag.value)
    const haystack = [
      component.key,
      component.name,
      component.playground_schema?.title,
      component.playground_schema?.description,
      component.playground_schema?.metadata?.category,
      component.manifest?.metadata?.label,
      component.manifest?.metadata?.description,
      ...(component.playground_schema?.metadata?.tags || []),
      ...(component.manifest?.metadata?.tags || [])
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()

    const matchesQuery = !query || haystack.includes(query)
    return matchesCategory && matchesTag && matchesQuery
  })
})

function openComponent(component) {
  activeComponent.value = component
}

function closeModal() {
  activeComponent.value = null
}

async function loadContext() {
  try {
    const response = await toolsService.getContext()
    const feature = response.data?.features?.native_playground || {}
    featureState.value = {
      enabled: feature.enabled === true,
      reason: String(feature.reason || '')
    }
  } catch {
    featureState.value = {
      enabled: false,
      reason: ''
    }
  }
}

async function loadComponents() {
  if (loadingComponents.value) return
  loadingComponents.value = true
  componentsError.value = ''
  try {
    const response = await pipelineService.listComponents({ playgroundOnly: true })
    components.value = response.data?.components || []
  } catch (err) {
    componentsError.value = err?.error?.message || err?.message || 'Could not load components.'
  } finally {
    loadingComponents.value = false
  }
}

async function loadSessions() {
  if (loadingSessions.value) return
  loadingSessions.value = true
  sessionsError.value = ''
  try {
    const response = await fileService.listSessions()
    sessions.value = (response.data?.sessions || []).filter((session) => session.permissions?.can_edit !== false && session.access_mode !== 'explorer_only')
  } catch (err) {
    sessionsError.value = err?.error?.message || err?.message || 'Could not load sessions. Upload a file first if you have no sessions yet.'
  } finally {
    loadingSessions.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadContext(), loadComponents(), loadSessions()])
})
</script>
