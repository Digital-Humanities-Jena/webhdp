import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  toolsService: {
    getCommunityMigrationContext: vi.fn(),
    planCommunityMigration: vi.fn(),
    launchCommunityMigration: vi.fn(),
    listCommunityMigrationJobs: vi.fn(),
    getCommunityMigrationJob: vi.fn(),
    resumeCommunityMigration: vi.fn(),
    cancelCommunityMigration: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/services/tools.service', () => ({ default: mocked.toolsService }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

import CommunityMigrationView from '../src/views/tools/CommunityMigrationView.vue'

function mountView() {
  return mount(CommunityMigrationView, {
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

async function fillCommunities(wrapper) {
  const source = wrapper.find('input[placeholder="community-a"]')
  const target = wrapper.find('input[placeholder="community-b"]')
  await source.setValue('alpha')
  await target.setValue('beta')
}

describe('CommunityMigrationView', () => {
  beforeEach(() => {
    Object.values(mocked.toolsService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.toolsService.getCommunityMigrationContext.mockResolvedValue({
      data: {
        retrievals: [
          {
            retrieval_id: 'retrieval-1',
            collection: { record_count: 42 },
            summary: { retrieved_records: 42 },
          },
        ],
        defaults: { record_status: 'all', editable_only: true },
      },
    })
    mocked.toolsService.listCommunityMigrationJobs.mockResolvedValue({ data: { jobs: [] } })
  })

  it('loads context and renders dry-run plan counts', async () => {
    mocked.toolsService.planCommunityMigration.mockResolvedValue({
      data: {
        plan_checksum: 'checksum-1',
        summary: {
          total_records: 3,
          editable: 2,
          append_needed: 1,
          already_in_target: 1,
          ineligible: 1,
          target_owner_token_required: false,
          pending_moderation_note: 'Target community accepts direct additions; no Community B owner token is required.',
        },
        records_preview: [
          {
            session_id: 7,
            local_record_id: 1,
            record_title: 'Record Alpha',
            record_status: 'published',
            is_editable: true,
            before_communities: ['alpha'],
          },
        ],
      },
    })

    const wrapper = mountView()
    await flushPromises()
    await fillCommunities(wrapper)
    await wrapper.findAll('button').find((button) => button.text().includes('Build Plan')).trigger('click')
    await flushPromises()

    expect(mocked.toolsService.planCommunityMigration).toHaveBeenCalledWith({
      source_retrieval_id: 'retrieval-1',
      source_community: 'alpha',
      target_community: 'beta',
      filters: {
        record_status: 'all',
        editable_only: true,
        q: '',
        created_from: null,
        created_to: null,
      },
      options: { remove_source_after_verify: false, target_acceptance_policy: 'direct' },
    })
    expect(wrapper.text()).toContain('Dry-Run Summary')
    expect(wrapper.text()).toContain('Record Alpha')
    expect(wrapper.text()).toContain('Append Needed')
  })

  it('keeps queue disabled when a plan has no actionable records', async () => {
    mocked.toolsService.planCommunityMigration.mockResolvedValue({
      data: {
        plan_checksum: 'checksum-empty',
        summary: {
          total_records: 0,
          editable: 0,
          append_needed: 0,
          already_in_target: 0,
          ineligible: 0,
          target_owner_token_required: false,
        },
        records_preview: [],
      },
    })

    const wrapper = mountView()
    await flushPromises()
    await fillCommunities(wrapper)
    await wrapper.findAll('button').find((button) => button.text().includes('Build Plan')).trigger('click')
    await flushPromises()

    const queueButton = wrapper.findAll('button').find((button) => button.text().includes('Queue Migration'))
    expect(queueButton.attributes('disabled')).toBeDefined()
  })

  it('queues a migration and renders progress plus export control', async () => {
    mocked.toolsService.planCommunityMigration.mockResolvedValue({
      data: {
        plan_checksum: 'checksum-queue',
        summary: {
          total_records: 2,
          editable: 2,
          append_needed: 1,
          already_in_target: 1,
          ineligible: 0,
          target_owner_token_required: false,
        },
        records_preview: [],
      },
    })
    mocked.toolsService.launchCommunityMigration.mockResolvedValue({
      data: {
        job_id: 'migration-1',
        state: 'PENDING',
        phase: 'queued',
        summary: { total_records: 2 },
        progress: { total_records: 2, processed: 0, percent: 0 },
      },
    })
    mocked.toolsService.getCommunityMigrationJob.mockResolvedValue({
      data: {
        job_id: 'migration-1',
        state: 'SUCCESS',
        phase: 'completed',
        summary: { total_records: 2, target_verified: 2 },
        progress: { total_records: 2, processed: 2, succeeded: 2, failed: 0, percent: 100 },
      },
    })

    const wrapper = mountView()
    await flushPromises()
    await fillCommunities(wrapper)
    await wrapper.findAll('button').find((button) => button.text().includes('Build Plan')).trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Queue Migration')).trigger('click')
    await flushPromises()

    expect(mocked.toolsService.launchCommunityMigration).toHaveBeenCalled()
    expect(mocked.toolsService.launchCommunityMigration).toHaveBeenCalledWith(expect.objectContaining({ plan_checksum: 'checksum-queue' }))
    expect(wrapper.text()).toContain('Job Progress')
    expect(wrapper.text()).toContain('SUCCESS')
    expect(wrapper.text()).toContain('Community B Owner Token')
    expect(wrapper.text()).toContain('Not required')
    expect(wrapper.html()).toContain('/api/v1/tools/community-migrations/jobs/migration-1/export?format=csv')
  })

  it('does not bind dry-run export controls to an unrelated recent job', async () => {
    mocked.toolsService.listCommunityMigrationJobs.mockResolvedValue({
      data: {
        jobs: [
          {
            job_id: 'old-migration',
            source_community: 'old-alpha',
            target_community: 'old-beta',
            state: 'SUCCESS',
            summary: { total_records: 1 },
            progress: { total_records: 1, processed: 1 },
          },
        ],
      },
    })
    mocked.toolsService.planCommunityMigration.mockResolvedValue({
      data: {
        plan_checksum: 'fresh-checksum',
        summary: {
          total_records: 1,
          editable: 1,
          append_needed: 1,
          already_in_target: 0,
          ineligible: 0,
          target_owner_token_required: false,
        },
        records_preview: [],
      },
    })

    const wrapper = mountView()
    await flushPromises()
    await fillCommunities(wrapper)
    await wrapper.findAll('button').find((button) => button.text().includes('Build Plan')).trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Dry-Run Summary')
    expect(wrapper.text()).not.toContain('Job Progress')
    expect(wrapper.html()).not.toContain('old-migration/export')
  })
})
