import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  toolsService: {
    getZenodoAccountRetrievalContext: vi.fn(),
    getZenodoAccountRetrievalCoverage: vi.fn(),
    launchZenodoAccountRetrieval: vi.fn(),
    preflightZenodoAccountRetrieval: vi.fn(),
    listZenodoAccountRetrievalJobs: vi.fn(),
    getZenodoAccountRetrievalJob: vi.fn(),
    getZenodoAccountRetrievalDiagnostics: vi.fn(),
    pauseZenodoAccountRetrieval: vi.fn(),
    resumeZenodoAccountRetrieval: vi.fn(),
    cancelZenodoAccountRetrieval: vi.fn(),
    deleteZenodoAccountRetrieval: vi.fn(),
    searchZenodoAccountRetrievalRecords: vi.fn(),
    runZenodoAccountRetrievalDetector: vi.fn(),
    compactZenodoAccountRetrieval: vi.fn(),
    updateZenodoAccountRetrievalRetention: vi.fn(),
    updateZenodoAccountRetrievalSchedule: vi.fn(),
    runZenodoAccountRetrievalScheduleNow: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

vi.mock('@/services/tools.service', () => ({ default: mocked.toolsService }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

import ZenodoAccountRetrievalView from '../src/views/tools/ZenodoAccountRetrievalView.vue'

function mountView() {
  return mount(ZenodoAccountRetrievalView, {
    global: {
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :href="to"><slot /></a>',
        },
      },
    },
  })
}

describe('ZenodoAccountRetrievalView', () => {
  beforeEach(() => {
    Object.values(mocked.toolsService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.toolsService.getZenodoAccountRetrievalContext.mockResolvedValue({
      data: {
        credentials: [
          { id: 10, name: 'Production key', environment: 'production', source: 'owned', masked_preview: 'sk-...abcd' },
        ],
        active: { production: { id: 10, name: 'Production key' } },
        recent_collections: [{ retrieval_id: 'base-1', record_count: 20, latest_created: '2026-04-20T12:00:00Z' }],
        coverage: {
          collection_count: 1,
          earliest_created: '2026-04-01T00:00:00Z',
          latest_created: '2026-04-20T12:00:00Z',
          timeline: [{ retrieval_id: 'base-1', record_count: 20, earliest_created: '2026-04-01T00:00:00Z', latest_created: '2026-04-20T12:00:00Z', retrieval_mode: 'full' }],
          gaps: [],
          overlaps: [],
        },
        detectors: [
          { id: 'community_migration_candidates', label: 'Community migration candidates' },
          { id: 'objaverse', label: 'Objaverse in description' },
          { id: '3d_model_files', label: '3D model files' },
        ],
        defaults: {
          retrieval_mode: 'full',
          execution_target: 'celery_local',
          initial_window_days: 31,
          request_retries: 2,
          request_timeout_seconds: 30,
          incremental_overlap_hours: 24,
        },
      },
    })
    mocked.toolsService.listZenodoAccountRetrievalJobs.mockResolvedValue({ data: { jobs: [] } })
    mocked.toolsService.getZenodoAccountRetrievalCoverage.mockResolvedValue({
      data: {
        coverage: {
          collection_count: 1,
          earliest_created: '2026-04-01T00:00:00Z',
          latest_created: '2026-04-20T12:00:00Z',
          timeline: [{ retrieval_id: 'base-1', record_count: 20, earliest_created: '2026-04-01T00:00:00Z', latest_created: '2026-04-20T12:00:00Z', retrieval_mode: 'full' }],
          gaps: [],
          overlaps: [],
        },
      },
    })
    mocked.toolsService.getZenodoAccountRetrievalDiagnostics.mockResolvedValue({
      data: {
        diagnostics: {
          process_health: { status: 'exited', task_id: 'task-1', pid: 123 },
          heartbeat_age_seconds: 12,
          execution_target: 'celery_local',
          runtime: { proxy_policy: 'inherit_worker_environment', shard_root: '/tmp/sessions', script_version: 'test' },
          window: { page: 1 },
          log_tail: ['completed'],
        },
      },
    })
    mocked.toolsService.getZenodoAccountRetrievalJob.mockResolvedValue({
      data: {
        retrieval_id: 'retrieval-1',
        state: 'SUCCESS',
        status: 'completed',
        environment: 'production',
        progress: { percent: 100, retrieved_records: 1, created_shards: 1, rate_limited_waits: 0 },
        summary: { retrieved_records: 1, published_records: 1, draft_records: 0 },
        manifest: { shards: [{ shard_index: 1, session_id: 7, record_count: 1, window: { status: 'published' } }] },
        diagnostics: { process_health: { status: 'exited', task_id: 'task-1' }, heartbeat_age_seconds: 10, runtime: { proxy_policy: 'inherit_worker_environment' } },
      },
    })
  })

  it('starts a retrieval with the selected credential and shows generated shard links', async () => {
    mocked.toolsService.launchZenodoAccountRetrieval.mockResolvedValue({
      data: {
        retrieval_id: 'retrieval-1',
        task_id: 'task-1',
        environment: 'production',
      },
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.launchZenodoAccountRetrieval).toHaveBeenCalledWith({
      credential_id: 10,
      retrieval_mode: 'full',
      execution_target: 'celery_local',
      initial_window_days: 31,
      request_retries: 2,
      request_timeout_seconds: 30,
    })
    expect(wrapper.text()).toContain('completed')
    expect(wrapper.text()).toContain('Shard 1')
    expect(wrapper.html()).toContain('/sessions/7/records')
  })

  it('renders an empty credential state', async () => {
    mocked.toolsService.getZenodoAccountRetrievalContext.mockResolvedValue({
      data: { credentials: [], active: {} },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Add or accept a Zenodo key')
    expect(wrapper.findAll('button').some((button) => button.text() === 'Start Retrieval' && button.attributes('disabled') !== undefined)).toBe(true)
  })

  it('can queue an incremental retrieval from the latest collection', async () => {
    mocked.toolsService.launchZenodoAccountRetrieval.mockResolvedValue({
      data: {
        retrieval_id: 'retrieval-incremental',
        task_id: 'task-incremental',
        environment: 'production',
        sync_mode: 'incremental',
        parent_retrieval_id: 'base-1',
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const checkbox = wrapper.find('input[type="checkbox"]')
    await checkbox.setValue(true)
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.launchZenodoAccountRetrieval).toHaveBeenCalledWith({
      credential_id: 10,
      retrieval_mode: 'incremental',
      execution_target: 'celery_local',
      initial_window_days: 31,
      request_retries: 2,
      request_timeout_seconds: 30,
      sync_mode: 'incremental',
      incremental_overlap_hours: 24,
    })
    expect(wrapper.text()).toContain('incremental')
  })

  it('restores a paused job and resumes it', async () => {
    mocked.toolsService.listZenodoAccountRetrievalJobs.mockResolvedValue({
      data: {
        jobs: [
          {
            retrieval_id: 'retrieval-paused',
            state: 'PAUSED',
            status: 'paused',
            environment: 'production',
            progress: { percent: 35, retrieved_records: 25, pending_windows: 2 },
            summary: { retrieved_records: 25 },
            manifest: { shards: [] },
          },
        ],
      },
    })
    mocked.toolsService.getZenodoAccountRetrievalJob.mockResolvedValue({
      data: {
        retrieval_id: 'retrieval-paused',
        state: 'PAUSED',
        status: 'paused',
        environment: 'production',
        progress: { percent: 35, retrieved_records: 25, pending_windows: 2 },
        summary: { retrieved_records: 25 },
        manifest: { shards: [] },
      },
    })
    mocked.toolsService.resumeZenodoAccountRetrieval.mockResolvedValue({
      data: {
        retrieval_id: 'retrieval-paused',
        state: 'PENDING',
        status: 'Queued Zenodo account retrieval resume',
        environment: 'production',
        progress: { percent: 35, retrieved_records: 25, pending_windows: 2 },
        summary: { retrieved_records: 25 },
        manifest: { shards: [] },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('PAUSED')).trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Resume').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.resumeZenodoAccountRetrieval).toHaveBeenCalledWith('retrieval-paused')
    expect(wrapper.text()).toContain('Queued Zenodo account retrieval resume')
  })

  it('applies historical backfill defaults from coverage and runs preflight', async () => {
    mocked.toolsService.preflightZenodoAccountRetrieval.mockResolvedValue({
      data: {
        preflight: {
          queueable: true,
          execution_target: 'celery_local',
          runtime_options: { proxy_policy: 'inherit_worker_environment' },
          date_window: { start: null, end: '2026-04-01T23:59:59Z' },
          coverage: { matching_collection_count: 1 },
          warnings: [],
          checks: [{ key: 'credential_access', status: 'pass', label: 'Credential is accessible' }],
        },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === 'Backfill Before').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Preflight').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.preflightZenodoAccountRetrieval).toHaveBeenCalledWith(expect.objectContaining({
      credential_id: 10,
      retrieval_mode: 'historical_backfill',
      end_date: '2026-04-01',
    }))
    expect(wrapper.text()).toContain('Ready to queue')
    expect(wrapper.text()).toContain('Credential is accessible')
  })

  it('shows diagnostics and detector candidates from local shards', async () => {
    mocked.toolsService.launchZenodoAccountRetrieval.mockResolvedValue({
      data: {
        retrieval_id: 'retrieval-1',
        task_id: 'task-1',
        environment: 'production',
      },
    })
    mocked.toolsService.runZenodoAccountRetrievalDetector.mockResolvedValue({
      data: {
        total: 1,
        candidates: [
          { session_id: 7, local_record_id: 1, title: 'Objaverse model', zenodo_record_id: '501', reason: 'Objaverse metadata; missing target community 3dbigdataspace.' },
        ],
      },
    })

    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Diagnostics')
    expect(wrapper.text()).toContain('ETA uses current effective throughput')

    await wrapper.findAll('button').filter((button) => button.text() === 'Run').at(-1).trigger('click')
    await flushPromises()

    expect(mocked.toolsService.runZenodoAccountRetrievalDetector).toHaveBeenCalledWith('retrieval-1', {
      detector: 'community_migration_candidates',
      target_community: '3dbigdataspace',
      limit: 25,
    })
    expect(wrapper.text()).toContain('Objaverse model')
    expect(wrapper.text()).toContain('1 candidates')
  })
})
