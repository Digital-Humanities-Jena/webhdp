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
  route: { query: {} },
  router: { push: vi.fn(), replace: vi.fn() },
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocked.authStore }))
vi.mock('vue-router', () => ({ useRouter: () => mocked.router, useRoute: () => mocked.route }))

import OnboardingView from '../src/views/onboarding/OnboardingView.vue'

describe('OnboardingView', () => {
  beforeEach(() => {
    localStorage.clear()
    mocked.route.query = {}
    mocked.authStore.user.id = 4
    mocked.authStore.updateOnboarding.mockReset()
    mocked.router.push.mockReset()
    mocked.router.replace.mockReset()
    mocked.authStore.updateOnboarding.mockResolvedValue({ data: { user: { onboarding_required: false } } })
  })

  function mountOnboarding() {
    return mount(OnboardingView, {
      attachTo: document.body,
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
        },
      },
    })
  }

  function press(wrapper, label) {
    return wrapper.findAll('button').find((button) => button.text() === label).trigger('click')
  }

  it('keeps service setup optional and offers the tutorial or a direct route to the dashboard', async () => {
    const wrapper = mountOnboarding()

    expect(wrapper.get('[href="/tutorial/3d"]').text()).toBe('Start 3D tutorial')
    expect(wrapper.get('[href="/account/setup"]').text()).toBe('Open account setup')

    await press(wrapper, 'Skip for now')
    await flushPromises()

    expect(mocked.authStore.updateOnboarding).toHaveBeenCalledWith('skip')
    expect(mocked.router.push).toHaveBeenCalledWith('/dashboard')
    wrapper.unmount()
  })

  it('moves focus with the steps, resumes after reopening, and can be replayed after completion', async () => {
    let wrapper = mountOnboarding()
    await press(wrapper, 'Take the tour')
    expect(document.activeElement).toBe(wrapper.get('#tour-step-title').element)
    expect(wrapper.get('#tour-step-title').text()).toBe('Find your work')
    expect(wrapper.get('[aria-current="step"]').text()).toBe('Find your work')

    await press(wrapper, 'Next')
    expect(wrapper.get('#tour-step-title').text()).toBe('Add files and describe your assets')
    await press(wrapper, 'Next')
    await press(wrapper, 'Back')
    expect(document.activeElement).toBe(wrapper.get('#tour-step-title').element)
    await press(wrapper, 'Pause tour')
    expect(document.activeElement.textContent).toBe('Continue the tour')
    expect(mocked.authStore.updateOnboarding).not.toHaveBeenCalled()
    wrapper.unmount()

    wrapper = mountOnboarding()
    await press(wrapper, 'Continue the tour')
    expect(wrapper.get('#tour-step-title').text()).toBe('Add files and describe your assets')
    await press(wrapper, 'Next')
    await press(wrapper, 'Next')
    await press(wrapper, 'Finish tour')
    await flushPromises()
    expect(mocked.authStore.updateOnboarding).toHaveBeenCalledWith('complete')
    expect(wrapper.get('[role="status"]').text()).toContain('Tour complete')
    expect(document.activeElement).toBe(wrapper.get('h1').element)

    await press(wrapper, 'Replay the tour')
    expect(wrapper.get('#tour-step-title').text()).toBe('Find your work')
    wrapper.unmount()
  })

  it('keeps unfinished steps separate by account and opens a direct tour link', async () => {
    localStorage.setItem('webhdp:intro-tour:v1:4', '3')
    mocked.authStore.user.id = 5
    mocked.route.query = { tour: '1' }
    const wrapper = mountOnboarding()
    await flushPromises()
    expect(wrapper.get('#tour-step-title').text()).toBe('Find your work')
    await press(wrapper, 'Pause tour')
    expect(mocked.router.replace).toHaveBeenCalledWith({ query: { tour: undefined } })
    expect(localStorage.getItem('webhdp:intro-tour:v1:4')).toBe('3')
    wrapper.unmount()
  })
})
