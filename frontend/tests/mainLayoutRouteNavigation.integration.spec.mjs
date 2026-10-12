import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'

const mocked = vi.hoisted(() => ({
  authStore: {
    token: 'token',
    user: { id: 1, email: 'user@example.com', role: 'user', groups: [] },
    institutions: [],
    hasCapability: () => false,
    hasGroup: () => false,
  },
  notifications: { startPolling: vi.fn(), stopPolling: vi.fn(), reset: vi.fn() },
  submissionService: {
    getSessionRecords: vi.fn(),
    getSessionWorkspaceSummary: vi.fn(),
    listSessionBatchOperations: vi.fn(),
    getSessionRecordDetail: vi.fn(),
  },
  api: { get: vi.fn() },
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocked.authStore }))
vi.mock('@/stores/system', () => ({ useSystemStore: () => ({ coreOnly: false }) }))
vi.mock('@/stores/notifications', () => ({ useNotificationStore: () => mocked.notifications }))
vi.mock('@/services/submission.service.js', () => ({ default: mocked.submissionService }))
vi.mock('@/services/api', () => ({ default: mocked.api }))

import MainLayout from '../src/components/layout/MainLayout.vue'
import SessionRecordsView from '../src/views/dashboard/SessionRecordsView.vue'
import RecordDetailView from '../src/views/dashboard/RecordDetailView.vue'

describe('MainLayout detail route navigation', () => {
  let wrapper

  beforeEach(() => {
    mocked.submissionService.getSessionRecords.mockImplementation(async (sessionId) => ({ data: {
      session: { id: sessionId, status: 'completed' },
      records: [{ local_record_id: 9, record_title: `Model in session ${sessionId}`, record_status: 'draft' }],
    } }))
    mocked.submissionService.getSessionWorkspaceSummary.mockImplementation(async (sessionId) => ({ data: {
      project_info: { project_name: `Workspace ${sessionId}` },
    } }))
    mocked.submissionService.listSessionBatchOperations.mockResolvedValue({ data: { tasks: [] } })
    mocked.submissionService.getSessionRecordDetail.mockImplementation(async (sessionId, recordId) => ({ data: {
      record: { local_record_id: recordId, record_title: `Model ${sessionId}/${recordId}`, record_status: 'draft', files: [] },
    } }))
    mocked.api.get.mockResolvedValue({ data: { available: false } })
  })

  afterEach(() => {
    wrapper?.unmount()
  })

  async function openRoute(path) {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{
        path: '/',
        component: MainLayout,
        children: [
          { path: 'sessions/:sessionId/records', component: SessionRecordsView },
          { path: 'sessions/:sessionId/records/:recordId', component: RecordDetailView },
        ],
      }, {
        path: '/:pathMatch(.*)*',
        component: { template: '<div />' },
      }],
    })
    await router.push(path)
    await router.isReady()
    wrapper = mount(RouterView, {
      global: {
        plugins: [router],
        stubs: { NotificationBell: true, SessionGovernanceDrawer: true, PlaygroundModelViewer: true },
      },
    })
    await flushPromises()
    return router
  }

  it('reloads session records on sibling navigation and preserves filters for query changes', async () => {
    const router = await openRoute('/sessions/42/records')
    expect(wrapper.text()).toContain('Model in session 42')
    const previousPage = wrapper.findComponent(SessionRecordsView).vm.$.uid

    await router.push('/sessions/43/records')
    await flushPromises()

    const currentPage = wrapper.findComponent(SessionRecordsView).vm.$.uid
    expect(currentPage).not.toBe(previousPage)
    expect(mocked.submissionService.getSessionRecords).toHaveBeenLastCalledWith(43)
    expect(mocked.submissionService.getSessionWorkspaceSummary).toHaveBeenLastCalledWith(43)
    expect(wrapper.text()).toContain('Model in session 43')
    expect(wrapper.text()).not.toContain('Model in session 42')

    const search = wrapper.find('input[placeholder="Search title, DOI, record ID..."]')
    await search.setValue('Model')
    await router.push('/sessions/43/records?view=files')
    await flushPromises()

    expect(wrapper.findComponent(SessionRecordsView).vm.$.uid).toBe(currentPage)
    expect(search.element.value).toBe('Model')
    expect(mocked.submissionService.getSessionRecords).toHaveBeenCalledTimes(2)
  })

  it('reloads both changed record and session IDs while preserving query-only state', async () => {
    const router = await openRoute('/sessions/42/records/9')
    expect(wrapper.text()).toContain('Model 42/9')

    await router.push('/sessions/42/records/10')
    await flushPromises()

    expect(mocked.submissionService.getSessionRecordDetail).toHaveBeenLastCalledWith(42, 10)
    expect(mocked.api.get).toHaveBeenLastCalledWith('/sessions/42/records/10/lod', { suppressGlobalError: true })
    expect(wrapper.text()).toContain('Model 42/10')
    expect(wrapper.text()).not.toContain('Model 42/9')

    await router.push('/sessions/43/records/10')
    await flushPromises()

    expect(mocked.submissionService.getSessionRecordDetail).toHaveBeenLastCalledWith(43, 10)
    expect(wrapper.text()).toContain('Model 43/10')
    expect(wrapper.text()).not.toContain('Model 42/10')
    const currentPage = wrapper.findComponent(RecordDetailView).vm.$.uid

    await router.push('/sessions/43/records/10?format=edm')
    await flushPromises()

    expect(wrapper.findComponent(RecordDetailView).vm.$.uid).toBe(currentPage)
    expect(mocked.submissionService.getSessionRecordDetail).toHaveBeenCalledTimes(3)
  })
})
