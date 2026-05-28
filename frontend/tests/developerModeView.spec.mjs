import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { mountWithApp } from './helpers/app.mjs'

const mocked = vi.hoisted(() => ({
  developerService: {
    getStatus: vi.fn(),
  },
}))

vi.mock('@/services/developer.service', () => ({
  default: mocked.developerService,
}))

import DeveloperModeView from '../src/views/developer/DeveloperModeView.vue'

describe('DeveloperModeView', () => {
  beforeEach(() => {
    mocked.developerService.getStatus.mockReset()
  })

  it('renders developer diagnostics and onboarding links', async () => {
    mocked.developerService.getStatus.mockResolvedValue({
      data: {
        version: { version: '0.1.5', timestamp: '2026-02-20T15:08:29' },
        runtime: { flask_env: 'development', storage_mode: 'local' },
        api_contract: { exists: true, regenerate_command: 'make api-contract' },
        feature_flags: {
          enable_renderer: true,
          enable_usdz_conversion: false,
        },
        user: {
          role: 'user',
          capabilities: ['developer_access'],
        },
        commands: [
          { label: 'Run environment doctor', command: 'make doctor' },
          { label: 'Run docs checks', command: 'make docs-check' },
          { label: 'Regenerate API contract', command: 'make api-contract' },
        ],
        docs: [
          {
            label: 'Developer Onboarding',
            path: '/docs/developer-onboarding',
            file: 'docs/development/onboarding.md',
            exists: true,
          },
          {
            label: 'Devcontainer Setup',
            path: '/docs/devcontainer',
            file: 'docs/development/devcontainer.md',
            exists: true,
          },
          {
            label: 'First PR Walkthrough',
            path: '/docs/first-pr-walkthrough',
            file: 'docs/development/first_pr_walkthrough.md',
            exists: true,
          },
          {
            label: 'Troubleshooting Decision Tree',
            path: '/docs/developer-troubleshooting',
            file: 'docs/development/troubleshooting_decision_tree.md',
            exists: true,
          },
          {
            label: 'Contributor Architecture Map',
            path: '/docs/contributor-architecture-map',
            file: 'docs/development/architecture_map.md',
            exists: true,
          },
          {
            label: 'Developer Glossary',
            path: '/docs/developer-glossary',
            file: 'docs/development/developer_glossary.md',
            exists: true,
          },
          {
            label: 'PR Size And Scope Examples',
            path: '/docs/pr-scope-examples',
            file: 'docs/development/pr_scope_examples.md',
            exists: true,
          },
          {
            label: 'Known Development Warnings',
            path: '/docs/known-development-warnings',
            file: 'docs/development/known_warnings.md',
            exists: true,
          },
          {
            label: 'Golden Sample Workflow',
            path: '/docs/golden-workflow',
            file: 'docs/development/golden_workflow.md',
            exists: true,
          },
        ],
      },
    })

    const { wrapper } = await mountWithApp(DeveloperModeView, {
      route: '/developer',
      routes: [{ path: '/developer', component: DeveloperModeView }],
    })
    await flushPromises()

    expect(mocked.developerService.getStatus).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Onboarding Diagnostics')
    expect(wrapper.text()).toContain('0.1.5')
    expect(wrapper.text()).toContain('make doctor')
    expect(wrapper.text()).toContain('make docs-check')
    expect(wrapper.text()).toContain('Developer Onboarding')
    expect(wrapper.text()).toContain('Devcontainer Setup')
    expect(wrapper.text()).toContain('First PR Walkthrough')
    expect(wrapper.text()).toContain('Troubleshooting Decision Tree')
    expect(wrapper.text()).toContain('Contributor Architecture Map')
    expect(wrapper.text()).toContain('Developer Glossary')
    expect(wrapper.text()).toContain('PR Size And Scope Examples')
    expect(wrapper.text()).toContain('Known Development Warnings')
    expect(wrapper.text()).toContain('Golden Sample Workflow')
    expect(wrapper.text()).toContain('developer_access')
  })
})
