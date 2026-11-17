import { flushPromises, mount } from '@vue/test-utils'
import { Blob as NodeBlob } from 'node:buffer'
import { createHash, webcrypto } from 'node:crypto'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ service: { listJobs: vi.fn(), getJob: vi.fn(), cancelJob: vi.fn(), downloadJobArtifact: vi.fn() }, route: { params: {} } }))
vi.mock('@/services/webhdpLink.service', () => ({ default: mocks.service }))
vi.mock('vue-router', () => ({ useRoute: () => mocks.route }))
import LinkedProcessingView from '../src/views/link/LinkedProcessingView.vue'
const job = { id: 'run-123', pipeline_id: 'piano-midi', pipeline_version: '1.0.0', client_id: 'piano', client_name: 'Piano Studio', status: 'queued', progress: { completed: 0, total: 2 }, steps: [], artifacts: [], created_at: '2026-11-06T12:00:00Z' }
const button = (wrapper, text) => wrapper.findAll('button').find(item => item.text() === text)
const mountView = () => mount(LinkedProcessingView, { global: { stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } } } })
beforeEach(() => {
  Object.values(mocks.service).forEach(fn => fn.mockReset()); mocks.route.params = {}
  mocks.service.listJobs.mockResolvedValue({ jobs: [job, { ...job, id: 'run-model', client_id: 'models', client_name: 'Model Studio', status: 'succeeded' }] })
  mocks.service.getJob.mockResolvedValue(job)
})
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('groups owned jobs by application and filters active processing', async () => {
  const wrapper = mountView(); await flushPromises()
  expect(wrapper.text()).toContain('Piano Studio'); expect(wrapper.text()).toContain('Model Studio')
  expect(wrapper.find('a[href="/link/jobs/run-123"]').exists()).toBe(true)
  await wrapper.get('select').setValue('active')
  expect(wrapper.text()).toContain('Piano Studio'); expect(wrapper.text()).not.toContain('Model Studio')
  wrapper.unmount()
})
it('shows resource waiting in the overview without changing its running status or exposing resource details', async () => {
  mocks.service.listJobs.mockResolvedValue({ jobs: [{ ...job, status: 'running', progress: { completed: 0, total: 2, phase: 'waiting_for_resources', node: 'private-node', allocation_id: 'private-allocation' } }] })
  const wrapper = mountView(); await flushPromises()
  expect(wrapper.text()).toContain('Waiting for resources')
  expect(wrapper.find('.badge').text()).toBe('Running')
  expect(wrapper.text()).not.toContain('private-node'); expect(wrapper.text()).not.toContain('private-allocation')
  await wrapper.get('select').setValue('active')
  expect(wrapper.text()).toContain('Waiting for resources')
  wrapper.unmount()
})
it('distinguishes resource wait, processing and finalization while terminal failure remains authoritative', async () => {
  vi.useFakeTimers(); mocks.route.params = { runId: 'run-123' }
  const phaseJob = phase => ({ ...job, status: 'running', progress: { completed: 0, total: 2, phase }, started_at: '2026-11-06T12:00:00Z' })
  mocks.service.getJob.mockResolvedValue(phaseJob('waiting_for_resources'))
  const wrapper = mountView(); await flushPromises()
  expect(wrapper.get('[role="status"]').text()).toContain('Waiting for resources')
  expect(wrapper.text()).toContain('Worker accepted'); expect(wrapper.text()).not.toContain('The pipeline is processing your files')
  mocks.service.getJob.mockResolvedValue(phaseJob('processing'))
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(wrapper.get('[role="status"]').text()).toContain('The pipeline is processing your files')
  mocks.service.getJob.mockResolvedValue(phaseJob('finalizing'))
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(wrapper.get('[role="status"]').text()).toContain('Preparing results')
  mocks.service.getJob.mockResolvedValue({ ...phaseJob('completed'), status: 'failed' })
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  expect(wrapper.find('.badge').text()).toBe('Failed')
  wrapper.unmount()
})
it('opens a bookmarkable job and cancels through the user-owned endpoint', async () => {
  mocks.route.params = { runId: 'run-123' }; mocks.service.cancelJob.mockResolvedValue({ ...job, status: 'cancelled', cancel_requested: true })
  const wrapper = mountView(); await flushPromises()
  expect(mocks.service.getJob).toHaveBeenCalledWith('run-123'); expect(wrapper.text()).toContain('bookmark this page')
  await button(wrapper, 'Cancel job').trigger('click'); await flushPromises()
  expect(mocks.service.cancelJob).toHaveBeenCalledWith('run-123'); expect(wrapper.text()).toContain('Cancelled'); expect(button(wrapper, 'Cancel job')).toBeUndefined()
  wrapper.unmount()
})
it('refreshes active progress and stops polling when complete', async () => {
  vi.useFakeTimers(); mocks.route.params = { runId: 'run-123' }
  const wrapper = mountView(); await flushPromises()
  mocks.service.getJob.mockResolvedValue({ ...job, status: 'succeeded', progress: { completed: 2, total: 2 }, steps: [{ id: 'step-1', name: 'Digitize', status: 'completed' }] })
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('100'); expect(wrapper.text()).toContain('Digitize')
  await vi.advanceTimersByTimeAsync(10000); expect(mocks.service.getJob).toHaveBeenCalledTimes(2)
  wrapper.unmount()
})
it('downloads an output with user authentication rather than a public token URL', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('crypto', webcrypto)
  mocks.route.params = { runId: 'run-123' }
  const artifact = { id: 'artifact-1', name: 'roll.mid', size: 4, sha256: createHash('sha256').update('midi').digest('hex'), media_type: 'audio/midi' }
  mocks.service.getJob.mockResolvedValue({ ...job, status: 'succeeded', artifacts: [artifact] }); mocks.service.downloadJobArtifact.mockResolvedValue(new NodeBlob(['midi']))
  const create = vi.fn().mockReturnValue('blob:private-output'), revoke = vi.fn()
  vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const wrapper = mountView(); await flushPromises(); await button(wrapper, 'Download').trigger('click'); await flushPromises(); await vi.waitFor(() => expect(click).toHaveBeenCalled())
  expect(mocks.service.downloadJobArtifact).toHaveBeenCalledWith('run-123', 'artifact-1'); expect(create).toHaveBeenCalled(); expect(click).toHaveBeenCalled(); await vi.advanceTimersByTimeAsync(1000); expect(revoke).toHaveBeenCalledWith('blob:private-output'); wrapper.unmount(); vi.unstubAllGlobals()
})
it('shows an ownership rejection without stale job data', async () => {
  mocks.route.params = { runId: 'someone-elses-run' }; mocks.service.getJob.mockRejectedValue({ detail: 'The job is unavailable to your account.' })
  const wrapper = mountView(); await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('unavailable to your account'); expect(button(wrapper, 'Cancel job')).toBeUndefined(); wrapper.unmount()
})

it('rejects an output with changed content before creating a browser download', async () => {
  vi.stubGlobal('crypto', webcrypto)
  mocks.route.params = { runId: 'run-123' }
  const artifact = { id: 'artifact-corrupt', name: 'roll.mid', size: 4, sha256: createHash('sha256').update('midi').digest('hex'), media_type: 'audio/midi' }
  mocks.service.getJob.mockResolvedValue({ ...job, status: 'succeeded', artifacts: [artifact] })
  mocks.service.downloadJobArtifact.mockResolvedValue(new NodeBlob(['evil']))
  const create = vi.fn()
  vi.stubGlobal('URL', class extends URL { static createObjectURL = create })
  const wrapper = mountView(); await flushPromises(); await button(wrapper, 'Download').trigger('click'); await flushPromises()
  await vi.waitFor(() => expect(wrapper.get('[role="alert"]').text()).toContain('checksum does not match'))
  expect(create).not.toHaveBeenCalled(); wrapper.unmount()
})
