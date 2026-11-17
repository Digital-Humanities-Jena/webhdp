import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  service: Object.fromEntries(['listClients', 'createClient', 'updateClient', 'listPublications', 'createPublication', 'updatePublication', 'pipelineOptions', 'listTokens', 'issueToken', 'revokeToken', 'listRuns', 'cancelRun', 'authorizationRequest', 'authorize'].map(name => [name, vi.fn()])),
  embedded: false, user: { id: 7, email: 'operator@example.org' }, route: { query: {} }, navigate: vi.fn(),
}))
vi.mock('@/services/webhdpLink.service', () => ({ default: mocks.service }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: mocks.user }) }))
vi.mock('vue-router', () => ({ useRoute: () => mocks.route }))
vi.mock('@/utils/webhdpLink', async () => ({ ...(await vi.importActual('@/utils/webhdpLink')), navigateLinkCallback: mocks.navigate, isEmbeddedLinkWindow: () => mocks.embedded }))
import WebHdpLinkView from '../src/views/admin/WebHdpLinkView.vue'
import LinkAuthorizeView from '../src/views/link/LinkAuthorizeView.vue'
const publication = { id: 'piano-midi', name: 'Piano roll to MIDI', description: 'Reconstruct MIDI from scanned rolls.', pipeline_identifier: 'hmsm', pipeline_version: '1.0.0', enabled: true, input: { min_files: 1, max_files: 4, extensions: ['.png'] }, execution_mode: 'record' }
const client = { id: 'piano-studio', name: 'Piano Studio', enabled: true, pipeline_ids: [publication.id], origins: ['https://piano.example.org'], redirect_uris: ['https://piano.example.org/callback'], max_queued_runs: 20, max_concurrent_runs: 1, max_upload_bytes: 104857600, max_storage_bytes: 1073741824 }
const query = { client_id: client.id, redirect_uri: client.redirect_uris[0], response_type: 'code', code_challenge: 'a'.repeat(43), code_challenge_method: 'S256', state: 'random-state-12345', scope: 'pipelines:read uploads:write runs:write runs:read artifacts:read' }
const button = (wrapper, text) => wrapper.findAll('button').find(item => item.text() === text)
const labelInput = (wrapper, text) => wrapper.findAll('label').find(item => item.text().startsWith(text)).find('input, select, textarea')
beforeEach(() => {
  Object.values(mocks.service).forEach(fn => fn.mockReset()); mocks.navigate.mockReset(); mocks.embedded = false; mocks.route.query = { ...query }
  mocks.service.listPublications.mockResolvedValue({ publications: [publication] }); mocks.service.listClients.mockResolvedValue({ clients: [client] })
  mocks.service.listTokens.mockResolvedValue({ tokens: [{ id: 'token-1', client_id: client.id, user_id: 7, expires_at: '2026-11-07T12:00:00Z', revoked: false }] })
  mocks.service.listRuns.mockResolvedValue({ runs: [{ id: 'run-1234567890', pipeline_id: publication.id, pipeline_version: '1.0.0', status: 'queued', progress: { completed: 0, total: 1 }, created_at: '2026-11-06T12:00:00Z' }] })
  mocks.service.pipelineOptions.mockResolvedValue({ pipelines: [{ identifier: 'hmsm', name: 'HMSM', versions: [{ version: '1.0.0', steps: [{ id: 'digitize', parameters: [{ name: 'tempo', label: 'Tempo', type: 'integer', minimum: 30, maximum: 300, default: 120 }] }] }] }] })
  mocks.service.authorizationRequest.mockResolvedValue({ client, redirect_uri: query.redirect_uri, scope: query.scope, pipelines: [publication], expires_in: 3600 })
})
describe('Link authorization', () => {
  it('rejects framed consent before fetching authorization details', async () => {
    mocks.embedded = true
    const wrapper = mount(LinkAuthorizeView); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('cannot be approved inside another page')
    expect(mocks.service.authorizationRequest).not.toHaveBeenCalled()
    expect(mocks.service.authorize).not.toHaveBeenCalled()
    expect(button(wrapper, 'Allow connection')).toBeUndefined()
    expect(button(wrapper, 'Deny')).toBeUndefined()
    expect(wrapper.get('a[target="_top"]').text()).toBe('Open WebHDP directly')
    expect(wrapper.get('a[target="_top"]').attributes('rel')).toBe('noopener noreferrer')
    wrapper.unmount()
  })
  it('shows verified app and scope information before explicit approval', async () => {
    const wrapper = mount(LinkAuthorizeView); await flushPromises()
    for (const text of ['Piano Studio', 'https://piano.example.org', 'operator@example.org', 'Piano roll to MIDI', 'Download output files']) expect(wrapper.text()).toContain(text)
    expect(mocks.service.authorize).not.toHaveBeenCalled()
    mocks.service.authorize.mockResolvedValue({ redirect_uri: `${query.redirect_uri}?code=one-use&state=random-state-12345` })
    await button(wrapper, 'Allow connection').trigger('click'); await flushPromises()
    expect(mocks.service.authorize).toHaveBeenCalledWith({ ...query, approve: true })
    expect(mocks.navigate).toHaveBeenCalledWith(`${query.redirect_uri}?code=one-use&state=random-state-12345`, query.redirect_uri)
    wrapper.unmount()
  })
  it('returns denial through the server-validated callback', async () => {
    mocks.service.authorize.mockResolvedValue({ redirect_uri: `${query.redirect_uri}?error=access_denied&state=random-state-12345` })
    const wrapper = mount(LinkAuthorizeView); await flushPromises(); await button(wrapper, 'Deny').trigger('click'); await flushPromises()
    expect(mocks.service.authorize).toHaveBeenCalledWith({ ...query, approve: false })
    expect(mocks.navigate).toHaveBeenCalledWith(`${query.redirect_uri}?error=access_denied&state=random-state-12345`, query.redirect_uri)
    wrapper.unmount()
  })
  it('blocks consent when validation fails and shows Problem Details', async () => {
    mocks.service.authorizationRequest.mockRejectedValue({ status: 400, detail: 'This return address is not registered.' })
    const wrapper = mount(LinkAuthorizeView, { global: { stubs: { RouterLink: true } } }); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('not registered'); expect(button(wrapper, 'Allow connection')).toBeUndefined(); expect(mocks.navigate).not.toHaveBeenCalled(); wrapper.unmount()
  })
})
describe('WebHDP-Link administration', () => {
  it('publishes a pinned version with explicit parameter bindings', async () => {
    mocks.service.createPublication.mockResolvedValue({})
    const wrapper = mount(WebHdpLinkView); await flushPromises(); await button(wrapper, 'Publish a pipeline').trigger('click')
    await labelInput(wrapper, 'Public name').setValue('HMSM processing'); await labelInput(wrapper, 'Publication ID').setValue('hmsm-public'); await labelInput(wrapper, 'Native pipeline').setValue('hmsm'); await labelInput(wrapper, 'Allowed extensions').setValue('.PNG, .jpg')
    await wrapper.findAll('label').find(item => item.text().startsWith('Tempo')).get('input[type="checkbox"]').setValue(true)
    await wrapper.get('form').trigger('submit.prevent'); await flushPromises()
    expect(mocks.service.createPublication).toHaveBeenCalledWith(expect.objectContaining({ id: 'hmsm-public', name: 'HMSM processing', pipeline_identifier: 'hmsm', pipeline_version: '1.0.0', execution_mode: 'record', input: { min_files: 1, max_files: 1, extensions: ['.png', '.jpg'] }, parameters: { tempo: { step_id: 'digitize', parameter: 'tempo', type: 'integer', label: 'Tempo', default: 120, minimum: 30, maximum: 300 } } }))
    wrapper.unmount()
  })
  it.each([false, true])('uses central duration and release defaults unless retention is explicit (%s)', async (retain) => {
    mocks.service.createPublication.mockResolvedValue({})
    const wrapper = mount(WebHdpLinkView); await flushPromises(); await button(wrapper, 'Publish a pipeline').trigger('click')
    await labelInput(wrapper, 'Public name').setValue('HPC pipeline'); await labelInput(wrapper, 'Publication ID').setValue('hpc-public'); await labelInput(wrapper, 'Native pipeline').setValue('hmsm'); await labelInput(wrapper, 'Allowed extensions').setValue('.png')
    await labelInput(wrapper, 'Request HPC resources').setValue(true)
    if (retain) {
      await labelInput(wrapper, 'Keep allocation after completion').setValue(true)
      await labelInput(wrapper, 'Duration (hours)').setValue(12)
    }
    await wrapper.get('form').trigger('submit.prevent'); await flushPromises()
    const policy = mocks.service.createPublication.mock.calls[0][0].hpc
    expect(policy).toEqual(retain ? { enabled: true, retain_allocation: true, reuse_retained_allocation: false, walltime_hours: 12, gpu_count: 1 } : { enabled: true, retain_allocation: false, reuse_retained_allocation: false, gpu_count: 1 })
    wrapper.unmount()
  })
  it('requires retention for the optional reuse policy and clears it from the payload when retention is unchecked', async () => {
    mocks.service.createPublication.mockResolvedValue({})
    const wrapper = mount(WebHdpLinkView); await flushPromises(); await button(wrapper, 'Publish a pipeline').trigger('click')
    await labelInput(wrapper, 'Public name').setValue('HPC pipeline'); await labelInput(wrapper, 'Publication ID').setValue('hpc-reuse'); await labelInput(wrapper, 'Native pipeline').setValue('hmsm'); await labelInput(wrapper, 'Allowed extensions').setValue('.png')
    await labelInput(wrapper, 'Request HPC resources').setValue(true)
    await labelInput(wrapper, 'Keep allocation after completion').setValue(true)
    await labelInput(wrapper, 'Reuse a compatible retained allocation').setValue(true)
    await wrapper.get('form').trigger('submit.prevent'); await flushPromises()
    expect(mocks.service.createPublication.mock.calls[0][0].hpc).toMatchObject({ retain_allocation: true, reuse_retained_allocation: true })
    await button(wrapper, 'Publish a pipeline').trigger('click')
    await labelInput(wrapper, 'Keep allocation after completion').setValue(false)
    await wrapper.get('form').trigger('submit.prevent'); await flushPromises()
    expect(mocks.service.createPublication.mock.calls[1][0].hpc).toMatchObject({ retain_allocation: false, reuse_retained_allocation: false })
    wrapper.unmount()
  })
  it('registers exact origins, redirects, permissions and byte limits', async () => {
    mocks.service.createClient.mockResolvedValue({})
    const wrapper = mount(WebHdpLinkView); await flushPromises(); await button(wrapper, 'Register an application').trigger('click')
    await labelInput(wrapper, 'Application name').setValue('Photo Studio'); await labelInput(wrapper, 'Client ID').setValue('photo-studio'); await labelInput(wrapper, 'Browser origins').setValue('https://photos.example.org\nhttps://other.example.org'); await labelInput(wrapper, 'OAuth return addresses').setValue('https://photos.example.org/callback'); await wrapper.find('input[type="checkbox"][value="piano-midi"]').setValue(true)
    await wrapper.get('form').trigger('submit.prevent'); await flushPromises()
    expect(mocks.service.createClient).toHaveBeenCalledWith(expect.objectContaining({ id: 'photo-studio', origins: ['https://photos.example.org', 'https://other.example.org'], redirect_uris: ['https://photos.example.org/callback'], pipeline_ids: ['piano-midi'], max_upload_bytes: 104857600, max_storage_bytes: 1073741824 })); wrapper.unmount()
  })
  it('edits an existing client without changing its identity', async () => {
    mocks.service.updateClient.mockResolvedValue({})
    const wrapper = mount(WebHdpLinkView); await flushPromises(); await button(wrapper, 'Edit').trigger('click')
    expect(labelInput(wrapper, 'Client ID').attributes('readonly')).toBeDefined()
    await labelInput(wrapper, 'Queued jobs').setValue(5)
    await wrapper.get('form').trigger('submit.prevent'); await flushPromises()
    expect(mocks.service.updateClient).toHaveBeenCalledWith('piano-studio', expect.objectContaining({ max_queued_runs: 5 }))
    expect(mocks.service.updateClient.mock.calls[0][1]).not.toHaveProperty('id')
    expect(mocks.service.updateClient.mock.calls[0][1]).not.toHaveProperty('enabled')
    wrapper.unmount()
  })
  it('creates a one-time token and can revoke tokens and cancel queued jobs', async () => {
    mocks.service.issueToken.mockResolvedValue({ access_token: 'one-time-secret' }); mocks.service.revokeToken.mockResolvedValue({}); mocks.service.cancelRun.mockResolvedValue({})
    const wrapper = mount(WebHdpLinkView); await flushPromises(); await button(wrapper, 'Create server token').trigger('click'); await wrapper.get('form').trigger('submit.prevent'); await flushPromises()
    expect(mocks.service.issueToken).toHaveBeenCalledWith('piano-studio', expect.objectContaining({ user_id: 7, expires_in: 3600 })); expect(wrapper.find('textarea[readonly]').element.value).toBe('one-time-secret')
    await button(wrapper, 'I have saved the token').trigger('click'); expect(wrapper.find('textarea[readonly]').exists()).toBe(false)
    await button(wrapper, 'Revoke').trigger('click'); await flushPromises(); expect(mocks.service.revokeToken).toHaveBeenCalledWith('token-1')
    await button(wrapper, 'Cancel job').trigger('click'); await flushPromises(); expect(mocks.service.cancelRun).toHaveBeenCalledWith('run-1234567890'); wrapper.unmount()
  })
  it('renders validation errors beside failed actions', async () => {
    mocks.service.updateClient.mockRejectedValue({ status: 403, detail: 'Only an administrator can change application access.' })
    const wrapper = mount(WebHdpLinkView); await flushPromises(); await button(wrapper, 'Disable access').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Only an administrator'); expect(wrapper.text()).toContain('Piano Studio'); wrapper.unmount()
  })
})
