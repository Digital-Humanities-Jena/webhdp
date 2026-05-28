import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  authStore: {
    user: {
      id: 4,
      email: 'new@example.com',
      role: 'user',
      full_name: '',
      affiliation: '',
      onboarding_required: true,
      zenodo_credentials_configured: false,
      hpc: { has_access: false, latest_request: null },
    },
    updateOnboarding: vi.fn(),
  },
  router: { push: vi.fn() },
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocked.authStore }))
vi.mock('vue-router', () => ({ useRouter: () => mocked.router }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

import OnboardingView from '../src/views/onboarding/OnboardingView.vue'

describe('OnboardingView', () => {
  beforeEach(() => {
    mocked.authStore.updateOnboarding.mockReset()
    mocked.router.push.mockReset()
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.authStore.updateOnboarding.mockResolvedValue({ data: { user: { onboarding_required: false } } })
  })

  it('renders setup checklist and can skip onboarding', async () => {
    const wrapper = mount(OnboardingView, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
        },
      },
    })

    expect(wrapper.text()).toContain('Account setup')
    expect(wrapper.text()).toContain('Zenodo key')
    expect(wrapper.text()).toContain('HPC resources')

    await wrapper.findAll('button').find((button) => button.text() === 'Skip for now').trigger('click')
    await flushPromises()

    expect(mocked.authStore.updateOnboarding).toHaveBeenCalledWith('skip')
    expect(mocked.router.push).toHaveBeenCalledWith('/workflow/upload')
  })
})
