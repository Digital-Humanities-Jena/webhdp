import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'
import LandingView from '../src/views/public/LandingView.vue'

describe('LandingView', () => {
  it('renders the public WebHDP landing page with primary access links', () => {
    const wrapper = mount(LandingView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    expect(wrapper.get('h1').text()).toContain('WebHDP turns heritage datasets into publishable records.')
    expect(wrapper.text()).toContain('Prepare, validate, and publish heritage-science datasets')
    expect(wrapper.text()).toContain('Upload and scan complex datasets')
    expect(wrapper.text()).toContain('Validate publication outputs')
    expect(wrapper.text()).toContain('Publish and retrieve Zenodo records')
    expect(wrapper.text()).toContain('Preserve process provenance')

    expect(wrapper.findAll('a[href="/register"]').length).toBeGreaterThan(0)
    expect(wrapper.findAll('a[href="/login"]').length).toBeGreaterThan(0)
    expect(wrapper.findAll('a[href="/docs"]').length).toBeGreaterThan(0)
    expect(wrapper.findAll('a[href="/credits"]').length).toBeGreaterThan(0)
    expect(wrapper.text()).toContain('People and project context')
    expect(wrapper.get('img').attributes('src')).toBeTruthy()
  })
})
