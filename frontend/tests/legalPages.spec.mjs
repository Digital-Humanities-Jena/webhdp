import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { RouterLinkStub } from './helpers/router.mjs'

import CookiePolicyView from '../src/views/legal/CookiePolicyView.vue'
import ImpressumView from '../src/views/legal/ImpressumView.vue'
import PrivacyPolicyView from '../src/views/legal/PrivacyPolicyView.vue'

const mountLegalView = (component) => mount(component, {
  global: {
    stubs: {
      RouterLink: RouterLinkStub,
    },
  },
})

describe('legal pages', () => {
  it('renders the Impressum with provider, project contact, funding, and alpha status', () => {
    const wrapper = mountLegalView(ImpressumView)

    expect(wrapper.text()).toContain('Example Research Institution')
    expect(wrapper.text()).toContain('its authorized representative')
    expect(wrapper.text()).toContain('configured by the operator')
    expect(wrapper.text()).toContain('WebHDP project team')
    expect(wrapper.text()).toContain('webhdp@3drepo.eu')
    expect(wrapper.text()).toContain('Grant Agreement No. 101173385')
    expect(wrapper.text()).toContain('Grant Agreement No. 101233051')
    expect(wrapper.text()).toContain('WebHDP credits page')
    expect(wrapper.find('a[href="/credits"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('alpha versions')
    expect(wrapper.text()).toContain('full GDPR compliance')
  })

  it('renders the privacy policy with GDPR, DPO, rights, and Zenodo baseline language', () => {
    const wrapper = mountLegalView(PrivacyPolicyView)

    expect(wrapper.text()).toContain('fully GDPR-compliant')
    expect(wrapper.text()).toContain('privacy@example.org')
    expect(wrapper.text()).toContain('competent data protection supervisory authority')
    expect(wrapper.text()).toContain('Zenodo is the baseline external service')
    expect(wrapper.text()).toContain('Dropbox, Google Drive, HPC-Link, SMTP mail services, and the local EDM validator')
    expect(wrapper.text()).toContain('encrypted at rest')
  })

  it('renders the cookies and storage notice with necessary storage details', () => {
    const wrapper = mountLegalView(CookiePolicyView)

    expect(wrapper.text()).toContain('does not set non-essential tracking cookies')
    expect(wrapper.text()).toContain('Authentication tokens in session storage')
    expect(wrapper.text()).toContain('Workflow state in session storage')
    expect(wrapper.text()).toContain('Directory upload recovery state')
    expect(wrapper.text()).toContain('local storage flag')
  })
})
