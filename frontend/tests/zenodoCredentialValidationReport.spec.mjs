import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ZenodoCredentialValidationReport from '../src/components/account/ZenodoCredentialValidationReport.vue'

function buildCredential(validationStatus, summary) {
  return {
    validation_status: validationStatus,
    validation_mode: 'live_write_cleanup',
    recommended_scopes: ['deposit:write', 'deposit:actions'],
    validation_report: {
      mode: 'live_write_cleanup',
      aggregate_status: validationStatus,
      summary,
      recommended_scopes: ['deposit:write', 'deposit:actions'],
      capabilities: {
        authentication: { status: validationStatus === 'valid' ? 'verified' : validationStatus, message: 'Authentication check message.' },
        deposit_read: { status: validationStatus === 'valid' ? 'verified' : validationStatus, message: 'Deposit read message.' },
        draft_create: { status: validationStatus === 'valid' ? 'verified' : validationStatus, message: 'Draft create message.' },
        draft_cleanup: { status: validationStatus === 'valid' ? 'verified' : validationStatus, message: 'Draft cleanup message.' },
      },
    },
  }
}

describe('ZenodoCredentialValidationReport', () => {
  it('renders live write validation summaries and capability rows', () => {
    const wrapper = mount(ZenodoCredentialValidationReport, {
      props: {
        credential: buildCredential(
          'valid',
          'Zenodo accepted the token for read access, temporary draft creation, and automatic draft cleanup.',
        ),
      },
    })

    expect(wrapper.text()).toContain('Live write cleanup')
    expect(wrapper.text()).toContain('Valid')
    expect(wrapper.text()).toContain('Test draft create')
    expect(wrapper.text()).toContain('Test draft cleanup')
    expect(wrapper.text()).toContain('deposit:write, deposit:actions')
  })

  it('renders invalid summaries distinctly', () => {
    const wrapper = mount(ZenodoCredentialValidationReport, {
      props: {
        credential: buildCredential('invalid', 'Zenodo rejected deposit API access for this token.'),
      },
    })

    expect(wrapper.text()).toContain('invalid')
    expect(wrapper.text()).toContain('Zenodo rejected deposit API access for this token.')
  })

  it('renders unreachable summaries distinctly', () => {
    const wrapper = mount(ZenodoCredentialValidationReport, {
      props: {
        credential: buildCredential('unreachable', 'Zenodo rate-limited token validation. Retry later.'),
      },
    })

    expect(wrapper.text()).toContain('unreachable')
    expect(wrapper.text()).toContain('Retry later')
  })
})
