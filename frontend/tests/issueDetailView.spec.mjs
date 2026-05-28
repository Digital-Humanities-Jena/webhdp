import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  issueService: {
    getRegistry: vi.fn(),
    getIssue: vi.fn(),
    updateIssue: vi.fn(),
    addComment: vi.fn(),
    refreshCodeReferences: vi.fn(),
  },
  route: {
    params: {
      issueId: '12',
    },
  },
  authStore: {
    user: {
      id: 4,
      email: 'developer@example.com',
      role: 'user',
      groups: ['developer'],
      capabilities: ['developer_access'],
    },
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/services/issue.service', () => ({ default: mocked.issueService }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocked.authStore }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
  }
})

import IssueDetailView from '../src/views/issues/IssueDetailView.vue'

function buildRegistryResponse() {
  return {
    data: {
      pages: [
        {
          page_key: 'workflow_upload',
          label: 'Workflow Upload',
          route_name: 'Upload',
          route_templates: ['/workflow/upload'],
        },
        {
          page_key: 'session_provenance_report',
          label: 'Session Provenance Report',
          route_name: 'SessionProvenanceReport',
          route_templates: ['/sessions/:sessionId/provenance-report'],
        },
      ],
      statuses: [
        { value: 'new', label: 'New' },
        { value: 'triaged', label: 'Triaged' },
      ],
      internal_priorities: [
        { value: 'medium', label: 'Medium' },
        { value: 'high', label: 'High' },
      ],
      issue_types: [
        { value: 'general', label: 'General bug' },
        { value: 'data', label: 'Incorrect data' },
      ],
      reporter_impacts: [
        { value: 'medium', label: 'Medium' },
        { value: 'high', label: 'High' },
      ],
      assignable_users: [
        { id: 3, email: 'moderator@example.com', role: 'moderator', groups: [] },
        { id: 4, email: 'developer@example.com', role: 'user', groups: ['developer'] },
      ],
    },
  }
}

function buildIssueResponse() {
  return {
    data: {
      issue: {
        id: 12,
        reporter_user_id: 1,
        assignee_user_id: null,
        title: 'Provenance panel does not load',
        issue_type: 'data',
        reporter_impact: 'high',
        internal_priority: 'medium',
        status: 'new',
        page_key: 'session_provenance_report',
        page_label: 'Session Provenance Report',
        route_name: 'SessionProvenanceReport',
        route_path: '/sessions/17/provenance-report',
        public_description: 'The report stays blank.',
        expected_behavior: 'It should render.',
        technical_details: '',
        reproduction_steps: '',
        console_notes: '',
        api_notes: '',
        suspected_subsystem: '',
        route_context: { params: { sessionId: '17' } },
        related_entity_ids: { session_id: 17 },
        environment_context: { app_version: { version: 'test-build', timestamp: '2026-03-31T12:00:00Z' } },
        user_context: { reporter_groups: [] },
        capture_context: {},
        comments: [],
        code_references: {
          first_order: [{ label: 'Frontend view: SessionProvenanceReportView.vue', kind: 'frontend_view', path_or_endpoint: 'frontend/src/views/dashboard/SessionProvenanceReportView.vue', score: 91, reason: 'Matched page' }],
          second_order: [],
          third_order: [],
        },
        reporter: { email: 'reporter@example.com' },
        assignee: null,
        created_at: '2026-03-31T10:00:00Z',
        permissions: {
          can_view_issue_queue: true,
          can_edit_internal_fields: true,
          can_assign_issues: true,
          can_reporter_edit: false,
          can_comment_public: true,
          can_comment_internal: true,
          is_reporter: false,
        },
      },
    },
  }
}

describe('IssueDetailView', () => {
  beforeEach(() => {
    Object.values(mocked.issueService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
  })

  it('renders exact-page and assignee controls for triage users', async () => {
    mocked.issueService.getRegistry.mockResolvedValue(buildRegistryResponse())
    mocked.issueService.getIssue.mockResolvedValue(buildIssueResponse())

    const wrapper = mount(IssueDetailView)
    await flushPromises()

    expect(wrapper.text()).toContain('Exact page')
    expect(wrapper.text()).toContain('Workflow Upload')
    expect(wrapper.text()).toContain('developer@example.com (user)')
    expect(wrapper.text()).toContain('moderator@example.com (moderator)')
  })

  it('submits the selected assignee in triage updates', async () => {
    mocked.issueService.getRegistry.mockResolvedValue(buildRegistryResponse())
    mocked.issueService.getIssue.mockResolvedValue(buildIssueResponse())
    mocked.issueService.updateIssue.mockResolvedValue(buildIssueResponse())

    const wrapper = mount(IssueDetailView)
    await flushPromises()

    const selects = wrapper.findAll('select')
    await selects[5].setValue('4')

    const saveButton = wrapper.findAll('button').find((button) => button.text().includes('Save Triage State'))
    await saveButton.trigger('click')

    expect(mocked.issueService.updateIssue).toHaveBeenCalledWith(12, expect.objectContaining({
      status: 'new',
      internal_priority: 'medium',
      assignee_user_id: 4,
    }))
  })
})
