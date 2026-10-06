<template>
  <section v-if="outcomes?.records?.length" aria-label="Record results" class="text-left space-y-3" data-testid="submission-outcomes">
    <p class="text-sm text-slate-700">{{ outcomes.summary.completed }} completed · {{ outcomes.summary.needs_attention }} need attention · {{ outcomes.summary.drafts }} drafts · {{ outcomes.summary.published }} published</p>
    <p class="text-xs text-slate-500">Processing and publication are separate. Review generated files and metadata before publishing a draft.</p>
    <RouterLink v-if="outcomes.can_recover && canEdit" :to="outcomes.recovery_route" class="inline-flex min-h-11 items-center text-sm font-semibold text-indigo-700 underline">Review and continue failed work</RouterLink>
    <details v-for="record in outcomes.records" :key="record.record_id" class="rounded-lg border border-slate-200 px-3 py-2" :open="record.status === 'needs_attention'">
      <summary class="cursor-pointer text-sm text-slate-800">{{ record.filename }} · {{ record.status === 'needs_attention' ? 'Needs attention' : 'Processing completed' }} · {{ record.publication_status }}</summary>
      <p v-if="record.issue" class="mt-2 text-sm text-rose-800">{{ record.issue }}</p>
      <ul class="mt-2 space-y-1 text-xs text-slate-700">
        <li v-for="step in record.steps" :key="step.id">{{ step.name }}: {{ step.status.replaceAll('_', ' ') }}{{ step.reused ? ' (verified output reused)' : '' }}<span v-if="step.issue"> — {{ step.issue }}</span></li>
        <li v-for="(warning, index) in record.warnings" :key="`warning-${index}`" class="text-amber-800">{{ typeof warning === 'string' ? warning : warning.message }}</li>
      </ul>
      <RouterLink :to="!canEdit && record.next_action.route.includes('recoverRunId') ? record.record_route : record.next_action.route" class="inline-flex min-h-11 items-center text-sm text-indigo-700 underline">{{ !canEdit && record.next_action.route.includes('recoverRunId') ? 'Review record issues' : record.next_action.label }}</RouterLink>
    </details>
  </section>
</template>

<script setup>
defineProps({ outcomes: Object, canEdit: { type: Boolean, default: true } })
</script>
