import { computed, onBeforeUnmount, ref } from 'vue'
import pipelineService from '@/services/pipeline.service'

export function usePersistentPipelineRun(userId) {
  const run = ref(null)
  const error = ref('')
  const trackingUnavailable = ref(false)
  const submitting = ref(false)
  const pending = ref(null)
  const now = ref(Date.now())
  let pollTimer
  let disposed = false
  let refreshing = false
  const storageKey = () => `pipeline-run:${userId()}`
  const active = computed(() => Boolean(pending.value && !['completed', 'failed', 'cancelled'].includes(run.value?.status)))
  const elapsed = computed(() => {
    const start = new Date(run.value?.started_at || pending.value?.startedAt).getTime()
    return Number.isFinite(start) ? Math.max(0, Math.floor(((run.value?.completed_at ? new Date(run.value.completed_at).getTime() : now.value) - start) / 1000)) : 0
  })
  function persist() {
    try { sessionStorage.setItem(storageKey(), JSON.stringify(pending.value)) } catch { /* Monitoring remains available in the current page. */ }
  }
  function schedule() {
    clearTimeout(pollTimer)
    if (active.value && !disposed && !trackingUnavailable.value) pollTimer = setTimeout(refresh, 3000)
  }
  async function refresh() {
    if (!pending.value || refreshing || disposed) return
    refreshing = true
    const runId = pending.value.runId
    try {
      const response = await pipelineService.getPipelineRun(pending.value.runId)
      if (disposed || pending.value?.runId !== runId) return
      run.value = response.data?.run || response.data
      error.value = ''
      trackingUnavailable.value = false
      if (run.value?.status === 'failed') error.value = run.value.error || 'The run failed. Review its step results before starting a new run.'
    } catch (err) {
      if (disposed || pending.value?.runId !== runId) return
      const status = err?.response?.status || err?.status
      trackingUnavailable.value = [403, 404, 410].includes(status) || ['FORBIDDEN', 'NOT_FOUND', 'RESOURCE_NOT_FOUND', 'SECURITY_ERROR'].includes(err?.error?.code)
      error.value = err?.error?.message || err?.message || 'Status is temporarily unavailable. Processing may still be running; reconnect to this run.'
    } finally {
      refreshing = false
      schedule()
    }
  }
  async function submit() {
    if (submitting.value || !pending.value?.request) return
    submitting.value = true
    error.value = ''
    const request = pending.value.request
    try {
      const response = await pipelineService.executePipelineOnFiles(request.sessionId, request.paths, true, request.identifier, {
        asyncExecution: true, abortOnCriticalError: true, requestId: pending.value.runId,
        expectedVersion: request.version, preflightToken: request.preflightToken,
      })
      pending.value.runId = response.data.run_id
      persist()
      await refresh()
    } catch (err) {
      const existing = err?.error?.details?.run_id || err?.details?.run_id
      if (existing) { pending.value = { runId: existing, startedAt: pending.value.startedAt }; persist(); await refresh() }
      else if (['VALIDATION_ERROR', 'OPERATION_CONFLICT', 'SECURITY_ERROR', 'FORBIDDEN'].includes(err?.error?.code)) {
        pending.value = null
        persist()
      }
      error.value = err?.error?.message || err?.message || 'Submission could not be confirmed. Reconnect or retry this same request; do not start a duplicate run.'
      schedule()
    } finally { submitting.value = false }
  }
  function dismiss() {
    clearTimeout(pollTimer)
    pending.value = null
    run.value = null
    error.value = ''
    trackingUnavailable.value = false
    persist()
    const url = new URL(window.location.href)
    url.searchParams.delete('run')
    window.history.replaceState({}, '', url)
  }
  async function start(request) {
    if (active.value || submitting.value) return
    run.value = null
    pending.value = { runId: crypto.randomUUID(), request: JSON.parse(JSON.stringify(request)), startedAt: new Date().toISOString() }
    persist()
    await submit()
  }
  async function resume(runId) {
    try { pending.value = JSON.parse(sessionStorage.getItem(storageKey()) || 'null') } catch { pending.value = null }
    if (runId && /^[a-zA-Z0-9-]+$/.test(runId)) pending.value = { runId, startedAt: new Date().toISOString() }
    if (pending.value?.runId) await refresh()
  }
  const clock = setInterval(() => { now.value = Date.now() }, 1000)
  onBeforeUnmount(() => { disposed = true; clearTimeout(pollTimer); clearInterval(clock) })
  return { run, error, trackingUnavailable, dismiss, active, submitting, pending, elapsed, start, refresh, resume, retry: submit }
}
