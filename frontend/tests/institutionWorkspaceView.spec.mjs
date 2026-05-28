import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  institutionService: {
    getInstitution: vi.fn(),
    listAuditEvents: vi.fn(),
    createInstitution: vi.fn(),
    updateInstitution: vi.fn(),
    createMembership: vi.fn(),
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
}))

vi.mock('@/services/institution.service', () => ({ default: mocked.institutionService }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocked.authStore }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

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
})
