import { computed, onBeforeUnmount, ref } from 'vue'
import pipelineService from '@/services/pipeline.service'
import { isPermanentProgressError, progressRetryDelay } from '@/utils/progressMonitoring'

export function usePersistentPipelineRun(userId, options = {}) {
  const run = ref(null)
  const error = ref('')
  const trackingUnavailable = ref(false)
  const submitting = ref(false)
  const pending = ref(null)
  const now = ref(Date.now())
  let pollTimer
  let disposed = false
  let refreshing = false
  let failures = 0
  let paused = false
  const storageKey = options.storageKey || (() => `pipeline-run:${userId()}`)
  const getRun = options.getRun || pipelineService.getPipelineRun
  const cancelRun = options.cancelRun || pipelineService.cancelPipelineRun
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
    if (active.value && !disposed && !paused && !trackingUnavailable.value) pollTimer = setTimeout(refresh, Math.max(3000, progressRetryDelay(failures)))
  }
  async function refresh() {
    if (!pending.value || refreshing || disposed) return
    refreshing = true
    const runId = pending.value.runId
    try {
      const response = await getRun(runId)
      if (disposed || pending.value?.runId !== runId) return
      run.value = response.data?.run || response.data
      error.value = ''
      failures = 0
      trackingUnavailable.value = false
      if (run.value?.status === 'failed') error.value = run.value.error || 'The run failed. Review its step results before starting a new run.'
    } catch (err) {
      if (disposed || pending.value?.runId !== runId) return
      failures += 1
      trackingUnavailable.value = isPermanentProgressError(err)
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
    const entry = pending.value
    try {
      const response = await (options.execute ? options.execute(request, entry.runId) : pipelineService.executePipelineOnFiles(request.sessionId, request.paths, true, request.identifier, {
        asyncExecution: true, abortOnCriticalError: true, requestId: pending.value.runId,
        expectedVersion: request.version, preflightToken: request.preflightToken,
      }))
      if (disposed || pending.value !== entry) return
      pending.value.runId = response.data.run_id
      if (response.data.run) run.value = response.data.run
      persist()
      await refresh()
    } catch (err) {
      if (disposed || pending.value !== entry) return
      const details = err?.error?.details || err?.details || {}
      const existing = !details.run_kind || details.run_kind === (options.runKind || 'pipeline') ? details.run_id : null
      if (existing) { pending.value = { runId: existing, startedAt: pending.value.startedAt }; persist(); await refresh() }
      else if (['VALIDATION_ERROR', 'OPERATION_CONFLICT', 'PIPELINE_ALREADY_RUNNING', 'SECURITY_ERROR', 'FORBIDDEN', 'RESOURCE_NOT_FOUND', 'NATIVE_PROCESSING_QUOTA'].includes(err?.error?.code)) {
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
    paused = false
    clearTimeout(pollTimer)
    run.value = null
    error.value = ''
    trackingUnavailable.value = false
    try { pending.value = JSON.parse(sessionStorage.getItem(storageKey()) || 'null') } catch { pending.value = null }
    if (runId && /^[a-zA-Z0-9-]+$/.test(runId)) {
      if (pending.value?.runId !== runId) pending.value = { runId, startedAt: new Date().toISOString() }
      persist()
    }
    if (pending.value?.runId) await refresh()
  }
  function pause() { paused = true; clearTimeout(pollTimer) }
  async function cancel() {
    if (!pending.value?.runId || run.value?.status !== 'pending') return
    const entry = pending.value
    try {
      await cancelRun(entry.runId)
      if (pending.value === entry) await refresh()
    } catch (err) {
      if (pending.value === entry) error.value = err?.error?.message || err?.message || 'Cancellation could not be confirmed. Refresh the run status.'
    }
  }
  const clock = setInterval(() => { now.value = Date.now() }, 1000)
  onBeforeUnmount(() => { disposed = true; clearTimeout(pollTimer); clearInterval(clock) })
  return { run, error, trackingUnavailable, dismiss, active, submitting, pending, elapsed, start, refresh, resume, pause, cancel, retry: submit }
}
