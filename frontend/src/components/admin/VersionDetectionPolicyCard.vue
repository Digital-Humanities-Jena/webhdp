<template>
  <section class="bg-white shadow rounded-lg mt-8" data-testid="version-detection-policy-card">
    <div class="px-6 py-4 border-b border-gray-200 flex items-start justify-between gap-4">
      <div>
        <h2 class="text-lg font-medium text-gray-900">Version Detection Policy</h2>
        <p class="mt-1 text-sm text-gray-600">
          Configure the default recommendation policy for pre-batch record resolution analysis.
        </p>
      </div>
      <button
        type="button"
        class="px-3 py-1.5 text-xs font-medium text-indigo-600 border border-indigo-200 rounded-full hover:bg-indigo-50 disabled:opacity-60"
        :disabled="loading || saving"
        data-testid="policy-refresh"
        @click="loadConfig"
      >
        {{ loading ? 'Loading...' : 'Refresh' }}
      </button>
    </div>

    <div v-if="loading" class="p-6 text-sm text-gray-500">
      Loading version detection policy...
    </div>

    <div v-else class="p-6 space-y-6">
      <div
        v-if="loadError"
        class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        data-testid="policy-error"
      >
        {{ loadError }}
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="space-y-2">
          <label for="policy-preset" class="block text-sm font-medium text-gray-700">
            Default policy preset
          </label>
          <select
            id="policy-preset"
            v-model="form.preset"
            class="block w-full rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500"
            data-testid="policy-preset-select"
            :disabled="saving"
            @change="handlePresetChange"
          >
            <option v-for="option in presetOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <p class="text-xs text-gray-500">
            {{ selectedPresetDescription }}
          </p>
        </div>

        <div class="space-y-3">
          <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
            <div class="flex items-start justify-between gap-4">
              <div>
                <p class="text-sm font-medium text-gray-900">Allow force-create override</p>
                <p class="mt-1 text-xs text-gray-500">
                  Lets reviewers explicitly bypass a blocker as a risky fresh-record action.
                </p>
              </div>
              <input
                v-model="form.allow_force_create_fresh"
                type="checkbox"
                class="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                data-testid="policy-allow-force"
                :disabled="saving"
              />
            </div>
          </div>

          <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
            <p class="text-sm font-medium text-gray-900">Enabled soft signals</p>
            <div class="mt-3 space-y-3">
              <label class="flex items-start justify-between gap-4">
                <div>
                  <span class="block text-sm text-gray-800">Hash matching</span>
                  <span class="block text-xs text-gray-500">
                    Strong positive evidence when the candidate source hash matches an existing record.
                  </span>
                </div>
                <input
                  v-model="form.enabled_signals.hash_matching"
                  type="checkbox"
                  class="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  data-testid="policy-signal-hash"
                  :disabled="saving"
                />
              </label>
              <label class="flex items-start justify-between gap-4">
                <div>
                  <span class="block text-sm text-gray-800">Metadata similarity</span>
                  <span class="block text-xs text-gray-500">
                    Advisory title, creator, and publication-date similarity scoring.
                  </span>
                </div>
                <input
                  v-model="form.enabled_signals.metadata_similarity"
                  type="checkbox"
                  class="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  data-testid="policy-signal-metadata"
                  :disabled="saving"
                />
              </label>
            </div>
          </div>
        </div>
      </div>

      <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Global Hash Collision Warnings</h3>
            <p class="mt-1 text-sm text-slate-500">
              Warn users when an uploaded source file matches the content hash of an existing Zenodo record.
            </p>
          </div>
          <input
            v-model="form.hash_collision_policy.enabled"
            type="checkbox"
            class="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            data-testid="policy-hash-collision-enabled"
            :disabled="saving"
          />
        </div>

        <div class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <label for="policy-hash-min-size" class="block text-sm font-medium text-gray-700">
              Primary exception threshold
            </label>
            <input
              id="policy-hash-min-size"
              v-model.number="form.hash_collision_policy.min_size_bytes"
              type="number"
              min="0"
              step="1024"
              class="mt-1 block w-full rounded-md border-gray-300 text-sm focus:border-indigo-500 focus:ring-indigo-500"
              data-testid="policy-hash-min-size"
              :disabled="saving || !form.hash_collision_policy.enabled"
            />
            <p class="mt-1 text-xs text-gray-500">
              Files smaller than this byte size are ignored.
            </p>
          </div>

          <label class="rounded-lg border border-slate-200 bg-white px-4 py-3">
            <div class="flex items-start justify-between gap-4">
              <div>
                <span class="block text-sm font-medium text-gray-800">Exclude generated renders</span>
                <span class="block text-xs text-gray-500">
                  Ignores render, thumbnail, preview, derived, and fast_renderer outputs.
                </span>
              </div>
              <input
                v-model="form.hash_collision_policy.exclude_generated_renders"
                type="checkbox"
                class="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                data-testid="policy-hash-exclude-generated"
                :disabled="saving || !form.hash_collision_policy.enabled"
              />
            </div>
          </label>
        </div>

        <div class="mt-4">
          <label for="policy-hash-excluded-extensions" class="block text-sm font-medium text-gray-700">
            Secondary exception extensions
          </label>
          <textarea
            id="policy-hash-excluded-extensions"
            :value="excludedExtensionsText"
            rows="2"
            class="mt-1 block w-full rounded-md border-gray-300 font-mono text-sm focus:border-indigo-500 focus:ring-indigo-500"
            data-testid="policy-hash-excluded-extensions"
            :disabled="saving || !form.hash_collision_policy.enabled"
            @input="handleExcludedExtensionsInput"
          />
          <p class="mt-1 text-xs text-gray-500">
            Comma-separated file extensions to ignore during global hash collision checks.
          </p>
        </div>
      </div>

      <div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Preset Thresholds</h3>
            <p class="mt-1 text-sm text-slate-500">
              Thresholds are derived from the selected preset and are shown for review only.
            </p>
          </div>
          <span class="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
            {{ presetLabel(form.preset) }}
          </span>
        </div>
        <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          <div
            v-for="threshold in thresholdRows"
            :key="threshold.key"
            class="rounded-lg border border-slate-200 bg-white px-4 py-3"
          >
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">{{ threshold.label }}</p>
            <p class="mt-2 text-2xl font-semibold text-slate-900" :data-testid="`policy-threshold-${threshold.key}`">
              {{ formatThreshold(threshold.value) }}
            </p>
          </div>
        </div>
      </div>

      <div class="flex flex-col gap-3 border-t border-gray-200 pt-4 md:flex-row md:items-center md:justify-between">
        <div class="text-sm text-gray-500" data-testid="policy-dirty-state">
          {{ dirty ? 'Unsaved changes' : 'Saved configuration loaded' }}
        </div>
        <div class="flex flex-wrap gap-3">
          <button
            type="button"
            class="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
            :disabled="saving || !dirty"
            data-testid="policy-restore-saved"
            @click="restoreSaved"
          >
            Discard Changes
          </button>
          <button
            type="button"
            class="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60"
            :disabled="saving"
            data-testid="policy-reset-defaults"
            @click="resetToDefaults"
          >
            Restore Defaults
          </button>
          <button
            type="button"
            class="px-4 py-2 border border-transparent rounded-md text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60"
            :disabled="saving || !dirty"
            data-testid="policy-save"
            @click="saveConfig"
          >
            {{ saving ? 'Saving...' : 'Save Policy' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import adminService from '@/services/admin.service'
import { useToast } from '@/composables/useToast'

const toast = useToast()

const PRESET_OPTIONS = [
  {
    value: 'strict',
    label: 'Strict',
    description: 'Favor blockers and require stronger evidence before recommending versioning.',
  },
  {
    value: 'balanced',
    label: 'Balanced',
    description: 'Blend hard lineage rules with soft evidence scoring for everyday operation.',
  },
  {
    value: 'permissive',
    label: 'Permissive',
    description: 'Lower soft-match thresholds and surface more version-review candidates.',
  },
]

const PRESET_THRESHOLDS = {
  strict: {
    version_recommendation_score: 0.95,
    warning_score: 0.45,
  },
  balanced: {
    version_recommendation_score: 0.9,
    warning_score: 0.35,
  },
  permissive: {
    version_recommendation_score: 0.8,
    warning_score: 0.25,
  },
}

const THRESHOLD_LABELS = {
  version_recommendation_score: 'Version Recommendation Score',
  warning_score: 'Warning Score',
}

const DEFAULT_HASH_COLLISION_POLICY = {
  enabled: true,
  min_size_bytes: 1024 * 1024,
  excluded_extensions: ['.csv', '.json', '.log', '.md', '.text', '.tsv', '.txt', '.xml'],
  exclude_generated_renders: true,
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value))
}

function normalizePreset(rawValue) {
  const normalized = String(rawValue || 'balanced').trim().toLowerCase()
  return PRESET_OPTIONS.some((option) => option.value === normalized) ? normalized : 'balanced'
}

function thresholdsForPreset(preset) {
  return {
    ...PRESET_THRESHOLDS[normalizePreset(preset)],
  }
}

function normalizeThresholds(rawValue, preset) {
  const defaults = thresholdsForPreset(preset)
  const value = rawValue && typeof rawValue === 'object' ? rawValue : {}

  const versionRecommendationScore = Number(value.version_recommendation_score)
  const warningScore = Number(value.warning_score)

  return {
    version_recommendation_score: Number.isFinite(versionRecommendationScore)
      ? versionRecommendationScore
      : defaults.version_recommendation_score,
    warning_score: Number.isFinite(warningScore)
      ? warningScore
      : defaults.warning_score,
  }
}

function normalizeExtension(rawValue) {
  const value = String(rawValue || '').trim().toLowerCase()
  if (!value) return ''
  return value.startsWith('.') ? value : `.${value}`
}

function normalizeExcludedExtensions(rawValue) {
  const values = Array.isArray(rawValue)
    ? rawValue
    : String(rawValue || '').split(',')
  return Array.from(new Set(values.map(normalizeExtension).filter(Boolean))).sort()
}

function normalizeHashCollisionPolicy(rawValue) {
  const value = rawValue && typeof rawValue === 'object' ? rawValue : {}
  const minSize = Number(value.min_size_bytes)

  return {
    enabled: Boolean(value.enabled === undefined ? DEFAULT_HASH_COLLISION_POLICY.enabled : value.enabled),
    min_size_bytes: Number.isFinite(minSize)
      ? Math.max(0, Math.trunc(minSize))
      : DEFAULT_HASH_COLLISION_POLICY.min_size_bytes,
    excluded_extensions: normalizeExcludedExtensions(
      value.excluded_extensions === undefined
        ? DEFAULT_HASH_COLLISION_POLICY.excluded_extensions
        : value.excluded_extensions
    ),
    exclude_generated_renders: Boolean(
      value.exclude_generated_renders === undefined
        ? DEFAULT_HASH_COLLISION_POLICY.exclude_generated_renders
        : value.exclude_generated_renders
    ),
  }
}

function normalizeConfig(rawValue) {
  const value = rawValue && typeof rawValue === 'object' ? rawValue : {}
  const preset = normalizePreset(value.preset)
  const enabledSignals = value.enabled_signals && typeof value.enabled_signals === 'object'
    ? value.enabled_signals
    : {}

  return {
    preset,
    thresholds: normalizeThresholds(value.thresholds, preset),
    allow_force_create_fresh: Boolean(
      value.allow_force_create_fresh === undefined ? true : value.allow_force_create_fresh
    ),
    enabled_signals: {
      hash_matching: Boolean(
        enabledSignals.hash_matching === undefined ? true : enabledSignals.hash_matching
      ),
      metadata_similarity: Boolean(
        enabledSignals.metadata_similarity === undefined ? true : enabledSignals.metadata_similarity
      ),
    },
    hash_collision_policy: normalizeHashCollisionPolicy(value.hash_collision_policy),
  }
}

const loading = ref(true)
const saving = ref(false)
const loadError = ref('')
const savedConfig = ref(normalizeConfig({}))
const form = ref(normalizeConfig({}))

const presetOptions = PRESET_OPTIONS

const dirty = computed(() => JSON.stringify(savedConfig.value) !== JSON.stringify(form.value))

const selectedPresetDescription = computed(() => {
  return PRESET_OPTIONS.find((option) => option.value === form.value.preset)?.description || ''
})

const thresholdRows = computed(() => {
  return Object.entries(form.value.thresholds || {}).map(([key, value]) => ({
    key,
    label: THRESHOLD_LABELS[key] || key,
    value,
  }))
})

const excludedExtensionsText = computed(() => {
  return (form.value.hash_collision_policy?.excluded_extensions || []).join(', ')
})

function presetLabel(preset) {
  return PRESET_OPTIONS.find((option) => option.value === preset)?.label || 'Balanced'
}

function formatThreshold(value) {
  return typeof value === 'number' ? value.toFixed(2) : 'n/a'
}

function applyConfig(config) {
  const normalized = normalizeConfig(config)
  savedConfig.value = deepClone(normalized)
  form.value = deepClone(normalized)
}

function handlePresetChange() {
  form.value = {
    ...form.value,
    preset: normalizePreset(form.value.preset),
    thresholds: thresholdsForPreset(form.value.preset),
  }
}

function restoreSaved() {
  form.value = deepClone(savedConfig.value)
}

function resetToDefaults() {
  form.value = normalizeConfig({})
}

function handleExcludedExtensionsInput(event) {
  form.value.hash_collision_policy.excluded_extensions = normalizeExcludedExtensions(event.target.value)
}

async function loadConfig() {
  loading.value = true
  loadError.value = ''
  try {
    const response = await adminService.getVersionDetectionConfig()
    applyConfig(response.data?.config || {})
  } catch (err) {
    loadError.value = err.error?.message || err.error || err.message || 'Failed to load version detection policy.'
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  saving.value = true
  loadError.value = ''
  try {
    const response = await adminService.updateVersionDetectionConfig({
      preset: form.value.preset,
      allow_force_create_fresh: form.value.allow_force_create_fresh,
      enabled_signals: {
        hash_matching: form.value.enabled_signals.hash_matching,
        metadata_similarity: form.value.enabled_signals.metadata_similarity,
      },
      hash_collision_policy: {
        enabled: form.value.hash_collision_policy.enabled,
        min_size_bytes: form.value.hash_collision_policy.min_size_bytes,
        excluded_extensions: form.value.hash_collision_policy.excluded_extensions,
        exclude_generated_renders: form.value.hash_collision_policy.exclude_generated_renders,
      },
    })
    applyConfig(response.data?.config || {})
    toast.success('Version detection policy updated')
  } catch (err) {
    loadError.value = err.error?.message || err.error || err.message || 'Failed to update version detection policy.'
    toast.error(loadError.value)
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>
