<template>
  <div class="rounded-md border border-indigo-200 bg-indigo-50/60 p-3 text-sm text-slate-800">
    <p role="status" aria-live="polite">{{ message }}</p>
    <div v-if="!allocation" class="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-xs font-medium text-indigo-700">
      <RouterLink v-if="needsAccess" :to="{ name: 'HpcResources' }" class="underline" @click.stop>Request HPC access</RouterLink>
      <button type="button" class="underline disabled:opacity-50" :disabled="loading" @click.stop="refresh">Check GPU status again</button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import hpcLinkService from '@/services/hpcLink.service'
import { pendingGpuMessage } from '@/utils/gpuAvailability'

const props = defineProps({
  sessionId: { type: [Number, String], required: true },
  gpuCount: { type: Number, default: 1 },
  componentKeys: { type: Array, default: () => [] },
  allocation: { type: Object, default: null },
  requestsAllocation: { type: Boolean, default: true },
})

const status = ref(null)
const loading = ref(false)
const refreshCount = ref(0)
const minimumGpus = computed(() => Math.max(1, props.gpuCount))

const selectedAllocation = computed(() => props.allocation || (status.value?.gpu_allocation_status ? {
  status: status.value.gpu_allocation_status,
  requested_gpu_count: status.value.gpu_allocation_gpu_count,
  scheduler_reason: status.value.gpu_allocation_scheduler_reason,
} : null))

const usesLocalRuntime = computed(() => props.componentKeys.length > 0 && props.componentKeys.every(key =>
  status.value?.component_runtime?.[key]?.status === 'local_allowed'))
const needsAccess = computed(() => !usesLocalRuntime.value && status.value?.available && status.value.can_allocate === false)

const message = computed(() => {
  const existing = selectedAllocation.value
  if (usesLocalRuntime.value) return 'This pipeline can use the local workstation runtime. WebHDP checks it before starting.'
  if (['running', 'queued', 'allocating'].includes(existing?.status)) {
    if (existing.requested_gpu_count != null && existing.requested_gpu_count < minimumGpus.value) {
      return `This pipeline requires ${minimumGpus.value} ${minimumGpus.value === 1 ? 'GPU' : 'GPUs'}. The current allocation request is too small.`
    }
    if (existing.status === 'running' && existing.requested_gpu_count >= minimumGpus.value) {
      return 'A GPU allocation is ready for this session. WebHDP checks the runtime before starting.'
    }
    if (existing.status === 'running') return 'The GPU count of the current allocation could not be confirmed.'
    return pendingGpuMessage(existing)
  }
  if (status.value?.active_hpc_gpu_count >= minimumGpus.value) return 'A GPU allocation is ready for this session.'
  if (loading.value) return 'Checking GPU status for this session…'
  if (!status.value) return 'GPU status could not be checked. Try again before processing.'
  if (status.value.available === false) return 'GPU access through HPC-Link is unavailable on this WebHDP instance.'
  if (needsAccess.value) return 'Your account needs HPC access to request a GPU.'
  if (status.value.available !== true || status.value.can_allocate !== true) return 'GPU status could not be confirmed. Check again before processing.'
  const nextStep = props.requestsAllocation
    ? 'Starting processing requests a GPU. If none is available, the request waits in the scheduler queue.'
    : 'Assign a GPU allocation before running this pipeline.'
  if (existing?.status === 'failed') return `The previous GPU request failed. ${nextStep}`
  if (['expired', 'released', 'cancelled'].includes(existing?.status)) return `The previous GPU allocation has ended. ${nextStep}`
  return `No GPU is allocated to this session. ${nextStep}`
})

function refresh() {
  refreshCount.value += 1
}

watch([() => props.sessionId, refreshCount], async ([sessionId], _previous, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  status.value = null
  loading.value = Boolean(sessionId)
  if (!sessionId) return
  try {
    const response = await hpcLinkService.getStatus({ purpose: 'workflow', session_id: sessionId }, {
      signal: controller.signal,
      suppressGlobalError: true,
    })
    if (!controller.signal.aborted) status.value = response.data || null
  } catch {
    if (!controller.signal.aborted) status.value = null
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

defineExpose({ refresh })
</script>
