import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  issueService: {
    getRegistry: vi.fn(),
    listIssues: vi.fn(),
    createIssue: vi.fn(),
  },
  router: {
    push: vi.fn(),
  },
  route: {
    name: 'IssuesWorkspace',
    path: '/issues',
    fullPath: '/issues',
    params: {},
    query: {},
    matched: [],
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
  authStore: {
    user: {
      id: 4,
      email: 'reporter@example.com',
      role: 'user',
      groups: [],
      capabilities: [],
    },
  },
}))

vi.mock('@/services/issue.service', () => ({ default: mocked.issueService }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocked.authStore }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => mocked.router,
    useRoute: () => mocked.route,
  }
})

import IssuesWorkspaceView from '../src/views/issues/IssuesWorkspaceView.vue'
import IssueReportView from '../src/views/issues/IssueReportView.vue'

function buildRegistryPayload() {
  return {
    data: {
      pages: [
        {
          page_key: 'session_provenance_report',
          label: 'Session Provenance Report',
          route_name: 'SessionProvenanceReport',
          route_templates: ['/sessions/:sessionId/provenance-report'],
          allow_actual_route: true,
        },
      ],
      statuses: [
        { value: 'new', label: 'New' },
        { value: 'triaged', label: 'Triaged' },
      ],
      issue_types: [
        { value: 'general', label: 'General bug' },
        { value: 'data', label: 'Incorrect data' },
      ],
      reporter_impacts: [
        { value: 'medium', label: 'Medium' },
        { value: 'high', label: 'High' },
      ],
      app_version: {
        version: 'test-build',
        timestamp: '2026-03-31T12:00:00Z',
      },
    },
  }
}

describe('Issues views', () => {
  beforeEach(() => {
    Object.values(mocked.issueService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.router.push.mockReset()
    window.sessionStorage.clear()
  })

  it('renders the shared triage queue when queue access is available', async () => {
    mocked.issueService.getRegistry.mockResolvedValue(buildRegistryPayload())
    mocked.issueService.listIssues.mockResolvedValue({
      data: {
        issues: [
          {
            id: 12,
            title: 'Provenance panel does not load',
            public_description: 'Charts never appear.',
            page_label: 'Session Provenance Report',
            route_path: '/sessions/17/provenance-report',
            status: 'new',
            reporter_impact: 'high',
            reporter: { email: 'reporter@example.com' },
            updated_at: '2026-03-31T10:00:00Z',
          },
        ],
        permissions: {
          can_view_issue_queue: true,
        },
      },
    })

    const wrapper = mount(IssuesWorkspaceView, {
      global: {
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Shared Triage Queue')
    expect(wrapper.text()).toContain('Provenance panel does not load')
    expect(wrapper.text()).toContain('Session Provenance Report')
  })

  it('prefills the current page context and switches to technical intake mode', async () => {
    window.sessionStorage.setItem('webhdp_issue_report_context', JSON.stringify({
      route_name: 'SessionProvenanceReport',
      route_path: '/sessions/17/provenance-report',
      current_url: 'https://example.test/sessions/17/provenance-report',
      route_context: {
        path: '/sessions/17/provenance-report',
        full_path: '/sessions/17/provenance-report',
        params: { sessionId: '17' },
        query: {},
      },
      related_entity_ids: { session_id: 17 },
      environment_context: {},
      user_context: { reporter_role: 'user', reporter_groups: [] },
      capture_context: { source: 'test' },
    }))
    mocked.issueService.getRegistry.mockResolvedValue(buildRegistryPayload())

    const wrapper = mount(IssueReportView, {
      global: {
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Session Provenance Report')
    expect(wrapper.text()).toContain('/sessions/17/provenance-report')
    expect(wrapper.text()).not.toContain('Technical detail')

    const technicalButton = wrapper.findAll('button').find((button) => button.text().includes('Technical'))
    await technicalButton.trigger('click')

    expect(wrapper.text()).toContain('Technical detail')
    expect(wrapper.text()).toContain('Captured context preview')
  })

  it('captures the current route when reporting from the workspace', async () => {
    mocked.issueService.getRegistry.mockResolvedValue(buildRegistryPayload())
    mocked.issueService.listIssues.mockResolvedValue({
      data: {
        issues: [],
        permissions: {
          can_view_issue_queue: false,
        },
      },
    })

    const wrapper = mount(IssuesWorkspaceView, {
      global: {
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })
    await flushPromises()

    const reportButton = wrapper.findAll('button').find((button) => button.text().includes('Report Issue'))
    await reportButton.trigger('click')

    expect(mocked.router.push).toHaveBeenCalledWith('/issues/report')
    const savedContext = JSON.parse(window.sessionStorage.getItem('webhdp_issue_report_context'))
    expect(savedContext.route_name).toBe('IssuesWorkspace')
    expect(savedContext.route_path).toBe('/issues')
  })
})
