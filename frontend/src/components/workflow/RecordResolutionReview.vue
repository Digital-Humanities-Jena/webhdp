<template>
  <section class="bg-sky-50 rounded-lg border border-sky-200 p-4 space-y-4">
    <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div>
        <h4 class="font-medium text-sky-950">Record resolution review</h4>
        <p class="mt-1 text-sm text-sky-900">
          Review every affected candidate before guided MSF analysis continues. The default action is explainable and can be changed row by row.
        </p>
      </div>
      <div class="w-full max-w-xs">
        <label class="block text-xs font-semibold uppercase tracking-wide text-sky-800 mb-1">Policy preset</label>
        <select
          :value="currentPolicyPreset"
          :disabled="loading || saving"
          class="block w-full rounded-md border-sky-300 bg-white shadow-sm focus:border-sky-500 focus:ring-sky-500 sm:text-sm"
          @change="handlePolicyChange($event.target.value)"
        >
          <option value="strict">Strict</option>
          <option value="balanced">Balanced</option>
          <option value="permissive">Permissive</option>
        </select>
        <p class="mt-1 text-xs text-sky-800">
          Admin default applies automatically. This override only affects the current session.
        </p>
      </div>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
      <div class="rounded-lg border border-white/80 bg-white p-3">
        <p class="text-xs uppercase tracking-wide text-slate-500">All</p>
        <p class="text-xl font-bold text-slate-900">{{ summary.candidate_count || 0 }}</p>
      </div>
      <div class="rounded-lg border border-emerald-100 bg-white p-3">
        <p class="text-xs uppercase tracking-wide text-emerald-600">Clean</p>
        <p class="text-xl font-bold text-emerald-700">{{ summary.clean || 0 }}</p>
      </div>
      <div class="rounded-lg border border-amber-100 bg-white p-3">
        <p class="text-xs uppercase tracking-wide text-amber-600">Warning</p>
        <p class="text-xl font-bold text-amber-700">{{ summary.warning || 0 }}</p>
      </div>
      <div class="rounded-lg border border-indigo-100 bg-white p-3">
        <p class="text-xs uppercase tracking-wide text-indigo-600">Version</p>
        <p class="text-xl font-bold text-indigo-700">{{ summary.version || 0 }}</p>
      </div>
      <div class="rounded-lg border border-rose-100 bg-white p-3">
        <p class="text-xs uppercase tracking-wide text-rose-600">Blocker</p>
        <p class="text-xl font-bold text-rose-700">{{ summary.blocker || 0 }}</p>
      </div>
    </div>

    <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
      <div class="flex flex-wrap gap-2">
        <button
          v-for="filter in filters"
          :key="filter.value"
          type="button"
          class="px-3 py-1.5 text-xs font-semibold rounded-md border transition-colors"
          :class="activeFilter === filter.value ? 'border-sky-400 bg-white text-sky-800' : 'border-sky-100 bg-sky-100/60 text-sky-700 hover:bg-white'"
          @click="activeFilter = filter.value"
        >
          {{ filter.label }}
        </button>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          type="button"
          class="px-3 py-1.5 text-xs font-semibold text-sky-700 bg-white border border-sky-200 rounded-md hover:bg-sky-100 disabled:opacity-50"
          :disabled="loading || saving || !editableCandidates.length"
          @click="acceptRecommendations"
        >
          Accept recommendations
        </button>
        <button
          type="button"
          class="px-3 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-200 rounded-md hover:bg-slate-100 disabled:opacity-50"
          :disabled="loading || saving || !editableCandidates.length"
          @click="setAllAffectedToSkip"
        >
          Set affected to skip
        </button>
      </div>
    </div>

    <div class="rounded-lg border border-white/80 bg-white p-3">
      <p class="text-sm text-slate-700">
        <span class="font-semibold text-slate-900">{{ summary.resolved_count || 0 }}</span>
        of
        <span class="font-semibold text-slate-900">{{ summary.candidate_count || 0 }}</span>
        candidates are resolved.
        <span v-if="summary.unresolved_count" class="text-amber-700">
          {{ summary.unresolved_count }} still need an explicit decision.
        </span>
        <span v-else class="text-emerald-700">
          Guided MSF analysis can continue with the saved plan.
        </span>
      </p>
    </div>

    <div v-if="loading" class="rounded-lg border border-dashed border-sky-300 bg-white px-4 py-5 text-sm text-sky-900">
      Loading record-resolution analysis...
    </div>
    <div v-else-if="!editableCandidates.length" class="rounded-lg border border-dashed border-emerald-300 bg-white px-4 py-5 text-sm text-emerald-800">
      No prepared candidates are available for record-resolution review yet.
    </div>
    <div v-else-if="!filteredCandidates.length" class="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-5 text-sm text-slate-600">
      No candidates match the current filter.
    </div>
    <div v-else class="space-y-3">
      <article
        v-for="candidate in filteredCandidates"
        :key="candidate.decision_key"
        class="rounded-xl border bg-white p-4"
        :class="candidateCardClass(candidate)"
      >
        <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <p class="text-sm font-semibold text-slate-900 break-all">{{ candidate.candidate_filename }}</p>
              <span class="inline-flex rounded-full border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide" :class="severityClass(candidate.severity)">
                {{ candidate.severity }}
              </span>
              <span
                v-if="candidate.resolved || candidate.severity === 'clean'"
                class="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-700"
              >
                Resolved
              </span>
            </div>
            <p class="mt-1 text-xs font-mono text-slate-500 break-all">{{ candidate.normalized_source_file_path }}</p>
            <p class="mt-2 text-sm text-slate-700">{{ candidate.explanation }}</p>
            <div class="mt-3 flex flex-wrap gap-3 text-xs text-slate-600">
              <span>Recommended: <span class="font-semibold text-slate-900">{{ actionLabel(candidate.recommended_action) }}</span></span>
              <span>Confidence: <span class="font-semibold text-slate-900">{{ candidate.confidence?.label || 'low' }}</span> ({{ confidencePercent(candidate.confidence?.score) }})</span>
              <span v-if="candidate.matched_record_count">Matches: <span class="font-semibold text-slate-900">{{ candidate.matched_record_count }}</span></span>
              <span v-if="candidate.hidden_matched_record_count" class="font-semibold text-amber-700">
                {{ candidate.hidden_matched_record_count }} hidden match{{ candidate.hidden_matched_record_count === 1 ? '' : 'es' }}
              </span>
            </div>
            <div
              v-if="(candidate.matched_records || []).length"
              class="mt-3 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3"
            >
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">Colliding Zenodo records</p>
              <div
                v-for="match in (candidate.matched_records || []).slice(0, 3)"
                :key="`${candidate.decision_key}-inline-${match.session_id}-${match.local_record_id}`"
                class="flex flex-col gap-2 text-sm md:flex-row md:items-center md:justify-between"
              >
                <div class="min-w-0">
                  <p class="truncate font-medium text-slate-900">{{ match.record_title || match.normalized_source_file_path || `Record ${match.zenodo_record_id || match.local_record_id}` }}</p>
                  <p class="text-xs text-slate-500">
                    {{ match.environment || (match.is_sandbox ? 'sandbox' : 'production') }} · {{ match.record_status || 'unknown' }}
                    <span v-if="match.zenodo_doi">· {{ match.zenodo_doi }}</span>
                  </p>
                </div>
                <a
                  v-if="match.record_link"
                  :href="match.record_link"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="shrink-0 text-xs font-semibold text-indigo-700 hover:text-indigo-900"
                >
                  Open Zenodo
                </a>
              </div>
              <p v-if="(candidate.matched_records || []).length > 3" class="text-xs text-slate-500">
                {{ (candidate.matched_records || []).length - 3 }} more visible matches are available in Explain.
              </p>
            </div>
          </div>
          <div class="w-full max-w-sm space-y-3">
            <div>
              <label class="block text-xs font-semibold uppercase tracking-wide text-slate-600 mb-1">Selected action</label>
              <select
                :value="candidate.selected_action"
                :disabled="loading || saving"
                class="block w-full rounded-md border-slate-300 bg-white shadow-sm focus:border-sky-500 focus:ring-sky-500 sm:text-sm"
                @change="handleActionChange(candidate, $event.target.value)"
              >
                <option
                  v-for="action in candidate.allowed_actions || []"
                  :key="`${candidate.decision_key}-${action}`"
                  :value="action"
                >
                  {{ actionLabel(action) }}
                </option>
              </select>
            </div>

            <div v-if="candidate.selected_action === 'create_version' && candidate.selected_target" class="rounded-lg border border-indigo-100 bg-indigo-50 p-3 text-xs text-indigo-900">
              <p class="font-semibold">Version target</p>
              <p class="mt-1">{{ candidate.selected_target.record_title || candidate.selected_target.normalized_source_file_path }}</p>
              <p class="mt-1">
                Session {{ candidate.selected_target.session_id }} · Local {{ candidate.selected_target.local_record_id }}
                <span v-if="candidate.selected_target.concept_rec_id">· concept {{ candidate.selected_target.concept_rec_id }}</span>
              </p>
            </div>

            <div v-if="candidate.selected_action === 'force_create_fresh' && candidate.forced_override_reason" class="rounded-lg border border-rose-100 bg-rose-50 p-3 text-xs text-rose-800">
              <p class="font-semibold">Override reason</p>
              <p class="mt-1">{{ candidate.forced_override_reason }}</p>
            </div>

            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                class="px-3 py-1.5 text-xs font-semibold text-slate-700 bg-slate-50 border border-slate-200 rounded-md hover:bg-slate-100"
                @click="inspectedCandidate = candidate"
              >
                Explain
              </button>
              <a
                v-if="candidate.recommended_target?.record_link"
                :href="candidate.recommended_target.record_link"
                target="_blank"
                rel="noopener noreferrer"
                class="px-3 py-1.5 text-xs font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-md hover:bg-indigo-100"
              >
                Open Zenodo
              </a>
            </div>
          </div>
        </div>
      </article>
    </div>

    <div
      v-if="inspectedCandidate"
      class="fixed inset-0 z-40 flex items-center justify-center bg-slate-950/50 px-4 py-8"
      @click.self="inspectedCandidate = null"
    >
      <div class="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white shadow-2xl">
        <div class="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-4">
          <div>
            <h5 class="text-lg font-semibold text-slate-900">{{ inspectedCandidate.candidate_filename }}</h5>
            <p class="mt-1 text-sm text-slate-600">{{ inspectedCandidate.explanation }}</p>
          </div>
          <button
            type="button"
            class="rounded-md border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
            @click="inspectedCandidate = null"
          >
            Close
          </button>
        </div>

        <div class="space-y-6 px-6 py-5">
          <section>
            <h6 class="text-sm font-semibold text-slate-900">Decision summary</h6>
            <dl class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
              <div class="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <dt class="text-xs uppercase tracking-wide text-slate-500">Recommended action</dt>
                <dd class="mt-1 text-sm font-semibold text-slate-900">{{ actionLabel(inspectedCandidate.recommended_action) }}</dd>
              </div>
              <div class="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <dt class="text-xs uppercase tracking-wide text-slate-500">Selected action</dt>
                <dd class="mt-1 text-sm font-semibold text-slate-900">{{ actionLabel(inspectedCandidate.selected_action) }}</dd>
              </div>
              <div class="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <dt class="text-xs uppercase tracking-wide text-slate-500">Confidence</dt>
                <dd class="mt-1 text-sm font-semibold text-slate-900">{{ inspectedCandidate.confidence?.label || 'low' }} ({{ confidencePercent(inspectedCandidate.confidence?.score) }})</dd>
              </div>
              <div class="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <dt class="text-xs uppercase tracking-wide text-slate-500">Reason codes</dt>
                <dd class="mt-1 text-sm text-slate-900">{{ (inspectedCandidate.reason_codes || []).join(', ') || 'None' }}</dd>
              </div>
            </dl>
          </section>

          <section>
            <h6 class="text-sm font-semibold text-slate-900">Evidence</h6>
            <div class="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <pre class="whitespace-pre-wrap break-words text-xs text-slate-700">{{ JSON.stringify(inspectedCandidate.evidence || {}, null, 2) }}</pre>
            </div>
          </section>

          <section>
            <h6 class="text-sm font-semibold text-slate-900">Matched records</h6>
            <div v-if="(inspectedCandidate.matched_records || []).length" class="mt-3 space-y-3">
              <div
                v-for="match in inspectedCandidate.matched_records"
                :key="`${inspectedCandidate.decision_key}-${match.session_id}-${match.local_record_id}`"
                class="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700"
              >
                <p class="font-semibold text-slate-900">{{ match.record_title || match.normalized_source_file_path }}</p>
                <p class="mt-1">Session {{ match.session_id }} · Local {{ match.local_record_id }} · {{ match.record_status }}</p>
                <p v-if="match.zenodo_doi" class="mt-1">{{ match.zenodo_doi }}</p>
                <p v-if="match.concept_rec_id" class="mt-1">Concept {{ match.concept_rec_id }}</p>
                <p v-if="match.source_sha256_hash" class="mt-1 font-mono text-xs break-all">{{ match.source_sha256_hash }}</p>
                <a
                  v-if="match.record_link"
                  :href="match.record_link"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="mt-2 inline-flex text-xs font-semibold text-indigo-700 hover:text-indigo-900"
                >
                  Open Zenodo
                </a>
              </div>
            </div>
            <p v-else class="mt-3 text-sm text-slate-600">No visible matched records were returned for this candidate.</p>
          </section>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  analysis: {
    type: Object,
    default: null,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  saving: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['policy-change', 'save-decisions'])

const inspectedCandidate = ref(null)
const activeFilter = ref('all')
const editableCandidates = ref([])
const currentPolicyPreset = ref('balanced')

const filters = [
  { value: 'all', label: 'All' },
  { value: 'blocker', label: 'Blocker' },
  { value: 'version', label: 'Version' },
  { value: 'warning', label: 'Warning' },
  { value: 'clean', label: 'Clean' },
]

watch(
  () => props.analysis,
  (nextAnalysis) => {
    editableCandidates.value = Array.isArray(nextAnalysis?.candidates)
      ? nextAnalysis.candidates.map((candidate) => ({ ...candidate }))
      : []
    currentPolicyPreset.value = nextAnalysis?.state?.policy_override || nextAnalysis?.policy_preset || 'balanced'
  },
  { immediate: true, deep: true }
)

const summary = computed(() => props.analysis?.summary || {})

const filteredCandidates = computed(() => {
  if (activeFilter.value === 'all') return editableCandidates.value
  return editableCandidates.value.filter((candidate) => String(candidate?.severity || 'clean') === activeFilter.value)
})

const actionLabel = (action) => {
  const labels = {
    create_fresh_record: 'Create fresh record',
    create_version: 'Create version',
    skip: 'Skip',
    force_create_fresh: 'Force create fresh',
  }
  return labels[action] || action || 'Unspecified'
}

const confidencePercent = (score) => `${Math.round(Number(score || 0) * 100)}%`

const severityClass = (severity) => {
  if (severity === 'blocker') return 'border-rose-200 bg-rose-50 text-rose-700'
  if (severity === 'version') return 'border-indigo-200 bg-indigo-50 text-indigo-700'
  if (severity === 'warning') return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-emerald-200 bg-emerald-50 text-emerald-700'
}

const candidateCardClass = (candidate) => {
  if (candidate?.severity === 'blocker') return 'border-rose-200'
  if (candidate?.severity === 'version') return 'border-indigo-200'
  if (candidate?.severity === 'warning') return 'border-amber-200'
  return 'border-emerald-200'
}

const buildDecisionPayload = () => ({
  policy_override: currentPolicyPreset.value,
  decisions: editableCandidates.value
    .filter((candidate) => String(candidate?.severity || 'clean') !== 'clean')
    .map((candidate) => {
      const payload = {
        decision_key: candidate.decision_key,
        action: candidate.selected_action,
        resolved: Boolean(candidate.resolved),
      }
      if (candidate.selected_action === 'create_version') {
        const target = candidate.selected_target || candidate.recommended_target || null
        payload.target_session_id = target?.session_id ?? null
        payload.target_local_record_id = target?.local_record_id ?? null
        payload.target_concept_rec_id = target?.concept_rec_id || null
      }
      if (candidate.selected_action === 'force_create_fresh') {
        payload.forced_override_reason = candidate.forced_override_reason || null
      }
      return payload
    }),
})

const saveDecisions = () => {
  emit('save-decisions', buildDecisionPayload())
}

const handlePolicyChange = (preset) => {
  currentPolicyPreset.value = preset || 'balanced'
  emit('policy-change', currentPolicyPreset.value)
}

const handleActionChange = (candidate, nextAction) => {
  if (!candidate) return

  if (nextAction === 'force_create_fresh') {
    const confirmed = window.confirm(
      'This source path conflicts with another lineage. Force-create will bypass the default guardrail for this row only. Continue?'
    )
    if (!confirmed) {
      return
    }
    const reason = window.prompt('Enter an audit reason for the force-create override:', candidate.forced_override_reason || '')
    if (!reason || !String(reason).trim()) {
      return
    }
    candidate.forced_override_reason = String(reason).trim()
  } else {
    candidate.forced_override_reason = null
  }

  candidate.selected_action = nextAction
  candidate.resolved = String(candidate.severity || 'clean') === 'clean' || Boolean(nextAction)
  if (nextAction === 'create_version') {
    candidate.selected_target = candidate.selected_target || candidate.recommended_target || candidate.matched_records?.[0] || null
  } else {
    candidate.selected_target = null
  }
  saveDecisions()
}

const acceptRecommendations = () => {
  const hasForceCreate = editableCandidates.value.some(
    (candidate) => String(candidate?.severity || 'clean') !== 'clean' && candidate?.recommended_action === 'force_create_fresh'
  )
  let sharedForceReason = null

  if (hasForceCreate) {
    const confirmed = window.confirm(
      'At least one recommendation requires a force-create override. Accepting recommendations will apply that risky action to those rows. Continue?'
    )
    if (!confirmed) return
    const reason = window.prompt('Enter one audit reason for the recommended force-create overrides:', '')
    if (!reason || !String(reason).trim()) {
      return
    }
    sharedForceReason = String(reason).trim()
  }

  editableCandidates.value = editableCandidates.value.map((candidate) => {
    const nextCandidate = { ...candidate }
    if (String(nextCandidate.severity || 'clean') === 'clean') {
      nextCandidate.resolved = true
      return nextCandidate
    }
    nextCandidate.selected_action = nextCandidate.recommended_action
    nextCandidate.selected_target = nextCandidate.recommended_target || null
    nextCandidate.resolved = true
    nextCandidate.forced_override_reason =
      nextCandidate.recommended_action === 'force_create_fresh'
        ? sharedForceReason
        : null
    return nextCandidate
  })
  saveDecisions()
}

const setAllAffectedToSkip = () => {
  editableCandidates.value = editableCandidates.value.map((candidate) => {
    if (String(candidate?.severity || 'clean') === 'clean') {
      return { ...candidate, resolved: true }
    }
    return {
      ...candidate,
      selected_action: 'skip',
      selected_target: null,
      resolved: true,
      forced_override_reason: null,
    }
  })
  saveDecisions()
}
</script>
