<template>
  <article
    class="rounded-2xl border border-slate-200 bg-slate-50 p-4 transition"
    :class="actions.isTriggerRuleDropTarget(step, rule) ? 'ring-2 ring-indigo-200 ring-offset-2 ring-offset-white' : ''"
    :data-testid="`trigger-rule-${step.id}-${ruleIndex}`"
    @dragover.prevent="actions.setTriggerRuleDropTarget(step, rule)"
    @drop.prevent="actions.dropTriggerRuleOn(step, rule)"
  >
    <div class="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
      <div class="grid flex-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Order</label>
          <div class="flex items-center gap-2">
            <div
              class="cursor-grab rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-600 shadow-sm active:cursor-grabbing"
              draggable="true"
              :data-testid="`trigger-rule-drag-handle-${step.id}-${ruleIndex}`"
              @dragstart="actions.startTriggerRuleDrag(step, rule)"
              @dragend="actions.endTriggerRuleDrag()"
            >
              Drag
            </div>
            <span class="inline-flex h-9 min-w-9 items-center justify-center rounded-xl bg-white px-3 text-xs font-semibold text-slate-600">
              {{ ruleIndex + 1 }}
            </span>
          </div>
        </div>
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Rule ID</label>
          <input v-model.trim="rule.id" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
        </div>
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Label</label>
          <input v-model.trim="rule.label" type="text" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
        </div>
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Action</label>
          <select v-model="rule.action" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
            <option value="run">run</option>
            <option value="skip">skip</option>
          </select>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button
          type="button"
          class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          :disabled="ruleIndex === 0"
          :data-testid="`trigger-rule-up-${step.id}-${ruleIndex}`"
          @click="actions.moveTriggerRule(step, ruleIndex, -1)"
        >
          Up
        </button>
        <button
          type="button"
          class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          :disabled="ruleIndex === totalRules - 1"
          :data-testid="`trigger-rule-down-${step.id}-${ruleIndex}`"
          @click="actions.moveTriggerRule(step, ruleIndex, 1)"
        >
          Down
        </button>
        <button type="button" class="rounded-xl border border-rose-300 bg-white px-3 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50" @click="actions.removeTriggerRule(step, ruleIndex)">
          Remove Rule
        </button>
      </div>
    </div>

    <div class="mt-4 space-y-3">
      <div class="flex items-center justify-between">
        <h4 class="text-xs font-semibold uppercase tracking-wide text-slate-600">Conditions</h4>
        <button type="button" class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="actions.addTriggerCondition(step, rule)">
          Add Condition
        </button>
      </div>

      <PipelineConstructorTriggerConditionRow
        v-for="(condition, conditionIndex) in rule.conditions"
        :key="condition.localKey"
        :step="step"
        :rule="rule"
        :rule-index="ruleIndex"
        :condition="condition"
        :condition-index="conditionIndex"
        :helpers="helpers"
        :actions="actions"
      />
    </div>

    <div class="mt-4 space-y-3">
      <div class="flex items-center justify-between">
        <h4 class="text-xs font-semibold uppercase tracking-wide text-slate-600">Parameter Overrides</h4>
        <button type="button" class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" @click="actions.addParameterOverride(rule)">
          Add Override
        </button>
      </div>

      <PipelineConstructorTriggerOverrideRow
        v-for="(overrideRow, overrideIndex) in rule.parameterOverrideRows"
        :key="overrideRow.localKey"
        :step="step"
        :rule="rule"
        :rule-index="ruleIndex"
        :override-row="overrideRow"
        :override-index="overrideIndex"
        :helpers="helpers"
        :actions="actions"
        :preflight-session-id="preflightSessionId"
        :constructor-session-files="constructorSessionFiles"
        :constructor-session-directories="constructorSessionDirectories"
      />
    </div>
  </article>
</template>

<script setup>
import PipelineConstructorTriggerConditionRow from '@/components/admin/pipeline/PipelineConstructorTriggerConditionRow.vue'
import PipelineConstructorTriggerOverrideRow from '@/components/admin/pipeline/PipelineConstructorTriggerOverrideRow.vue'

defineProps({
  step: {
    type: Object,
    required: true,
  },
  rule: {
    type: Object,
    required: true,
  },
  ruleIndex: {
    type: Number,
    required: true,
  },
  totalRules: {
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
</script>
