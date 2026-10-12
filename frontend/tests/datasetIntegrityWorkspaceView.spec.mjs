import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  user: { role: 'user' },
  datasetService: {
    listDatasets: vi.fn(), getDatasetSummary: vi.fn(), getDatasetDuplicates: vi.fn(),
    getConflictReview: vi.fn(), exportDataset: vi.fn(),
  },
  submissionService: { getSessionWorkspaceSummary: vi.fn() },
}))
vi.mock('@/services/dataset.service.js', () => ({ default: mocked.datasetService }))
vi.mock('@/services/submission.service.js', () => ({ default: mocked.submissionService }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: mocked.user }) }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }))

import DatasetIntegrityWorkspaceView from '../src/views/dashboard/DatasetIntegrityWorkspaceView.vue'

const summary = (extra = {}) => ({
  dataset_key: 'session_27_dataset', record_count: 1, sessions: [],
  available_environments: ['sandbox'], ...extra,
})
const mountWorkspace = async (location) => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { name: 'DatasetIntegrityWorkspace', path: '/datasets/:datasetKey?', component: DatasetIntegrityWorkspaceView },
    { name: 'SessionRecords', path: '/sessions/:sessionId/records', component: { template: '<div />' } },
  ] })
  await router.push(location)
  await router.isReady()
  const wrapper = mount(DatasetIntegrityWorkspaceView, { global: { plugins: [router] } })
  await flushPromises()
  return { router, wrapper }
}

describe('DatasetIntegrityWorkspaceView', () => {
  beforeEach(() => {
    mocked.user.role = 'user'
    Object.values(mocked.datasetService).forEach(fn => fn.mockReset())
    mocked.submissionService.getSessionWorkspaceSummary.mockResolvedValue({ data: {} })
    mocked.datasetService.listDatasets.mockResolvedValue({ data: { datasets: [summary()] } })
    mocked.datasetService.getDatasetSummary.mockResolvedValue({ data: summary() })
    mocked.datasetService.getDatasetDuplicates.mockResolvedValue({ data: { groups: [] } })
  })

  it('opens an existing bare Sandbox dataset link in its available environment', async () => {
    const { wrapper } = await mountWorkspace('/datasets/session_27_dataset')
    expect(mocked.datasetService.listDatasets).toHaveBeenCalledWith({ environment: 'all' })
    expect(mocked.datasetService.getDatasetSummary).toHaveBeenCalledWith('session_27_dataset', { environment: 'sandbox' })
    expect(mocked.datasetService.getDatasetDuplicates).toHaveBeenCalledWith('session_27_dataset', { environment: 'sandbox' })
    expect(wrapper.findAll('select')[1].element.value).toBe('sandbox')
    expect(wrapper.text()).not.toContain('Dataset not found')
    wrapper.unmount()
  })

  it('preserves an explicit empty Production scope and allows switching back to Sandbox', async () => {
    mocked.datasetService.getDatasetSummary.mockImplementation((key, params) => Promise.resolve({ data: summary({
      empty_reason: params.environment === 'production' ? 'no_records_in_environment' : null,
      record_count: params.environment === 'production' ? 0 : 1,
    }) }))
    const { wrapper, router } = await mountWorkspace('/datasets/session_27_dataset?environment=production')
    expect(wrapper.text()).toContain('No records in Production for this dataset.')
    expect(wrapper.text()).toContain('Choose Sandbox in Environment')
    await wrapper.findAll('select')[1].setValue('sandbox')
    await flushPromises()
    expect(router.currentRoute.value.query.environment).toBe('sandbox')
    expect(wrapper.text()).not.toContain('No records in Production')
    await wrapper.findAll('select')[1].setValue('production')
    await flushPromises()
    expect(router.currentRoute.value.query.environment).toBe('production')
    expect(wrapper.text()).toContain('No records in Production')
    wrapper.unmount()
  })

  it('keeps dataset and environment controls available after a failed detail request', async () => {
    mocked.datasetService.getDatasetSummary.mockRejectedValueOnce({ error: { message: 'Dataset not found' } })
    const { wrapper } = await mountWorkspace('/datasets/session_27_dataset?environment=production')
    expect(wrapper.text()).toContain('Dataset not found')
    expect(wrapper.findAll('select')).toHaveLength(2)
    expect(wrapper.findAll('select')[1].element.disabled).toBe(false)
    await wrapper.findAll('select')[1].setValue('sandbox')
    await flushPromises()
    expect(wrapper.text()).not.toContain('Dataset not found')
    wrapper.unmount()
  })

  it('uses already decoded route keys and filters containing literal percent characters', async () => {
    const { wrapper } = await mountWorkspace({ name: 'DatasetIntegrityWorkspace', params: { datasetKey: '100%_dataset' },
      query: { environment: 'sandbox', path: 'mesh%source.glb' } })
    expect(mocked.datasetService.getDatasetSummary).toHaveBeenCalledWith('100%_dataset', { environment: 'sandbox' })
    expect(mocked.datasetService.getDatasetDuplicates).toHaveBeenCalledWith('100%_dataset', { environment: 'sandbox', path: 'mesh%source.glb' })
    wrapper.unmount()
  })

  it('discards a late dataset response after navigation to a different dataset', async () => {
    let resolvePrevious
    mocked.datasetService.getDatasetSummary.mockImplementation(key => key === 'old_dataset'
      ? new Promise(resolve => { resolvePrevious = resolve })
      : Promise.resolve({ data: summary({ dataset_key: key, sessions: [{ session_id: 28, record_count: 1 }] }) }))
    const { wrapper, router } = await mountWorkspace('/datasets/old_dataset?environment=sandbox')
    await router.push('/datasets/new_dataset?environment=sandbox')
    await flushPromises()
    resolvePrevious({ data: summary({ sessions: [{ session_id: 999, record_count: 1 }] }) })
    await flushPromises()
    expect(wrapper.text()).not.toContain('999')
    expect(wrapper.findAll('select')[0].element.value).toBe('new_dataset')
    wrapper.unmount()
  })

  it('explains a prepared dataset with no records instead of treating it as missing', async () => {
    mocked.datasetService.getDatasetSummary.mockResolvedValue({ data: summary({ record_count: 0, empty_reason: 'no_records' }) })
    const { wrapper } = await mountWorkspace('/datasets/session_27_dataset?environment=sandbox')
    expect(wrapper.text()).toContain('This dataset has no prepared records yet.')
    expect(wrapper.text()).not.toContain('Dataset not found')
    wrapper.unmount()
  })

  it('discards an export that finishes after the environment changed', async () => {
    let resolveSandbox
    mocked.datasetService.exportDataset.mockImplementation((key, payload) => payload.environment === 'sandbox'
      ? new Promise(resolve => { resolveSandbox = resolve })
      : Promise.resolve({ data: { primary_record_count: 2, secondary_record_count: 0 } }))
    const { wrapper, router } = await mountWorkspace('/datasets/session_27_dataset?environment=sandbox&tab=exports')
    await router.push('/datasets/session_27_dataset?environment=production&tab=exports')
    await flushPromises()
    resolveSandbox({ data: { primary_record_count: 999, secondary_record_count: 999 } })
    await flushPromises()
    expect(wrapper.text()).toMatch(/Primary Records\s*2/)
    expect(wrapper.text()).not.toContain('999')
    wrapper.unmount()
  })

  it('discards a conflict review that finishes after the environment changed', async () => {
    mocked.user.role = 'admin'
    let resolveProduction
    mocked.datasetService.getConflictReview.mockImplementation(params => params.environment === 'production'
      ? new Promise(resolve => { resolveProduction = resolve })
      : Promise.resolve({ data: { datasets: [], duplicate_group_count: 0 } }))
    const { wrapper, router } = await mountWorkspace('/datasets?environment=production')
    await router.push('/datasets?environment=sandbox')
    await flushPromises()
    resolveProduction({ data: { datasets: [{ dataset_key: 'stale_dataset', groups_preview: [] }], duplicate_group_count: 999 } })
    await flushPromises()
    expect(wrapper.text()).toContain('No duplicate-review datasets were found for this environment.')
    expect(wrapper.text()).not.toContain('stale_dataset')
    expect(wrapper.text()).not.toContain('999')
    wrapper.unmount()
  })
})
