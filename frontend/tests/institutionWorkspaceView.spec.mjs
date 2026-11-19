import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  institutionService: {
    listInstitutions: vi.fn(),
    getInstitution: vi.fn(),
    listAuditEvents: vi.fn(),
    createInstitution: vi.fn(),
    updateInstitution: vi.fn(),
    listInvitations: vi.fn(),
    sendInvitation: vi.fn(),
    revokeInvitation: vi.fn(),
    listWorkspaceRequests: vi.fn(),
    updateMembership: vi.fn(),
    deleteMembership: vi.fn(),
    createCommunity: vi.fn(),
    updateCommunity: vi.fn(),
    deleteCommunity: vi.fn(),
    saveZenodoCredential: vi.fn(),
    validateZenodoCredential: vi.fn(),
    deleteZenodoCredential: vi.fn(),
  },
  authStore: {
    user: {
      id: 9,
      role: 'user',
      default_institution_id: 3,
    },
    institutions: [
      { id: 3, name: 'Museum Network', slug: 'museum-network', role: 'manager' },
    ],
    fetchCurrentUser: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
  route: { query: {} },
  router: { replace: vi.fn() },
}))

vi.mock('@/services/institution.service', () => ({ default: mocked.institutionService }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocked.authStore }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))
vi.mock('vue-router', async importOriginal => ({
  ...await importOriginal(),
  useRoute: () => mocked.route,
  useRouter: () => mocked.router,
}))

import InstitutionWorkspaceView from '../src/views/account/InstitutionWorkspaceView.vue'

const invalidCredential = {
  masked_preview: 'prod...1234',
  validation_status: 'invalid',
  validation_mode: 'live_write_cleanup',
  recommended_scopes: ['deposit:write', 'deposit:actions'],
  validation_report: {
    mode: 'live_write_cleanup',
    aggregate_status: 'invalid',
    summary: 'Zenodo accepted the read probe but rejected test draft creation. This usually means missing deposit:write.',
    capabilities: {
      authentication: { status: 'verified', message: 'Zenodo accepted the token for the production environment.' },
      deposit_read: { status: 'verified', message: 'The deposit API list probe succeeded.' },
      draft_create: { status: 'invalid', message: 'Zenodo rejected test draft creation for this token.' },
      draft_cleanup: { status: 'unverified', message: 'No test draft was created, so cleanup was not needed.' },
    },
  },
}

describe('InstitutionWorkspaceView credentials', () => {
  beforeEach(() => {
    Object.values(mocked.institutionService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.authStore.fetchCurrentUser.mockReset()
    mocked.authStore.user = { id: 9, role: 'user', default_institution_id: 3 }
    mocked.authStore.institutions = [{ id: 3, name: 'Museum Network', role: 'manager' }]
    mocked.route.query = {}
    mocked.institutionService.listInvitations.mockResolvedValue({ data: { invitations: [] } })
    mocked.institutionService.listWorkspaceRequests.mockResolvedValue({ data: { requests: [] } })
  })

  it('renders manager-visible institution live credential details', async () => {
    mocked.authStore.fetchCurrentUser.mockResolvedValue(undefined)
    mocked.institutionService.getInstitution.mockResolvedValue({
      data: {
        institution: {
          id: 3,
          name: 'Museum Network',
          slug: 'museum-network',
          description: '',
          member_count: 4,
          memberships: [],
          communities: [],
          community_policy: {
            primary_submission_community: null,
            moderation_default_communities: [],
            default_communities: [],
          },
          zenodo_credentials: {
            sandbox: invalidCredential,
            production: null,
          },
        },
      },
    })
    mocked.institutionService.listAuditEvents.mockResolvedValue({
      data: {
        audit_events: [],
        pagination: { page: 1, per_page: 10, total: 0, pages: 1 },
      },
    })

    const wrapper = mount(InstitutionWorkspaceView)
    await flushPromises()

    expect(wrapper.text()).toContain('Live write cleanup')
    expect(wrapper.text()).toContain('rejected test draft creation')
    expect(wrapper.text()).toContain('Test draft create')
    expect(wrapper.text()).toContain('invalid')
  })

  it('lets site admins select a workspace where they are not members', async () => {
    mocked.authStore.user = { id: 9, role: 'admin' }
    mocked.route.query = { workspace: '4' }
    mocked.institutionService.listInstitutions.mockResolvedValue({ data: { institutions: [{ id: 4, name: 'Library' }] } })
    mocked.institutionService.getInstitution.mockResolvedValue({ data: { institution: { id: 4, name: 'Library' } } })
    mocked.institutionService.listAuditEvents.mockResolvedValue({ data: { audit_events: [] } })

    const wrapper = mount(InstitutionWorkspaceView)
    await flushPromises()

    expect(mocked.institutionService.listInstitutions).toHaveBeenCalledWith({ all: true })
    expect(mocked.institutionService.getInstitution).toHaveBeenCalledWith(4)
    expect(mocked.institutionService.listWorkspaceRequests).toHaveBeenLastCalledWith(expect.objectContaining({ all: true, status: 'pending' }))
    expect(wrapper.text()).toContain('Site administration')
  })

  it('opens a manager’s invitation controls and saves changed directory visibility', async () => {
    mocked.route.query = { workspace: '3', section: 'members' }
    const institution = { id: 3, name: 'Museum Network', profile_visibility: 'private' }
    mocked.institutionService.getInstitution.mockResolvedValue({ data: { institution } })
    mocked.institutionService.listAuditEvents.mockResolvedValue({ data: { audit_events: [] } })
    mocked.institutionService.updateInstitution.mockResolvedValue({
      data: { institution: { ...institution, profile_visibility: 'internal' } },
    })
    const wrapper = mount(InstitutionWorkspaceView, { attachTo: document.body })
    await flushPromises()

    expect(document.activeElement.textContent).toBe('Members')
    expect(wrapper.text()).toContain('Send invitation')
    const visibility = wrapper.get('#workspace-visibility')
    expect(visibility.element.value).toBe('private')
    await visibility.setValue('internal')
    await wrapper.findAll('button').find(button => button.text() === 'Save institution').trigger('click')
    await flushPromises()

    expect(mocked.institutionService.updateInstitution).toHaveBeenCalledWith(3, {
      description: '',
      profile_visibility: 'internal',
    })
    wrapper.unmount()
  })

  it('keeps invitation and directory controls unavailable for a reader', async () => {
    mocked.route.query = { workspace: '3', section: 'members' }
    mocked.authStore.institutions = [{ id: 3, name: 'Museum Network', role: 'reader' }]
    mocked.institutionService.getInstitution.mockResolvedValue({ data: { institution: { id: 3, name: 'Museum Network' } } })
    const wrapper = mount(InstitutionWorkspaceView)
    await flushPromises()

    expect(wrapper.find('#workspace-visibility').exists()).toBe(false)
    expect(wrapper.get('#workspace-description').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('Send invitation')
    wrapper.unmount()
  })
})
