import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  fileService: {
    listSessions: vi.fn(),
    downloadHdpc: vi.fn(),
    downloadSharedHdpc: vi.fn(),
    downloadZenodoMetadata: vi.fn(),
  },
  router: {
    push: vi.fn(),
  },
  workflowStore: {
    setSessionId: vi.fn(),
    setBatchMode: vi.fn(),
    goToStep: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/services/file.service', () => ({ default: mocked.fileService }))
vi.mock('@/stores/workflow', () => ({ useWorkflowStore: () => mocked.workflowStore }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => mocked.router,
  }
})
vi.mock('@/components/dashboard/SessionGovernanceDrawer.vue', () => ({
  default: {
    props: ['open', 'session'],
    template: '<div data-testid="session-governance-drawer" :data-open="String(open)" />',
  },
}))

import DashboardView from '../src/views/dashboard/DashboardView.vue'

describe('DashboardView', () => {
  beforeEach(() => {
    Object.values(mocked.fileService).forEach((fn) => fn.mockReset())
    Object.values(mocked.workflowStore).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.router.push.mockReset()
  })

  it('disables raw .hdpc download for non-owners while exposing shared export download', async () => {
    mocked.fileService.listSessions.mockResolvedValue({
      data: {
        sessions: [
          {
            id: 42,
            created_at: '2026-03-30T10:00:00Z',
            file_count: 3,
            status: 'active',
            workspace: {
              type: 'institution',
              institution: { id: 5, name: 'Museum Network' },
            },
            publishing_context: {
              effective_credential_source: 'institution',
              default_zenodo_environment: 'sandbox',
            },
            permissions: {
              can_manage: true,
              can_download_hdpc: false,
              can_download_shared_hdpc: true,
            },
            access_mode: 'explorer_only',
            origin_type: 'hdpc_import',
            shared_hdpc_download_policy: {
              message: 'Institution readers and above can download the sanitized shared .hdpc export for institution-shared sessions.',
            },
            workflow_hint: {},
          },
        ],
      },
    })

    const wrapper = mount(DashboardView)
    await flushPromises()

    expect(mocked.fileService.listSessions).toHaveBeenCalledWith({ scope: 'all' })
    expect(wrapper.text()).toContain('Manage Session')

    const downloadButton = wrapper.findAll('button').find((button) => button.text() === 'Download .hdpc')
    expect(downloadButton.attributes('disabled')).toBeDefined()
    expect(downloadButton.attributes('title')).toContain('Only the session owner can download the raw .hdpc file')
    expect(wrapper.text()).toContain('Explorer-only')
    expect(wrapper.text()).toContain('Imported .hdpc')

    const sharedExportButton = wrapper.findAll('button').find((button) => button.text() === 'Download Shared Export')
    expect(sharedExportButton).toBeTruthy()
  })
})
