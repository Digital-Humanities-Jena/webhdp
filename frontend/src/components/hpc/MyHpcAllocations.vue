<template>
  <section class="rounded-xl border border-slate-200 bg-white p-5" aria-labelledby="my-allocation-title" :aria-busy="loading">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 id="my-allocation-title" class="text-lg font-semibold text-slate-950">Your HPC allocations</h2>
      <button type="button" :disabled="loading || Boolean(releasing)" class="text-sm font-medium text-indigo-700 underline disabled:opacity-50" @click="refresh">Refresh allocations</button>
    </div>

    <p v-if="loading" class="mt-3 text-sm text-slate-700" role="status">Checking your allocations…</p>
    <p v-if="message" class="mt-3 text-sm text-slate-800" role="status">{{ message }}</p>
    <p v-if="error" class="mt-3 text-sm text-rose-800" role="alert">{{ error }}</p>

    <dl v-if="quota" class="mt-4 grid gap-3 rounded-lg bg-slate-50 p-4 text-sm text-slate-700 sm:grid-cols-2">
      <div><dt class="font-medium text-slate-950">Active allocations</dt><dd>{{ quota.active }} of {{ quota.active_limit }}</dd></div>
      <div><dt class="font-medium text-slate-950">Requests waiting in WebHDP</dt><dd>{{ quota.queued }} of {{ quota.queued_limit }}</dd></div>
      <div><dt class="font-medium text-slate-950">GPUs per new allocation</dt><dd>Up to {{ quota.max_gpu_count }}</dd></div>
      <div><dt class="font-medium text-slate-950">New allocation duration</dt><dd>Up to {{ quota.max_duration_minutes }} minutes</dd></div>
    </dl>
    <p v-if="quota" class="mt-2 text-xs text-slate-600">A request sent to the cluster scheduler uses an active slot while it waits for resources.</p>

    <p v-if="loaded && !allocations.length" class="mt-4 text-sm text-slate-700">You have no queued or active allocations.</p>
    <ul v-else-if="allocations.length" class="mt-4 divide-y divide-slate-200">
      <li v-for="allocation in allocations" :key="allocation.allocation_id" class="flex flex-wrap items-center justify-between gap-3 py-3">
        <div>
          <p class="text-sm font-semibold text-slate-950">{{ allocationTitle(allocation) }}</p>
          <p class="mt-1 text-sm text-slate-700">{{ allocationState(allocation) }}</p>
          <p class="mt-1 text-xs text-slate-600">
            {{ allocation.requested_gpu_count ? `${allocation.requested_gpu_count} GPU${allocation.requested_gpu_count === 1 ? '' : 's'}` : 'CPU allocation' }}
            <template v-if="allocation.expires_at"> · Ends {{ expiryLabel(allocation.expires_at) }}</template>
          </p>
        </div>
        <button
          v-if="allocation.can_release !== false && allocation.status !== 'releasing'"
          type="button" :disabled="Boolean(releasing) || loading"
          class="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50"
          @click="release(allocation)"
        >
          {{ releasing === allocation.allocation_id ? 'Releasing…' : allocation.status === 'queued' ? 'Cancel request' : 'Release allocation' }}
        </button>
        <p v-else-if="allocation.status === 'running'" class="text-xs text-slate-600">Release becomes available when the run finishes.</p>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import hpcLinkService from '@/services/hpcLink.service'

const quota = ref(null)
const allocations = ref([])
const loading = ref(false)
const loaded = ref(false)
const error = ref('')
const message = ref('')
const releasing = ref('')
let controller
let refreshTimer

const pending = allocation => ['queued', 'allocating'].includes(allocation.status)

function allocationTitle(allocation) {
  const label = allocation.reservation_id ? 'Reserved GPU' : allocation.purpose === 'playground' ? 'Playground allocation' : 'Workflow allocation'
  return allocation.session_id ? `${label} for session ${allocation.session_id}` : label
}

function allocationState(allocation) {
  if (allocation.awaiting_confirmation) return 'Waiting for the gateway to confirm this request'
  if (allocation.status === 'allocating' && allocation.reservation_id) return 'Confirming the reserved GPU'
  if (allocation.status === 'running') return allocation.can_release === false ? 'In use' : 'Ready'
  return ({ queued: 'Queued in WebHDP', allocating: 'Waiting for the HPC scheduler', releasing: 'Releasing resources' })[allocation.status] || 'Checking allocation status'
}

function expiryLabel(value) {
  const date = new Date(/(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`)
  return Number.isNaN(date.getTime()) ? 'at the scheduler deadline' : date.toLocaleString()
}

async function refresh() {
  if (controller) return
  window.clearTimeout(refreshTimer)
  const request = new AbortController()
  controller = request
  loading.value = true
  error.value = ''
  try {
    const options = { signal: request.signal, suppressGlobalError: true }
    const own = await hpcLinkService.listMyAllocations(options)
    if (request.signal.aborted) return
    const listed = own.data?.allocations || []
    for (const [index, allocation] of listed.entries()) {
      if (!pending(allocation) || request.signal.aborted) continue
      const latest = await hpcLinkService.getAllocation(allocation.allocation_id, options).catch(() => null)
      if (latest?.data?.allocation) listed[index] = { ...allocation, ...latest.data.allocation }
    }
    if (request.signal.aborted) return
    allocations.value = listed.filter(allocation => ['queued', 'allocating', 'running', 'releasing'].includes(allocation.status))
    const status = await hpcLinkService.getStatus({}, options)
    if (request.signal.aborted) return
    quota.value = status.data?.quota || null
    loaded.value = true
  } catch {
    if (!request.signal.aborted) error.value = 'Could not load your HPC allocations. Refresh to try again.'
  } finally {
    controller = undefined
    if (!request.signal.aborted) {
      loading.value = false
      if (allocations.value.some(pending)) refreshTimer = window.setTimeout(refresh, document.hidden ? 15000 : 5000)
    }
  }
}

async function release(allocation) {
  if (releasing.value) return
  releasing.value = allocation.allocation_id
  message.value = ''
  error.value = ''
  try {
    await hpcLinkService.releaseAllocation(allocation.allocation_id, { suppressGlobalError: true })
    message.value = allocation.status === 'queued' ? 'Request cancelled.' : 'Allocation released.'
    await refresh()
  } catch (failure) {
    error.value = failure?.error?.message || 'Could not release the allocation.'
  } finally {
    releasing.value = ''
  }
}

defineExpose({ refresh })
onMounted(refresh)
onBeforeUnmount(() => {
  window.clearTimeout(refreshTimer)
  controller?.abort()
})
</script>
