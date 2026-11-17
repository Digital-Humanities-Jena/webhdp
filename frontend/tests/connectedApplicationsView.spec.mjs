import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ listGrants: vi.fn(), revokeGrant: vi.fn() }))
vi.mock('@/services/webhdpLink.service', () => ({ default: mocks }))
import ConnectedApplicationsView from '../src/views/link/ConnectedApplicationsView.vue'
const grant = { id: 'grant-1', client_id: 'piano', client_name: 'Piano Studio', scope: 'pipelines:read runs:write', expires_at: '2099-01-01T00:00:00Z', revoked: false }
beforeEach(() => { mocks.listGrants.mockReset(); mocks.revokeGrant.mockReset(); mocks.listGrants.mockResolvedValue({ grants: [grant] }) })
it('shows connection permissions and revokes only the selected grant', async () => {
  const wrapper = mount(ConnectedApplicationsView); await flushPromises()
  expect(wrapper.text()).toContain('Piano Studio'); expect(wrapper.text()).toContain('Submit and cancel processing jobs')
  mocks.revokeGrant.mockResolvedValue({}); mocks.listGrants.mockResolvedValue({ grants: [{ ...grant, revoked: true }] })
  await wrapper.findAll('button').find(button => button.text() === 'Disconnect application').trigger('click'); await flushPromises()
  expect(mocks.revokeGrant).toHaveBeenCalledWith('grant-1'); expect(wrapper.text()).toContain('Disconnected')
  expect(wrapper.findAll('button').some(button => button.text() === 'Disconnect application')).toBe(false)
  wrapper.unmount()
})
it('keeps the connection visible when revocation fails', async () => {
  mocks.revokeGrant.mockRejectedValue({ detail: 'This connection could not be revoked.' })
  const wrapper = mount(ConnectedApplicationsView); await flushPromises()
  await wrapper.findAll('button').find(button => button.text() === 'Disconnect application').trigger('click'); await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('could not be revoked'); expect(wrapper.text()).toContain('Active'); wrapper.unmount()
})
