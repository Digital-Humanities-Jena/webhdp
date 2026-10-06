import { webcrypto } from 'node:crypto'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readinessStream } from '../src/utils/readinessStream'
import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('@/services/api', () => ({ apiV2: { get: mocked.get } }))
import DerivativeReview from '../src/components/workflow/DerivativeReview.vue'
import SubmissionOutcomes from '../src/components/workflow/SubmissionOutcomes.vue'

describe('readiness streaming', () => {
  it('processes complete lines once and waits for the final result', () => {
    const progress = vi.fn()
    const reader = readinessStream(progress)
    const first = '{"type":"progress","checked":1,"total":2}\n'
    expect(reader.consume(first + '{"type":"res')).toBeNull()
    expect(reader.consume(first)).toBeNull()
    expect(progress).toHaveBeenCalledTimes(1)
    expect(reader.consume(first + '{"type":"result","report":{"ready":true}}\n', true)).toEqual({ data: { ready: true } })
  })
  it('fails closed on interrupted, corrupt or failed streams', () => {
    expect(() => readinessStream().consume('{"type":"progress","checked":0,"total":1}\n', true)).toThrow('before its result')
    expect(() => readinessStream().consume('invalid\n', true)).toThrow()
    expect(() => readinessStream().consume('{"type":"result","report":{}}\n{"type":"error","message":"Check failed"}\n', true)).toThrow('Check failed')
  })
  it('accepts the ordinary JSON API envelope', () => {
    const response = { data: { ready: true, blockers: [] } }
    expect(readinessStream().consume(JSON.stringify(response, null, 2), true)).toEqual(response)
    expect(readinessStream().consume(response, true)).toBe(response)
  })
})

describe('record outcomes', () => {
  const outcomes = { summary: { completed: 1, needs_attention: 1, drafts: 1, published: 0 }, can_recover: true, recovery_route: '/workflow/submit?recoverRunId=run', records: [
    { record_id: 1, filename: 'model.glb', status: 'needs_attention', publication_status: 'draft', issue: 'Conversion failed', steps: [{ id: 'prepare', name: 'Prepare source', status: 'completed', reused: true }], warnings: [], record_route: '/records/1', next_action: { label: 'Review failed work', route: '/workflow/submit?recoverRunId=run' } },
  ] }
  it('opens failed results and explains reuse and draft publication', () => {
    const wrapper = mount(SubmissionOutcomes, { props: { outcomes }, global: { stubs: { RouterLink: RouterLinkStub } } })
    expect(wrapper.find('details').attributes()).toHaveProperty('open')
    expect(wrapper.text()).toContain('verified output reused')
    expect(wrapper.text()).toContain('before publishing a draft')
    expect(wrapper.text()).toContain('Conversion failed')
  })
  it('shows record guidance without editing actions to viewers', () => {
    const wrapper = mount(SubmissionOutcomes, { props: { outcomes, canEdit: false }, global: { stubs: { RouterLink: RouterLinkStub } } })
    expect(wrapper.text()).not.toContain('Review and continue failed work')
    expect(wrapper.get('a').attributes('href')).toBe('/records/1')
  })
})

describe('geometric detail review', () => {
  const checksum = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
  const blob = { size: 3, arrayBuffer: async () => new TextEncoder().encode('abc').buffer }
  const detail = { step_run_id: 1, models: ['source', 'high', 'medium', 'low'].map(level => ({ level, label: level, triangles: 1, bytes: 3, sha256: checksum, size_change_percent: 0, filename: level + '.glb' })) }
  const open = () => mount(DerivativeReview, { props: { sessionId: 1, recordId: 2 }, global: { stubs: { PlaygroundModelViewer: true } } })
  beforeEach(() => {
    mocked.get.mockReset()
    vi.stubGlobal('crypto', webcrypto)
    URL.createObjectURL = vi.fn(() => 'blob:verified')
    URL.revokeObjectURL = vi.fn()
  })
  it('adds no panel when the record has no geometric derivatives', async () => {
    mocked.get.mockResolvedValue({ data: { sets: [] } })
    const wrapper = open()
    await flushPromises()
    expect(wrapper.find('details').exists()).toBe(false)
    wrapper.unmount()
  })
  it('verifies transferred bytes and releases both comparisons when the level changes', async () => {
    mocked.get.mockResolvedValueOnce({ data: { sets: [detail] } }).mockResolvedValue(blob)
    const wrapper = open()
    await flushPromises()
    await wrapper.find('button').trigger('click')
    await vi.waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(2))
    expect(wrapper.text()).toContain('match their recorded SHA-256')
    await wrapper.get('select').setValue('low')
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('playground-model-viewer-stub')).toHaveLength(0)
    wrapper.unmount()
  })
  it('blocks mismatched transfers and ignores reports from an earlier record', async () => {
    let resolve
    mocked.get.mockReturnValueOnce(new Promise(done => { resolve = done })).mockResolvedValueOnce({ data: { sets: [] } })
    const wrapper = open()
    await wrapper.setProps({ recordId: 3 })
    await flushPromises()
    resolve({ data: { sets: [detail] } })
    await flushPromises()
    expect(wrapper.find('details').exists()).toBe(false)
    mocked.get.mockResolvedValueOnce({ data: { sets: [detail] } }).mockResolvedValue({ ...blob, size: 4 })
    await wrapper.setProps({ recordId: 4 })
    await flushPromises()
    await wrapper.find('button').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('does not match the report'))
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('explains unavailable checksum verification without downloading unverified models', async () => {
    mocked.get.mockResolvedValueOnce({ data: { sets: [detail] } })
    vi.stubGlobal('crypto', {})
    const wrapper = open()
    await flushPromises()
    await wrapper.find('button').trigger('click')
    expect(wrapper.text()).toContain('HTTPS or localhost')
    expect(mocked.get).toHaveBeenCalledTimes(1)
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
