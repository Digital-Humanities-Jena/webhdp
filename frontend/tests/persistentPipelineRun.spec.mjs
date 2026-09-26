import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest'
const service = vi.hoisted(() => ({ executePipelineOnFiles: vi.fn(), getPipelineRun: vi.fn() }))
vi.mock('@/services/pipeline.service', () => ({ default: service }))
import { usePersistentPipelineRun } from '../src/composables/usePersistentPipelineRun'
let controller, wrapper
function setup() {
  wrapper = mount(defineComponent({ setup() { controller = usePersistentPipelineRun(() => 7); return {} }, template: '<div />' }))
}
beforeEach(() => { sessionStorage.clear(); vi.useFakeTimers(); vi.resetAllMocks(); setup() })
afterEach(() => { wrapper.unmount(); vi.useRealTimers() })
const request = { sessionId: 42, identifier: 'render', version: '1.0.0', paths: ['/tmp/file.glb'], preflightToken: 'signed-check' }
describe('persistent pipeline execution', () => {
  it('reconnects after remount without submitting again and stops polling at completion', async () => {
    service.executePipelineOnFiles.mockResolvedValue({ data: { run_id: 'run-persistent' } })
    service.getPipelineRun.mockResolvedValue({ data: { run: { status: 'running', started_at: new Date().toISOString() } } })
    await controller.start(request)
    expect(controller.active.value).toBe(true)
    wrapper.unmount(); setup()
    await controller.resume()
    expect(service.executePipelineOnFiles).toHaveBeenCalledTimes(1)
    service.getPipelineRun.mockResolvedValue({ data: { run: { status: 'completed' } } })
    await vi.advanceTimersByTimeAsync(3000)
    expect(controller.active.value).toBe(false)
    const calls = service.getPipelineRun.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(service.getPipelineRun).toHaveBeenCalledTimes(calls)
  })
  it('reconnects to an existing session run without retrying unrelated inputs', async () => {
    service.executePipelineOnFiles.mockRejectedValue({ error: { code: 'OPERATION_CONFLICT', details: { run_id: 'existing-run' }, message: 'Session already running' } })
    service.getPipelineRun.mockResolvedValue({ data: { run: { status: 'running' } } })
    await controller.start(request)
    expect(controller.pending.value.runId).toBe('existing-run')
    expect(controller.pending.value.request).toBeUndefined()
    await controller.retry()
    expect(service.executePipelineOnFiles).toHaveBeenCalledTimes(1)
  })
  it('retries an uncertain submission with the same identifier and immutable inputs', async () => {
    service.executePipelineOnFiles.mockRejectedValueOnce(new Error('Connection interrupted'))
    await controller.start(request)
    const firstOptions = service.executePipelineOnFiles.mock.calls[0][4]
    request.paths = ['/tmp/edited.glb']
    service.executePipelineOnFiles.mockResolvedValue({ data: { run_id: firstOptions.requestId } })
    service.getPipelineRun.mockResolvedValue({ data: { run: { status: 'pending' } } })
    await controller.retry()
    expect(service.executePipelineOnFiles.mock.calls[1][4].requestId).toBe(firstOptions.requestId)
    expect(service.executePipelineOnFiles.mock.calls[1][1]).toEqual(['/tmp/file.glb'])
    expect(firstOptions).toMatchObject({ asyncExecution: true, expectedVersion: '1.0.0', preflightToken: 'signed-check' })
  })
})

it('stops automatic polling for a removed run and permits explicit dismissal', async () => {
  service.getPipelineRun.mockRejectedValue({ error: { code: 'RESOURCE_NOT_FOUND', message: 'Run not found' } })
  await controller.resume('missing-run')
  expect(controller.trackingUnavailable.value).toBe(true)
  await vi.advanceTimersByTimeAsync(12000)
  expect(service.getPipelineRun).toHaveBeenCalledTimes(1)
  controller.dismiss()
  expect(controller.active.value).toBe(false)
  expect(controller.pending.value).toBe(null)
})

it('ignores an outstanding status response after tracking is dismissed', async () => {
  let resolve
  service.getPipelineRun.mockImplementation(() => new Promise(r => { resolve = r }))
  const pending = controller.resume('slow-run')
  controller.dismiss()
  resolve({ data: { run: { status: 'running' } } })
  await pending
  expect(controller.run.value).toBe(null)
  expect(controller.active.value).toBe(false)
})
