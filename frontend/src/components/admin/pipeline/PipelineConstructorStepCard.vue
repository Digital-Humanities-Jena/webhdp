<template>
  <details :open="expanded" @toggle="expanded = $event.target.open"
    class="rounded-2xl border border-slate-200 bg-slate-50 p-4 transition sm:p-5"
    :class="actions.isStepDropTarget(step) ? 'ring-2 ring-indigo-200 ring-offset-2 ring-offset-white' : ''"
    :data-testid="`step-card-${step.id}`"
    @dragover.prevent="actions.setStepDropTarget(step)"
    @drop.prevent="actions.dropStepOn(step)"
  >
    <summary class="mb-4 cursor-pointer rounded-lg text-sm font-semibold text-slate-800 focus-visible:ring-2 focus-visible:ring-indigo-500">
      {{ index + 1 }}. {{ step.name }} <span class="font-normal text-slate-500">· {{ step.enabled ? 'Enabled' : 'Disabled' }} · {{ step.component_ref }} {{ step.component_version || '' }}</span>
    </summary>
    <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
      <div class="min-w-0 flex-1 space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <div
            class="cursor-grab rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-600 shadow-sm active:cursor-grabbing"
            draggable="true"
            :data-testid="`step-drag-handle-${step.id}`"
            @dragstart="actions.startStepDrag(step)"
            @dragend="actions.endStepDrag()"
          >
            Drag
          </div>
          <span class="inline-flex h-8 w-8 items-center justify-center rounded-full bg-indigo-100 text-sm font-semibold text-indigo-700">
            {{ index + 1 }}
          </span>
          <input
            :aria-label="`Step ${index + 1} name`" v-model.trim="step.name"
            type="text"
            class="min-w-[14rem] flex-1 rounded-xl border border-slate-300 px-3 py-2 text-sm font-medium text-slate-900"
          />
          <span class="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
            {{ step.component_ref }}
          </span>
          <span class="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
            {{ getComponentCategory() }}
          </span>
        </div>
        <textarea :aria-label="`Description for ${step.name}`" v-model="step.description" rows="2" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" />
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <button type="button" class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="index === 0" @click="actions.moveStep(index, -1)">Up</button>
        <button type="button" class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" :disabled="index === totalSteps - 1" @click="actions.moveStep(index, 1)">Down</button>
        <button type="button" class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="actions.duplicateStep(index)">Duplicate</button>
        <button type="button" class="rounded-xl border border-rose-300 bg-white px-3 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50" @click="actions.removeStep(index)">Remove</button>
      </div>
    </div>

    <div class="mt-5 grid gap-4 md:grid-cols-3">
      <div>
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Execution Profile</label>
        <select :aria-label="`Runtime for ${step.name}`" v-model="step.execution_profile_ref" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
          <option v-for="profile in getComponentProfiles()" :key="profile.id" :value="profile.id">
            {{ profile.label || (profile.id === 'builtin_default' ? 'Built-in runtime' : profile.id) }}
          </option>
        </select>
      </div>
      <div>
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Scope</label>
        <select :aria-label="`Run scope for ${step.name}`" v-model="step.scope" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
          <option value="record">Each file separately</option>
          <option value="batch">Files together as a batch</option>
          <option value="pipeline">Once for the whole pipeline</option>
        </select>
      </div>
      <div>
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Enabled</label>
        <select :aria-label="`Enable ${step.name}`" v-model="step.enabled" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
          <option :value="true">Enabled</option>
          <option :value="false">Disabled</option>
        </select>
      </div>
    </div>

    <div role="tablist" :aria-label="`Settings for ${step.name}`" @keydown="onTabKeydown" class="mt-5 flex flex-wrap gap-2 border-t border-slate-200 pt-4">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        role="tab"
        :data-tab="tab.id"
        :id="`${step.localKey}-tab-${tab.id}`"
        :aria-selected="activeTab === tab.id"
        :aria-controls="`${step.localKey}-panel`"
        :tabindex="activeTab === tab.id ? 0 : -1"
        type="button"
        class="rounded-lg px-3 py-1.5 text-xs font-semibold transition"
        :class="activeTab === tab.id ? 'bg-indigo-600 text-white' : 'bg-white text-slate-700 hover:bg-slate-100'"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
        <span v-if="tab.count !== null" class="ml-1 opacity-80">{{ tab.count }}</span>
      </button>
    </div>

    <div role="tabpanel" :id="`${step.localKey}-panel`" :aria-labelledby="`${step.localKey}-tab-${activeTab}`">
    <PipelineConstructorStepInputs
      v-if="activeTab === 'inputs'"
      :step="step"
      :helpers="helpers"
      :actions="actions"
    />

    <PipelineConstructorStepBaseConfig
      v-if="activeTab === 'parameters'"
      :step="step"
      :helpers="helpers"
      :actions="actions"
      :preflight-session-id="preflightSessionId"
      :constructor-session-files="constructorSessionFiles"
      :constructor-session-directories="constructorSessionDirectories"
    />

    <PipelineConstructorStepTriggers
      v-if="activeTab === 'triggers'"
      :step="step"
      :helpers="helpers"
      :actions="actions"
      :preflight-session-id="preflightSessionId"
      :constructor-session-files="constructorSessionFiles"
      :constructor-session-directories="constructorSessionDirectories"
    />

    <PipelineConstructorStepOutputSummary
      v-if="activeTab === 'outputs'"
      :step="step"
      :helpers="helpers"
      :actions="actions"
    />

    <section v-if="activeTab === 'advanced'" class="mt-5 rounded-2xl border border-white bg-white p-4 shadow-sm">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Advanced JSON</h3>
        <span class="text-xs text-slate-500">Unsupported or legacy entries are preserved here</span>
      </div>
      <textarea
        :aria-label="`Advanced configuration for ${step.name}`" v-model="step.advancedJson"
        rows="9"
        class="mt-4 w-full rounded-2xl border border-slate-300 px-3 py-2 font-mono text-xs"
        :data-testid="`advanced-json-${step.id}`"
      />
    </section>
    </div>
  </details>
</template>

<script setup>
import { computed, ref, toRefs } from 'vue'
import PipelineConstructorStepBaseConfig from '@/components/admin/pipeline/PipelineConstructorStepBaseConfig.vue'
import PipelineConstructorStepInputs from '@/components/admin/pipeline/PipelineConstructorStepInputs.vue'
import PipelineConstructorStepOutputSummary from '@/components/admin/pipeline/PipelineConstructorStepOutputSummary.vue'
import PipelineConstructorStepTriggers from '@/components/admin/pipeline/PipelineConstructorStepTriggers.vue'

const props = defineProps({
  step: {
    type: Object,
    required: true,
  },
  index: {
    type: Number,
    required: true,
  },
  totalSteps: {
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
  preflightSessionId: {
    type: String,
    required: true,
  },
  constructorSessionFiles: {
    type: Array,
    required: true,
  },
  constructorSessionDirectories: {
    type: Array,
    required: true,
  },
})

const { step, index, totalSteps, helpers, actions, preflightSessionId, constructorSessionFiles, constructorSessionDirectories } = toRefs(props)
const activeTab = ref(getInitialActiveTab())
const expanded = ref(index.value === 0)

const tabs = computed(() => [
  { id: 'inputs', label: 'Inputs', count: helpers.value.getConstructorInputs(step.value).length },
  { id: 'parameters', label: 'Parameters', count: helpers.value.getParameterGroups(step.value).length },
  { id: 'triggers', label: 'Triggers', count: step.value.triggers?.rules?.length || 0 },
  { id: 'outputs', label: 'Outputs', count: step.value.outputMappings?.length || 0 },
  { id: 'advanced', label: 'Advanced JSON', count: null },
])

function onTabKeydown(event) {
  const index = tabs.value.findIndex(tab => tab.id === activeTab.value)
  const next = event.key === 'ArrowRight' ? (index + 1) % tabs.value.length : event.key === 'ArrowLeft' ? (index - 1 + tabs.value.length) % tabs.value.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.value.length - 1 : null
  if (next === null) return
  event.preventDefault()
  activeTab.value = tabs.value[next].id
  event.currentTarget.querySelector(`[data-tab="${activeTab.value}"]`)?.focus()
}

function getComponentCategory() {
  return helpers.value.getComponentForStep(step.value)?.constructor_schema?.metadata?.category || 'Uncategorized'
}

function getComponentProfiles() {
  return helpers.value.getComponentProfiles(step.value)
}

function getInitialActiveTab() {
  if ((step.value.triggers?.rules || []).length > 0) {
    return 'triggers'
  }
  if ((step.value.outputMappings || []).length > 0 || helpers.value.getJsonOutputs(step.value).length > 0) {
    return 'outputs'
  }
  return 'inputs'
}
</script>
