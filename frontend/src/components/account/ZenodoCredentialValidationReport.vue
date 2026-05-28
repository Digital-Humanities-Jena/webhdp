<template>
  <div class="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <span
        class="rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide"
        :class="aggregateStatusClass"
      >
        {{ aggregateStatusLabel }}
      </span>
      <span class="rounded-full border border-slate-300 bg-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
        {{ validationModeLabel }}
      </span>
    </div>

    <p class="text-xs text-slate-600">
      {{ summaryText }}
    </p>

    <p class="text-[11px] text-slate-500">
      Recommended scopes:
      <span class="font-medium text-slate-700">{{ recommendedScopesLabel }}</span>
    </p>

    <div class="space-y-2">
      <article
        v-for="item in capabilityItems"
        :key="item.key"
        class="rounded-lg border border-slate-200 bg-white px-3 py-2"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">{{ item.label }}</p>
          <span
            class="rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
            :class="statusClass(item.status)"
          >
            {{ formatStatusLabel(item.status) }}
          </span>
        </div>
        <p class="mt-1 text-xs text-slate-600">{{ item.message }}</p>
      </article>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  credential: {
    type: Object,
    default: null,
  },
})

const liveCapabilityDefinitions = [
  { key: 'authentication', label: 'Authentication' },
  { key: 'deposit_read', label: 'Deposit read' },
  { key: 'draft_create', label: 'Test draft create' },
  { key: 'draft_cleanup', label: 'Test draft cleanup' },
]

const advisoryCapabilityDefinitions = [
  { key: 'authentication', label: 'Authentication' },
  { key: 'deposit_api_access', label: 'Deposit API access' },
  { key: 'deposit_write', label: 'Deposit write' },
  { key: 'deposit_actions', label: 'Deposit actions' },
  { key: 'community_moderation', label: 'Community moderation' },
]

const report = computed(() => props.credential?.validation_report || null)
const aggregateStatus = computed(() => String(props.credential?.validation_status || report.value?.aggregate_status || 'unknown').trim().toLowerCase())
const validationMode = computed(() => String(props.credential?.validation_mode || report.value?.mode || 'live_write_cleanup').trim())
const validationModeLabel = computed(() => {
  if (validationMode.value === 'safe_advisory') return 'Safe advisory'
  if (validationMode.value === 'live_write_cleanup') return 'Live write cleanup'
  return validationMode.value.replace(/_/g, ' ')
})
const recommendedScopesLabel = computed(() => {
  const scopes = props.credential?.recommended_scopes || report.value?.recommended_scopes || []
  return Array.isArray(scopes) && scopes.length ? scopes.join(', ') : 'deposit:write, deposit:actions'
})
const summaryText = computed(() => {
  return report.value?.summary
    || props.credential?.last_validation_error
    || 'Validate the stored token to create and automatically delete a temporary Zenodo draft.'
})
const aggregateStatusLabel = computed(() => {
  if (aggregateStatus.value === 'valid') return 'Valid'
  if (aggregateStatus.value === 'warning') return 'Advisory warning'
  return formatStatusLabel(aggregateStatus.value)
})
const aggregateStatusClass = computed(() => statusClass(aggregateStatus.value))
const capabilityItems = computed(() => {
  const reportCapabilities = report.value?.capabilities || {}
  const definitions = validationMode.value === 'safe_advisory'
    ? advisoryCapabilityDefinitions
    : liveCapabilityDefinitions
  return definitions.map(({ key, label }) => {
    const entry = reportCapabilities[key] || {}
    return {
      key,
      label,
      status: String(entry.status || 'unknown').trim().toLowerCase(),
      message: String(entry.message || 'No validation details available yet.').trim(),
    }
  })
})

function formatStatusLabel(status) {
  const normalized = String(status || 'unknown').trim().toLowerCase()
  if (!normalized) return 'Unknown'
  return normalized.replace(/_/g, ' ')
}

function statusClass(status) {
  const normalized = String(status || 'unknown').trim().toLowerCase()
  if (normalized === 'valid' || normalized === 'verified') return 'bg-emerald-100 text-emerald-700'
  if (normalized === 'warning' || normalized === 'unverified') return 'bg-amber-100 text-amber-700'
  if (normalized === 'invalid') return 'bg-rose-100 text-rose-700'
  if (normalized === 'unreachable') return 'bg-slate-200 text-slate-700'
  return 'bg-gray-100 text-gray-700'
}
</script>
