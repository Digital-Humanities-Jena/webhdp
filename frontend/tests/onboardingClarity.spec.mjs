import { describe, expect, it } from 'vitest'
import { mountWithApp } from './helpers/app.mjs'
import { activateTestPinia } from './helpers/pinia.mjs'
import { useAuthStore } from '../src/stores/auth'
import OnboardingView from '../src/views/onboarding/OnboardingView.vue'

describe('Onboarding readiness', () => {
  it.each([
    ['pending', false, 'Awaiting approval'],
    ['rejected', false, 'Not approved'],
    ['approved', true, 'Access enabled'],
  ])('describes %s requests without claiming they are ready to render', async (status, hasAccess, label) => {
    const pinia = activateTestPinia()
    useAuthStore().user = { hpc: { has_access: hasAccess, latest_request: { status } } }
    const { wrapper } = await mountWithApp(OnboardingView, { pinia })
    const hpc = wrapper.findAll('article').find(card => card.text().includes('HPC resources'))
    expect(hpc.text()).toContain(label)
    expect(hpc.text()).not.toContain('Done')
    expect(wrapper.text()).toContain('Continue to upload')
    wrapper.unmount()
  })
})
