<template>
  <section class="mt-5 rounded-2xl border border-white bg-white p-4 shadow-sm">
    <div class="flex items-center justify-between">
      <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Triggers</h3>
      <button type="button" class="rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50" :data-testid="`trigger-add-rule-${step.id}`" @click="actions.addTriggerRule(step)">
        Add Rule
      </button>
    </div>
    <div class="mt-4 grid gap-3 md:grid-cols-2">
      <div>
        <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Default Behavior</label>
        <select v-model="step.triggers.default_behavior" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm">
          <option value="run">run</option>
          <option value="skip">skip</option>
        </select>
      </div>
    </div>
    <div v-if="step.triggers.rules.length === 0" class="mt-4 rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
      No trigger rules yet. Base config runs when no rule matches.
    </div>
    <div v-else class="mt-4 space-y-4">
      <PipelineConstructorTriggerRuleCard
        v-for="(rule, ruleIndex) in step.triggers.rules"
        :key="rule.localKey"
        :step="step"
        :rule="rule"
        :rule-index="ruleIndex"
        :total-rules="step.triggers.rules.length"
        :helpers="helpers"
        :actions="actions"
        :preflight-session-id="preflightSessionId"
        :constructor-session-files="constructorSessionFiles"
        :constructor-session-directories="constructorSessionDirectories"
      />
    </div>
  </section>
</template>

<script setup>
import PipelineConstructorTriggerRuleCard from '@/components/admin/pipeline/PipelineConstructorTriggerRuleCard.vue'

defineProps({
  step: {
    type: Object,
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
