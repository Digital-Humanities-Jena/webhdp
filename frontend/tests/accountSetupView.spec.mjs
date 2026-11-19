import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mountWithApp } from './helpers/app.mjs'
import { activateTestPinia } from './helpers/pinia.mjs'
import authService from '../src/services/auth.service'
import institutionService from '../src/services/institution.service'
import { useAuthStore } from '../src/stores/auth'
import { invitationStorageKey } from '../src/utils/emailAction'
import AccountSetupView from '../src/views/account/AccountSetupView.vue'

vi.mock('@/services/auth.service', () => ({ default: { listZenodoCredentials: vi.fn() } }))
vi.mock('@/services/institution.service', () => ({
  default: { listWorkspaceRequests: vi.fn(), suggestInstitutions: vi.fn() },
}))

const memberships = [
  { id: 5, name: 'City Archive', role: 'reader' },
  { id: 6, name: 'Digital Heritage Lab', role: 'manager' },
]

async function mountSetup(role = 'user', institutions = memberships) {
  const pinia = activateTestPinia()
  useAuthStore().setUser({ id: 4, role, affiliation: 'Heritage Lab', institutions })
  return (await mountWithApp(AccountSetupView, { pinia })).wrapper
}

function linkWithText(wrapper, text) {
  return wrapper.findAll('a').find(link => link.text() === text)
}

describe('Account setup', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    sessionStorage.clear()
    const sandbox = { environment: 'sandbox', validation_status: 'valid' }
    authService.listZenodoCredentials.mockResolvedValue({
      data: { active: { sandbox }, credentials: [sandbox] },
    })
    institutionService.listWorkspaceRequests.mockResolvedValue({ data: { pagination: { total: 1 } } })
  })

  it('shows separate credential states and directs to the existing credential form', async () => {
    const wrapper = await mountSetup()

    const keyCards = wrapper.get('[aria-labelledby="setup-zenodo-heading"]').findAll('article')
    expect(keyCards[0].text()).toContain('Validated')
    expect(keyCards[1].text()).toContain('No key added')
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    expect(linkWithText(wrapper, 'Manage Sandbox key').attributes('href')).toBe('/account/configuration?zenodo=sandbox#zenodo-sandbox')
    expect(linkWithText(wrapper, 'Add Production key').attributes('href')).toBe('/account/configuration?zenodo=production#zenodo-keys')
    expect(wrapper.text()).toContain('1 awaiting approval')
    expect(institutionService.listWorkspaceRequests).toHaveBeenCalledWith({ status: 'pending', per_page: 1 })
    wrapper.unmount()
  })

  it('offers invitation and management links according to membership and the search results', async () => {
    sessionStorage.setItem(invitationStorageKey, 'example-value-for-a-pending-invitation')
    institutionService.suggestInstitutions.mockResolvedValue({
      data: { institutions: [memberships[1], { id: 8, name: 'Regional Museum' }] },
    })
    const wrapper = await mountSetup()

    expect(linkWithText(wrapper, 'Continue an invitation').attributes('href')).toBe('/institution-invitation')
    expect(linkWithText(wrapper, 'Invite to City Archive')).toBeUndefined()
    expect(linkWithText(wrapper, 'Invite to Digital Heritage Lab').attributes('href')).toBe('/account/institutions?workspace=6&section=members')
    expect(linkWithText(wrapper, 'Create a workspace')).toBeUndefined()
    expect(wrapper.get('#setup-workspace-search').element.value).toBe('Heritage Lab')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    const results = wrapper.get('[aria-label="Workspace search results"]')
    const [member, other] = results.findAll('li')
    expect(member.get('a').attributes('href')).toBe('/account/institutions?workspace=6')
    expect(other.text()).toContain('Regional Museum')
    expect(other.text()).toContain('Ask the workspace manager for an invitation')
    expect(other.find('a').exists()).toBe(false)
    expect(institutionService.suggestInstitutions).toHaveBeenCalledWith('Heritage Lab', {}, { suppressGlobalError: true })
    wrapper.unmount()
  })

  it('allows administrators to create workspaces and see the review queue', async () => {
    const wrapper = await mountSetup('admin', [])

    expect(linkWithText(wrapper, 'Create a workspace').attributes('href')).toBe('/account/institutions#create-institution')
    expect(linkWithText(wrapper, 'Review workspace requests').attributes('href')).toBe('/account/institutions#workspace-requests-title')
    expect(linkWithText(wrapper, 'Manage all workspaces').attributes('href')).toBe('/account/institutions')
    expect(institutionService.listWorkspaceRequests).toHaveBeenCalledWith({ status: 'pending', per_page: 1, all: true })
    wrapper.unmount()
  })

  it('offers a retry when checking workspace requests fails', async () => {
    institutionService.listWorkspaceRequests.mockRejectedValueOnce(new Error('Unavailable'))
    const wrapper = await mountSetup()

    expect(wrapper.text()).toContain('Request status unavailable')
    const refresh = wrapper.findAll('button').find(button => button.text() === 'Refresh setup status')
    await refresh.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('1 awaiting approval')
    expect(wrapper.text()).not.toContain('Request status unavailable')
    wrapper.unmount()
  })

  it('discards an unfinished status request from a previous account', async () => {
    const previous = Promise.withResolvers()
    authService.listZenodoCredentials.mockReturnValueOnce(previous.promise)
    const wrapper = await mountSetup()
    useAuthStore().setUser({ id: 12, role: 'user', institutions: [] })
    await flushPromises()

    previous.resolve({ data: { active: { production: { validation_status: 'valid' } } } })
    await flushPromises()

    expect(linkWithText(wrapper, 'Add Production key')).toBeDefined()
    expect(linkWithText(wrapper, 'Manage Production key')).toBeUndefined()
    expect(wrapper.text()).toContain('You have no workspace memberships yet.')
    wrapper.unmount()
  })
})
