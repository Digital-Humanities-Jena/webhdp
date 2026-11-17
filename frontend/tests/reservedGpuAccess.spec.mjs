import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  listSessions: vi.fn(),
  listReservations: vi.fn(),
  claimReservation: vi.fn(),
  releaseAllocation: vi.fn(),
}))

vi.mock('@/services/file.service', () => ({ default: { listSessions: mocks.listSessions } }))
vi.mock('@/services/hpcLink.service', () => ({ default: mocks }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 } }) }))

import ReservedGpuAccess from '../src/components/hpc/ReservedGpuAccess.vue'

const wrapperInstances = []

function mountPanel(props) {
  const wrapper = mount(ReservedGpuAccess, { props, global: { stubs: { RouterLink: true } } })
  wrapperInstances.push(wrapper)
  return wrapper
}

function button(wrapper, text) {
  return wrapper.findAll('button').find(candidate => candidate.text() === text)
}

const reservation = {
  reservation_id: 'reserved-a100', label: 'Conference demo', status: 'available', can_claim: true,
  node_name: 'gpu017', partition: 'gpu', gpu_type: 'a100', gpu_count: 1, cpus: 8, memory_mb: 65536,
}

function response(...reservations) {
  return { data: { reservations } }
}

describe('ReservedGpuAccess', () => {
  beforeEach(() => {
    Object.values(mocks).forEach(mock => mock.mockReset())
    mocks.listSessions.mockResolvedValue({ data: { sessions: [
      { id: 71, name: 'Demo photos', owner_user_id: 7 },
      { id: 72, name: 'Shared photos', owner_user_id: 8 },
    ] } })
    mocks.listReservations.mockResolvedValue(response())
  })

  afterEach(() => {
    wrapperInstances.splice(0).forEach(wrapper => wrapper.unmount())
  })

  it('binds the reservation to a selected uploaded session and releases only its WebHDP claim', async () => {
    const allocation = { allocation_id: 'claim-71', reservation_id: reservation.reservation_id, session_id: 71, status: 'running' }
    const available = { ...reservation, expires_at: new Date(Date.now() + 3600000).toISOString() }
    mocks.listReservations
      .mockResolvedValueOnce(response(available))
      .mockResolvedValueOnce(response({ ...available, status: 'in_use', can_claim: false, allocation }))
      .mockResolvedValueOnce(response(available))
    mocks.claimReservation.mockResolvedValue({ data: { allocation } })
    mocks.releaseAllocation.mockResolvedValue({ data: {} })

    const wrapper = mountPanel({ selectSession: true })
    await flushPromises()
    expect(wrapper.text()).toContain('1 A100 · 8 CPUs · 64 GiB RAM')
    expect(wrapper.text()).not.toContain('Shared photos')
    expect(button(wrapper, 'Use reserved GPU').element.disabled).toBe(true)
    await wrapper.get('[data-testid="reserved-gpu-session"]').setValue('71')
    await button(wrapper, 'Use reserved GPU').trigger('click')
    await flushPromises()

    expect(mocks.claimReservation).toHaveBeenCalledWith('reserved-a100', { purpose: 'workflow', session_id: 71 })
    expect(wrapper.text()).toContain('Ready for this session')
    expect(wrapper.emitted('claimed')).toEqual([[allocation]])

    await button(wrapper, 'Release access').trigger('click')
    await flushPromises()
    expect(mocks.releaseAllocation).toHaveBeenCalledOnce()
    expect(mocks.releaseAllocation).toHaveBeenCalledWith('claim-71')
    expect(wrapper.text()).toContain('The Slurm reservation keeps its scheduled end time.')
    expect(button(wrapper, 'Use reserved GPU')).toBeDefined()
  })

  it('offers an idempotent connection retry without showing a pending claim as ready', async () => {
    const allocation = { allocation_id: 'claim-71', reservation_id: reservation.reservation_id, session_id: 71, status: 'allocating', last_error: 'Gateway confirmation is pending.' }
    const inUse = { ...reservation, status: 'in_use', can_claim: false, allocation }
    const running = { ...allocation, status: 'running', last_error: null }
    mocks.listReservations
      .mockResolvedValueOnce(response(inUse))
      .mockResolvedValueOnce(response({ ...inUse, allocation: running }))
    mocks.claimReservation.mockResolvedValue({ data: { allocation: running } })

    const wrapper = mountPanel({ sessionId: 71 })
    await flushPromises()
    expect(wrapper.text()).toContain('Gateway confirmation is pending.')
    expect(wrapper.text()).not.toContain('Ready for this session')
    await button(wrapper, 'Retry connection').trigger('click')
    await flushPromises()

    expect(mocks.claimReservation).toHaveBeenCalledWith(reservation.reservation_id, { purpose: 'workflow', session_id: 71 })
    expect(wrapper.text()).toContain('Ready for this session')
  })

  it('removes a claim action after another session wins and displays the server conflict', async () => {
    mocks.listReservations
      .mockResolvedValueOnce(response(reservation))
      .mockResolvedValueOnce(response({ ...reservation, status: 'in_use', can_claim: false }))
    mocks.claimReservation.mockRejectedValue({ error: { message: 'GPU reservation is already in use.' } })

    const wrapper = mountPanel({ sessionId: '71', purpose: 'playground' })
    await flushPromises()
    await button(wrapper, 'Use reserved GPU').trigger('click')
    await flushPromises()

    expect(mocks.listReservations).toHaveBeenCalledWith('playground')
    expect(mocks.claimReservation).toHaveBeenCalledWith('reserved-a100', { purpose: 'playground', session_id: 71 })
    expect(wrapper.get('[role="alert"]').text()).toContain('already in use')
    expect(button(wrapper, 'Use reserved GPU')).toBeUndefined()
    expect(button(wrapper, 'Release access')).toBeUndefined()
  })

  it('does not expose actions for an expired reservation or an account with no reservations', async () => {
    mocks.listReservations.mockResolvedValueOnce(response({
      ...reservation, expires_at: new Date(Date.now() - 5000).toISOString(),
    }))
    const granted = mountPanel({ sessionId: 71 })
    await flushPromises()
    expect(granted.text()).toContain('Expired')
    expect(button(granted, 'Use reserved GPU')).toBeUndefined()

    const unlisted = mountPanel({ sessionId: 71 })
    await flushPromises()
    expect(unlisted.find('[data-testid="reserved-gpu-access"]').exists()).toBe(false)
    expect(mocks.claimReservation).not.toHaveBeenCalled()
  })
})
