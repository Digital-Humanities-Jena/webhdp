import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  authService: {
    getZenodoCredential: vi.fn(),
    saveZenodoCredential: vi.fn(),
    validateZenodoCredential: vi.fn(),
    deleteZenodoCredential: vi.fn(),
    listZenodoCredentials: vi.fn(),
    createZenodoCredential: vi.fn(),
    validateZenodoCredentialById: vi.fn(),
    deleteZenodoCredentialById: vi.fn(),
    shareZenodoCredential: vi.fn(),
    setActiveZenodoCredential: vi.fn(),
    acceptZenodoCredentialShare: vi.fn(),
    declineZenodoCredentialShare: vi.fn(),
    getRecoveryCodes: vi.fn(),
    regenerateRecoveryCodes: vi.fn(),
  },
  institutionService: {
    suggestInstitutions: vi.fn(),
    configureAffiliation: vi.fn(),
  },
  authStore: {
    user: {
      id: 7,
      email: 'owner@example.com',
      role: 'user',
      created_at: '2026-03-30T10:00:00Z',
    },
    institutions: [],
    memberships: [],
    updateCurrentUser: vi.fn(),
    updatePassword: vi.fn(),
    setUser: vi.fn((nextUser) => {
      mocked.authStore.user = nextUser
      mocked.authStore.institutions = nextUser?.institutions || []
      mocked.authStore.memberships = nextUser?.memberships || []
    }),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/services/auth.service', () => ({ default: mocked.authService }))
vi.mock('@/services/institution.service', () => ({ default: mocked.institutionService }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocked.authStore }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))

import AccountConfigurationView from '../src/views/account/AccountConfigurationView.vue'

const liveCredential = {
  id: 42,
  name: 'Research Sandbox',
  environment: 'sandbox',
  source: 'owned',
  active: true,
  masked_preview: 'sand...7890',
  validation_status: 'valid',
  validation_mode: 'live_write_cleanup',
  recommended_scopes: ['deposit:write', 'deposit:actions'],
  validation_report: {
    mode: 'live_write_cleanup',
    aggregate_status: 'valid',
    summary: 'Zenodo accepted the sandbox token for read access, test draft creation, and cleanup.',
    capabilities: {
      authentication: { status: 'verified', message: 'Zenodo accepted the token for the sandbox environment.' },
      deposit_read: { status: 'verified', message: 'The deposit API list probe succeeded.' },
      draft_create: { status: 'verified', message: 'Zenodo allowed WebHDP to create a temporary validation draft.' },
      draft_cleanup: { status: 'verified', message: 'WebHDP automatically deleted the temporary validation draft.' },
    },
  },
}

describe('AccountConfigurationView credentials', () => {
  beforeEach(() => {
    Object.values(mocked.authService).forEach((fn) => fn.mockReset())
    Object.values(mocked.institutionService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.authStore.updateCurrentUser.mockReset()
    mocked.authStore.updatePassword.mockReset()
    mocked.authStore.setUser.mockClear()
    mocked.authStore.user = {
      id: 7,
      email: 'owner@example.com',
      role: 'user',
      created_at: '2026-03-30T10:00:00Z',
    }
    mocked.authStore.institutions = []
    mocked.authStore.memberships = []
    mocked.authService.getRecoveryCodes.mockResolvedValue({
      data: {
        recovery_codes: {
          configured: true,
          remaining_count: 2,
          used_count: 1,
          total_count: 3,
        },
      },
    })
  })

  it('renders the live credential matrix for personal credentials', async () => {
    mocked.authService.listZenodoCredentials.mockResolvedValue({
      data: {
        credentials: [liveCredential],
        active: { sandbox: liveCredential, production: null },
        incoming_shares: [],
        outgoing_shares: [],
      },
    })

    const wrapper = mount(AccountConfigurationView, {
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :href="to"><slot /></a>',
          },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Live write cleanup')
    expect(wrapper.text()).toContain('Profile slug')
    expect(wrapper.text()).toContain('Internal')
    expect(wrapper.text()).toContain('Zenodo Keys')
    expect(wrapper.text()).toContain('Research Sandbox')
    expect(wrapper.text()).toContain('Active')
    expect(wrapper.text()).toContain('Test draft create')
    expect(wrapper.text()).toContain('WebHDP automatically deleted the temporary validation draft.')
    expect(wrapper.text()).toContain('deposit:write, deposit:actions')
    expect(wrapper.text()).not.toContain('sandbox-secret-token')

    expect(wrapper.get('a[aria-label="Open Zenodo API key documentation"]').attributes('href')).toBe('/docs/zenodo-api-keys')
    expect(wrapper.get('a[aria-label="Open documentation for secure Zenodo API key storage"]').attributes('href')).toBe('/docs/security-and-credentials')
    expect(wrapper.get('a[aria-label="Open documentation for active Zenodo keys"]').attributes('href')).toBe('/docs/zenodo-api-keys')
    expect(wrapper.get('a[aria-label="Open documentation for secure Zenodo key sharing"]').attributes('href')).toBe('/docs/security-and-credentials')
    expect(wrapper.get('a[aria-label="Open security and credentials documentation"]').attributes('href')).toBe('/docs/security-and-credentials')
    expect(wrapper.findAll('a[aria-label="Open password security documentation"]')).toHaveLength(3)
    expect(wrapper.get('a[aria-label="Open recovery code documentation"]').attributes('href')).toBe('/docs/security-and-credentials')
  })

  it('renders pending shares and keeps shared token cleartext hidden', async () => {
    mocked.authService.listZenodoCredentials.mockResolvedValue({
      data: {
        credentials: [],
        active: { sandbox: null, production: null },
        incoming_shares: [
          {
            id: 12,
            status: 'pending',
            shared_by: { email: 'owner@example.com' },
            credential: {
              id: 77,
              name: 'Shared Production',
              environment: 'production',
              masked_preview: 'prod...1234',
            },
          },
        ],
        outgoing_shares: [],
      },
    })
    mocked.authService.acceptZenodoCredentialShare.mockResolvedValue({ data: { share: { id: 12, status: 'accepted' } } })

    const wrapper = mount(AccountConfigurationView, {
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :href="to"><slot /></a>',
          },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Pending shared keys')
    expect(wrapper.text()).toContain('Shared Production')
    expect(wrapper.text()).toContain('owner@example.com')
    expect(wrapper.text()).not.toContain('production-secret-token')

    const acceptButton = wrapper.findAll('button').find((button) => button.text() === 'Accept')
    await acceptButton.trigger('click')
    expect(mocked.authService.acceptZenodoCredentialShare).toHaveBeenCalledWith(12)
  })

  it('renders recovery code status and displays regenerated codes once', async () => {
    mocked.authService.listZenodoCredentials.mockResolvedValue({
      data: {
        credentials: [],
        active: { sandbox: null, production: null },
        incoming_shares: [],
        outgoing_shares: [],
      },
    })
    mocked.authService.regenerateRecoveryCodes.mockResolvedValue({
      data: {
        recovery_codes: {
          configured: true,
          remaining_count: 3,
          used_count: 0,
          total_count: 3,
        },
        codes: ['ABCD-EFGH-IJKL', 'MNOP-QRST-UVWX', '1234-5678-9ABC'],
      },
    })

    const wrapper = mount(AccountConfigurationView, {
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :href="to"><slot /></a>',
          },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Recovery codes')
    expect(wrapper.text()).toContain('2 recovery codes available')

    await wrapper.get('[data-testid="recovery-code-password"]').setValue('password123')
    await wrapper.get('[data-testid="recovery-code-form"]').trigger('submit.prevent')
    await flushPromises()

    expect(mocked.authService.regenerateRecoveryCodes).toHaveBeenCalledWith('password123')
    expect(wrapper.get('[data-testid="generated-recovery-codes"]').text()).toContain('ABCD-EFGH-IJKL')
    expect(wrapper.get('[data-testid="clear-generated-recovery-codes"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="recovery-codes-saved"]').setValue(true)
    await wrapper.get('[data-testid="clear-generated-recovery-codes"]').trigger('click')
    expect(wrapper.find('[data-testid="generated-recovery-codes"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('3 recovery codes available')
  })

  it('suggests existing institutions and warns before creating a similar one', async () => {
    vi.useFakeTimers()
    mocked.authService.listZenodoCredentials.mockResolvedValue({
      data: { credentials: [], active: { sandbox: null, production: null }, incoming_shares: [], outgoing_shares: [] },
    })
    mocked.institutionService.suggestInstitutions.mockResolvedValue({
      data: { institutions: [{ id: 3, name: 'Museum Network', similarity: 0.97 }] },
    })
    mocked.institutionService.configureAffiliation
      .mockRejectedValueOnce({
        error: {
          code: 'SIMILAR_INSTITUTION_EXISTS',
          details: { similar: [{ id: 3, name: 'Museum Network', similarity: 0.94 }] },
          message: 'A very similar institution already exists.',
        },
      })
      .mockResolvedValueOnce({
        data: {
          user: { id: 7, email: 'owner@example.com', affiliation: 'Museum Network', default_institution_id: 3 },
          institution: { id: 3, name: 'Museum Network' },
          institutions: [{ id: 3, name: 'Museum Network', role: 'reader' }],
          memberships: [],
          created: false,
        },
      })

    const wrapper = mount(AccountConfigurationView, {
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :href="to"><slot /></a>',
          },
        },
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="institution-affiliation-input"]').setValue('Museum Net')
    vi.advanceTimersByTime(250)
    await flushPromises()
    expect(mocked.institutionService.suggestInstitutions).toHaveBeenCalledWith('Museum Net', { limit: 8 })
    expect(wrapper.get('[data-testid="institution-suggestions"]').text()).toContain('Museum Network')

    await wrapper.get('[data-testid="institution-affiliation-input"]').setValue('Museum Networks')
    await wrapper.get('[data-testid="institution-create-button"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="similar-institution-warning"]').text()).toContain('Museum Network')

    await wrapper.findAll('button').find((button) => button.text() === 'Use Museum Network').trigger('click')
    await flushPromises()
    expect(mocked.institutionService.configureAffiliation).toHaveBeenLastCalledWith({ institution_id: 3 })
    expect(mocked.authStore.setUser).toHaveBeenCalled()
    vi.useRealTimers()
  })
})
