import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  router: {
    push: vi.fn(),
    replace: vi.fn(),
  },
  route: {
    params: {},
  },
  docsService: {
    listDocuments: vi.fn(),
    getDocument: vi.fn(),
  },
  authStore: {
    isAuthenticated: false,
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
    useRouter: () => mocked.router,
  }
})

vi.mock('@/services/docs.service', () => ({
  default: mocked.docsService,
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => mocked.authStore,
}))

import DocumentationHubView from '../src/views/docs/DocumentationHubView.vue'

describe('DocumentationHubView', () => {
  beforeEach(() => {
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.docsService).forEach((fn) => fn.mockReset())
    mocked.route.params = {}
    mocked.authStore.isAuthenticated = false
  })

  it('loads the documentation index, opens the landing guide, and supports search', async () => {
    mocked.docsService.listDocuments.mockResolvedValue({
      data: {
        documents: [
          {
            id: 'operations',
            title: 'Operations Guide',
            description: 'Operational runbook',
            category: 'operations',
            audience: 'operator',
            path: 'guides/operations_and_setup_guide.md',
            sort_order: 40,
          },
          {
            id: 'user-guide',
            title: 'End-to-End User Guide',
            description: 'Primary user landing page',
            category: 'start-here',
            audience: 'beginner',
            path: 'guides/end_to_end_user_guide.md',
            sort_order: 2,
          },
        ],
      },
    })
    mocked.docsService.getDocument.mockResolvedValue({
      data: {
        document: {
          id: 'user-guide',
          title: 'End-to-End User Guide',
          description: 'Primary user landing page',
          category: 'start-here',
          audience: 'beginner',
          path: 'guides/end_to_end_user_guide.md',
          content: '# Getting Started\n\nWelcome to WebHDP.',
        },
      },
    })

    const wrapper = mount(DocumentationHubView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    expect(mocked.router.replace).toHaveBeenCalledWith({
      name: 'DocumentationDoc',
      params: { docId: 'user-guide' },
    })
    expect(wrapper.text()).toContain('End-to-End User Guide')
    expect(wrapper.text()).toContain('Sign in')

    await wrapper.get('#docs-search').setValue('operations')
    expect(wrapper.text()).toContain('Operations Guide')
    expect(wrapper.text()).not.toContain('No documents match your filters.')
  })

  it('surfaces developer onboarding documents in search results', async () => {
    mocked.docsService.listDocuments.mockResolvedValue({
      data: {
        documents: [
          {
            id: 'developer-onboarding',
            title: 'Developer Onboarding',
            description: 'First-hour setup and contribution tracks',
            category: 'development',
            audience: 'developer',
            path: 'development/onboarding.md',
          },
          {
            id: 'devcontainer',
            title: 'Devcontainer Setup',
            description: 'Developer ready VS Code environment',
            category: 'development',
            audience: 'developer',
            path: 'development/devcontainer.md',
          },
          {
            id: 'first-pr-walkthrough',
            title: 'First PR Walkthrough',
            description: 'Developer first contribution path',
            category: 'development',
            audience: 'developer',
            path: 'development/first_pr_walkthrough.md',
          },
          {
            id: 'developer-troubleshooting',
            title: 'Developer Troubleshooting Decision Tree',
            description: 'Developer failure-mode guide',
            category: 'development',
            audience: 'developer',
            path: 'development/troubleshooting_decision_tree.md',
          },
          {
            id: 'contributor-architecture-map',
            title: 'Contributor Architecture Map',
            description: 'Developer ownership map',
            category: 'development',
            audience: 'developer',
            path: 'development/architecture_map.md',
          },
          {
            id: 'developer-glossary',
            title: 'Developer Glossary',
            description: 'Developer vocabulary',
            category: 'development',
            audience: 'developer',
            path: 'development/developer_glossary.md',
          },
          {
            id: 'pr-scope-examples',
            title: 'PR Size And Scope Examples',
            description: 'Developer reviewable PR examples',
            category: 'development',
            audience: 'developer',
            path: 'development/pr_scope_examples.md',
          },
          {
            id: 'known-development-warnings',
            title: 'Known Development Warnings',
            description: 'Developer warning triage',
            category: 'development',
            audience: 'developer',
            path: 'development/known_warnings.md',
          },
          {
            id: 'developer-examples',
            title: 'Developer Examples Cookbook',
            description: 'Copyable implementation patterns',
            category: 'development',
            audience: 'developer',
            path: 'development/examples.md',
          },
          {
            id: 'golden-workflow',
            title: 'Golden Sample Workflow',
            description: 'Developer fixture-backed setup confidence check',
            category: 'development',
            audience: 'developer',
            path: 'development/golden_workflow.md',
          },
        ],
      },
    })
    mocked.docsService.getDocument.mockResolvedValue({
      data: {
        document: {
          id: 'developer-onboarding',
          title: 'Developer Onboarding',
          description: 'First-hour setup and contribution tracks',
          category: 'development',
          audience: 'developer',
          path: 'development/onboarding.md',
          content: '# Developer Onboarding\n\nStart here.',
        },
      },
    })

    const wrapper = mount(DocumentationHubView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    await wrapper.get('#docs-search').setValue('developer')

    expect(wrapper.text()).toContain('Developer Onboarding')
    expect(wrapper.text()).toContain('Devcontainer Setup')
    expect(wrapper.text()).toContain('First PR Walkthrough')
    expect(wrapper.text()).toContain('Developer Troubleshooting Decision Tree')
    expect(wrapper.text()).toContain('Contributor Architecture Map')
    expect(wrapper.text()).toContain('Developer Glossary')
    expect(wrapper.text()).toContain('PR Size And Scope Examples')
    expect(wrapper.text()).toContain('Known Development Warnings')
    expect(wrapper.text()).toContain('Developer Examples Cookbook')
    expect(wrapper.text()).toContain('Golden Sample Workflow')
    expect(wrapper.text()).toContain('Developers')
  })

  it('filters by audience and category using stable taxonomy labels', async () => {
    mocked.docsService.listDocuments.mockResolvedValue({
      data: {
        documents: [
          {
            id: 'user-guide',
            title: 'End-to-End User Guide',
            description: 'Primary user landing page',
            category: 'start-here',
            audience: 'beginner',
            path: 'guides/end_to_end_user_guide.md',
            sort_order: 2,
          },
          {
            id: 'zenodo-api-keys',
            title: 'Zenodo API Keys',
            description: 'Create and secure Zenodo keys',
            category: 'account-security',
            audience: 'user',
            path: 'guides/zenodo_api_keys.md',
            sort_order: 10,
          },
          {
            id: 'api-reference',
            title: 'WebHDP API Reference',
            description: 'Endpoint reference',
            category: 'reference',
            audience: 'developer',
            path: 'api/webhdp_api_reference.md',
            sort_order: 72,
          },
        ],
      },
    })
    mocked.docsService.getDocument.mockResolvedValue({
      data: {
        document: {
          id: 'user-guide',
          title: 'End-to-End User Guide',
          description: 'Primary user landing page',
          category: 'start-here',
          audience: 'beginner',
          path: 'guides/end_to_end_user_guide.md',
          content: '# Getting Started\n\nWelcome.',
        },
      },
    })

    const wrapper = mount(DocumentationHubView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    await wrapper.get('[data-testid="docs-audience-user"]').trigger('click')
    expect(wrapper.get('[data-testid="docs-audience-user"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.text()).toContain('Zenodo API Keys')
    expect(wrapper.text()).not.toContain('WebHDP API Reference')

    await wrapper.get('[data-testid="docs-category-account-security"]').trigger('click')
    expect(wrapper.get('[data-testid="docs-category-account-security"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.text()).toContain('Zenodo API Keys')
    expect(wrapper.get('aside').text()).not.toContain('End-to-End User Guide')
  })

  it('routes internal markdown documentation links through the docs hub', async () => {
    mocked.docsService.listDocuments.mockResolvedValue({
      data: {
        documents: [
          {
            id: 'zenodo-api-keys',
            title: 'Zenodo API Keys',
            description: 'Create and secure Zenodo keys',
            category: 'account-security',
            audience: 'user',
            path: 'guides/zenodo_api_keys.md',
          },
          {
            id: 'security-and-credentials',
            title: 'Security and Credentials',
            description: 'Credential safety',
            category: 'account-security',
            audience: 'all',
            path: 'guides/security_and_credentials.md',
          },
        ],
      },
    })
    mocked.docsService.getDocument.mockImplementation(async (docId) => ({
      data: {
        document: {
          id: docId,
          title: docId === 'zenodo-api-keys' ? 'Zenodo API Keys' : 'Security and Credentials',
          description: 'Credential safety',
          category: 'account-security',
          audience: 'user',
          path: docId === 'zenodo-api-keys' ? 'guides/zenodo_api_keys.md' : 'guides/security_and_credentials.md',
          content: docId === 'zenodo-api-keys'
            ? '# Zenodo API Keys\n\nRead [Security and Credentials](security_and_credentials.md).'
            : '# Security and Credentials\n\nSafe storage.',
        },
      },
    }))

    const wrapper = mount(DocumentationHubView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    const link = wrapper.get('.doc-markdown a[href="/docs/security-and-credentials"]')
    await link.trigger('click')

    expect(mocked.router.push).toHaveBeenCalledWith({
      name: 'DocumentationDoc',
      params: { docId: 'security-and-credentials' },
      hash: '',
    })
    expect(mocked.docsService.getDocument).toHaveBeenCalledWith('security-and-credentials')
  })

  it('renders workflow guide links as docs hub hyperlinks', async () => {
    mocked.route.params = { docId: 'workflows' }
    mocked.docsService.listDocuments.mockResolvedValue({
      data: {
        documents: [
          {
            id: 'workflows',
            title: 'WebHDP Workflow Guide',
            description: 'Task-based workflow index',
            category: 'workflows',
            audience: 'all',
            path: 'guides/workflows.md',
          },
          {
            id: 'user-guide',
            title: 'End-to-End User Guide',
            description: 'Primary user landing page',
            category: 'start-here',
            audience: 'beginner',
            path: 'guides/end_to_end_user_guide.md',
          },
          {
            id: 'zenodo-account-retrieval',
            title: 'Zenodo Account Deep Retrieval',
            description: 'Retrieve account inventory',
            category: 'workflows',
            audience: 'user',
            path: 'guides/zenodo_account_retrieval.md',
          },
        ],
      },
    })
    mocked.docsService.getDocument.mockResolvedValue({
      data: {
        document: {
          id: 'workflows',
          title: 'WebHDP Workflow Guide',
          description: 'Task-based workflow index',
          category: 'workflows',
          audience: 'all',
          path: 'guides/workflows.md',
          content: '# WebHDP Workflow Guide\n\nUse [End-to-End User Guide](end_to_end_user_guide.md) and [Zenodo Account Deep Retrieval](zenodo_account_retrieval.md).',
        },
      },
    })

    const wrapper = mount(DocumentationHubView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    expect(wrapper.get('.doc-markdown a[href="/docs/user-guide"]').text()).toBe('End-to-End User Guide')
    expect(wrapper.get('.doc-markdown a[href="/docs/zenodo-account-retrieval"]').text()).toBe('Zenodo Account Deep Retrieval')
  })

  it('adds stable heading anchors and preserves hash navigation for internal docs links', async () => {
    const scrollIntoView = vi.fn()
    const originalScrollIntoView = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = scrollIntoView
    const host = document.createElement('div')
    document.body.appendChild(host)
    mocked.docsService.listDocuments.mockResolvedValue({
      data: {
        documents: [
          {
            id: 'zenodo-api-keys',
            title: 'Zenodo API Keys',
            description: 'Create and secure Zenodo keys',
            category: 'account-security',
            audience: 'user',
            path: 'guides/zenodo_api_keys.md',
          },
          {
            id: 'security-and-credentials',
            title: 'Security and Credentials',
            description: 'Credential safety',
            category: 'account-security',
            audience: 'all',
            path: 'guides/security_and_credentials.md',
          },
        ],
      },
    })
    mocked.docsService.getDocument.mockImplementation(async (docId) => ({
      data: {
        document: {
          id: docId,
          title: docId === 'zenodo-api-keys' ? 'Zenodo API Keys' : 'Security and Credentials',
          description: 'Credential safety',
          category: 'account-security',
          audience: 'user',
          path: docId === 'zenodo-api-keys' ? 'guides/zenodo_api_keys.md' : 'guides/security_and_credentials.md',
          content: docId === 'zenodo-api-keys'
            ? '# Zenodo API Keys\n\nRead [Validation](security_and_credentials.md#validation-results).'
            : '# Security and Credentials\n\n## Validation Results\n\nSafe validation.',
        },
      },
    }))

    try {
      const wrapper = mount(DocumentationHubView, {
        attachTo: host,
        global: {
          stubs: {
            RouterLink: RouterLinkStub,
          },
        },
      })
      await flushPromises()

      const link = wrapper.get('.doc-markdown a[href="/docs/security-and-credentials#validation-results"]')
      await link.trigger('click')
      await flushPromises()
      await new Promise(resolve => requestAnimationFrame(resolve))
      await new Promise(resolve => requestAnimationFrame(resolve))

      expect(mocked.router.push).toHaveBeenCalledWith({
        name: 'DocumentationDoc',
        params: { docId: 'security-and-credentials' },
        hash: '#validation-results',
      })
      expect(wrapper.get('#validation-results').text()).toBe('Validation Results')
      expect(scrollIntoView).toHaveBeenCalledWith({ block: 'start' })
    } finally {
      Element.prototype.scrollIntoView = originalScrollIntoView
      host.remove()
    }
  })
})
