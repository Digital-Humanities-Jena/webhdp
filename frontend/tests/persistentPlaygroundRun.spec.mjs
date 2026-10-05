import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
const service = vi.hoisted(() => ({ executePlayground: vi.fn(), getPlaygroundRun: vi.fn(), cancelPlaygroundRun: vi.fn() }))
vi.mock('@/services/pipeline.service', () => ({ default: service }))
import { usePersistentPlaygroundRun } from '../src/composables/usePersistentPlaygroundRun'
let controller, wrapper
function setup(component = 'test-component') {
  wrapper = mount(defineComponent({ setup() { controller = usePersistentPlaygroundRun(() => 7, () => component); return {} }, template: '<div />' }))
}
beforeEach(() => { vi.useFakeTimers(); vi.resetAllMocks(); setup() })
afterEach(() => wrapper.unmount())
const request = () => ({ session_id: 42, component_key: 'test-component', profile_id: 'local', inputs: { files: ['model.glb'] }, parameters: {} })

it('resumes a queued component after remount without re-submitting', async () => {
  service.executePlayground.mockImplementation(async payload => ({ data: { playground_run: { run_id: payload.request_id, status: 'pending' } } }))
  service.getPlaygroundRun.mockResolvedValue({ data: { playground_run: { status: 'pending' } } })
  await controller.start(request())
  const id = controller.pending.value.runId
  wrapper.unmount(); setup()
  await controller.resume()
  expect(controller.pending.value.runId).toBe(id)
  service.getPlaygroundRun.mockResolvedValue({ data: { playground_run: { status: 'completed', result: { success: true } } } })
  await vi.advanceTimersByTimeAsync(3000)
  expect(controller.active.value).toBe(false)
  expect(service.executePlayground).toHaveBeenCalledTimes(1)
  const calls = service.getPlaygroundRun.mock.calls.length
  await vi.advanceTimersByTimeAsync(10000)
  expect(service.getPlaygroundRun).toHaveBeenCalledTimes(calls)
})

it('retries an unconfirmed submission with the same immutable request', async () => {
  service.executePlayground.mockRejectedValueOnce(new Error('Acknowledgement lost'))
  const original = request()
  await controller.start(original)
  const first = service.executePlayground.mock.calls[0][0]
  original.inputs.files = ['edited.glb']
  service.executePlayground.mockResolvedValue({ data: { playground_run: { run_id: first.request_id, status: 'pending' } } })
  service.getPlaygroundRun.mockResolvedValue({ data: { playground_run: { status: 'pending' } } })
  await controller.retry()
  expect(service.executePlayground.mock.calls[1][0]).toEqual(first)
  expect(first.async_execution).toBe(true)
})

it('pauses polling when the dialog closes and reconnects on reopen', async () => {
  service.getPlaygroundRun.mockResolvedValue({ data: { playground_run: { status: 'running' } } })
  await controller.resume('existing')
  controller.pause()
  await vi.advanceTimersByTimeAsync(10000)
  expect(service.getPlaygroundRun).toHaveBeenCalledTimes(1)
  await controller.resume()
  expect(service.getPlaygroundRun).toHaveBeenCalledTimes(2)
})

it('reports terminal failures and safely cancels only a pending run', async () => {
  service.getPlaygroundRun.mockResolvedValueOnce({ data: { playground_run: { status: 'pending' } } })
  service.getPlaygroundRun.mockResolvedValue({ data: { playground_run: { status: 'failed', error: 'Cancelled before processing' } } })
  await controller.resume('queued')
  await controller.cancel()
  expect(service.cancelPlaygroundRun).toHaveBeenCalledWith('queued')
  expect(controller.error.value).toBe('Cancelled before processing')
  expect(controller.active.value).toBe(false)
})

it('keeps unrelated component tracking separate', async () => {
  service.getPlaygroundRun.mockResolvedValue({ data: { playground_run: { status: 'running' } } })
  await controller.resume('first')
  wrapper.unmount(); setup('other-component')
  await controller.resume()
  expect(controller.pending.value).toBe(null)
})
