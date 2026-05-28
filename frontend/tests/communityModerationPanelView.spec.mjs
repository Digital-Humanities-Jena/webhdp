import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  toolsService: {
    getCommunityModerationRequests: vi.fn(),
    getCommunityModerationHistory: vi.fn(),
    getCommunityModerationTask: vi.fn(),
    launchCommunityModerationBatch: vi.fn(),
    planCommunityModerationSweep: vi.fn(),
    launchCommunityModerationSweep: vi.fn(),
    listCommunityModerationSweeps: vi.fn(),
    getCommunityModerationSweep: vi.fn(),
    cancelCommunityModerationSweep: vi.fn(),
    exportCommunityModerationSweep: vi.fn(),
  },
  institutionService: {
    listInstitutions: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/services/tools.service', () => ({ default: mocked.toolsService }))
vi.mock('@/services/institution.service', () => ({ default: mocked.institutionService }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

import CommunityModerationPanelView from '../src/views/tools/CommunityModerationPanelView.vue'

function moderationResponse({
  communityIdentifier,
  resolutionSource,
  institutionId = null,
  institutionName = null,
  candidateDefaults = [],
  primarySubmissionCommunity = null,
} = {}) {
  return {
    data: {
      summary: {
        open_requests_total: 0,
        requests_filtered: 0,
        request_types: [],
      },
      community: {
        slug: communityIdentifier,
        title: communityIdentifier,
      },
      filters: {
        institution_id: institutionId,
        community_identifier: communityIdentifier,
      },
      moderation_context: {
        institution_id: institutionId,
        community_identifier: communityIdentifier,
        resolution_source: resolutionSource,
        institution: institutionId ? { id: institutionId, name: institutionName } : null,
        candidate_default_communities: candidateDefaults,
        primary_submission_community: primarySubmissionCommunity,
      },
      requests: [],
      all_filtered_request_ids: [],
      all_filtered_requests_preview: [],
      pagination: {
        total: 0,
        page: 1,
        per_page: 25,
      },
    },
  }
}

describe('CommunityModerationPanelView', () => {
  beforeEach(() => {
    Object.values(mocked.toolsService).forEach((fn) => fn.mockReset())
    Object.values(mocked.institutionService).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
  })

  it('auto-fills the community from institution defaults and preserves a manual override on apply', async () => {
    mocked.institutionService.listInstitutions.mockResolvedValue({
      data: {
        institutions: [{ id: 5, name: 'Museum Network' }],
      },
    })
    mocked.toolsService.getCommunityModerationHistory.mockResolvedValue({ data: { tasks: [] } })
    mocked.toolsService.listCommunityModerationSweeps.mockResolvedValue({ data: { jobs: [] } })
    mocked.toolsService.getCommunityModerationRequests
      .mockResolvedValueOnce(moderationResponse({
        communityIdentifier: 'global-community',
        resolutionSource: 'global_override',
      }))
      .mockResolvedValueOnce(moderationResponse({
        communityIdentifier: 'moderation-a',
        resolutionSource: 'institution_moderation_default',
        institutionId: 5,
        institutionName: 'Museum Network',
        candidateDefaults: ['moderation-a', 'moderation-b'],
        primarySubmissionCommunity: 'primary-only',
      }))
      .mockResolvedValueOnce(moderationResponse({
        communityIdentifier: 'moderation-a',
        resolutionSource: 'institution_moderation_default',
        institutionId: 5,
        institutionName: 'Museum Network',
        candidateDefaults: ['moderation-a', 'moderation-b'],
        primarySubmissionCommunity: 'primary-only',
      }))

    const wrapper = mount(CommunityModerationPanelView, {
      global: {
        stubs: {
          Alert: { template: '<div data-testid="alert-stub" />' },
          LoadingSpinner: { template: '<div data-testid="spinner-stub" />' },
        },
      },
    })

    await flushPromises()

    const selects = wrapper.findAll('select')
    await selects[0].setValue('5')
    await flushPromises()

    const communityInput = wrapper.get('input[placeholder="Community identifier"]')
    expect(communityInput.element.value).toBe('moderation-a')
    expect(wrapper.text()).toContain('Institution default')
    expect(wrapper.text()).toContain('Museum Network')
    expect(wrapper.text()).toContain('moderation-b')
    expect(wrapper.text()).toContain('primary-only')

    await communityInput.setValue('manual-community')
    await wrapper.findAll('button').find((button) => button.text() === 'Apply Filters').trigger('click')
    await flushPromises()

    expect(communityInput.element.value).toBe('manual-community')
    expect(mocked.toolsService.getCommunityModerationRequests).toHaveBeenNthCalledWith(3, expect.objectContaining({
      institution_id: '5',
      community_identifier: 'manual-community',
    }))
  })

  it('plans a sweep and requires the confirmation phrase before queueing', async () => {
    mocked.institutionService.listInstitutions.mockResolvedValue({ data: { institutions: [] } })
    mocked.toolsService.getCommunityModerationHistory.mockResolvedValue({ data: { tasks: [] } })
    mocked.toolsService.listCommunityModerationSweeps.mockResolvedValue({ data: { jobs: [] } })
    mocked.toolsService.getCommunityModerationRequests.mockResolvedValue(moderationResponse({
      communityIdentifier: '3dbigdataspace',
      resolutionSource: 'global_override',
    }))
    mocked.toolsService.planCommunityModerationSweep.mockResolvedValue({
      data: {
        community_identifier: '3dbigdataspace',
        action: 'accept',
        plan_checksum: 'checksum-1',
        confirmation_text: 'ACCEPT 12 REQUESTS FOR 3dbigdataspace',
        api_key_context: { configured: true },
        summary: { total_matching: 12, planned_requests: 12, preview_actionable_count: 2 },
        preview: [{ request_id: 'req-1', title: 'Alpha', status: 'submitted', type: 'inclusion-request' }],
        community: { slug: '3dbigdataspace', title: '3D Big Data Space' },
      },
    })
    mocked.toolsService.launchCommunityModerationSweep.mockResolvedValue({
      data: {
        job_id: 'sweep-1',
        state: 'PENDING',
        phase: 'queued',
        progress: { total_requests: 12, processed: 0, percent: 0 },
        events: [],
      },
    })
    mocked.toolsService.getCommunityModerationSweep.mockResolvedValue({
      data: {
        job_id: 'sweep-1',
        state: 'SUCCESS',
        phase: 'completed',
        progress: { total_requests: 12, processed: 12, accepted: 12, failed: 0, percent: 100 },
        events: [],
      },
    })

    const wrapper = mount(CommunityModerationPanelView, {
      global: {
        stubs: {
          Alert: { template: '<div data-testid="alert-stub" />' },
          LoadingSpinner: { template: '<div data-testid="spinner-stub" />' },
        },
      },
    })

    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Sweep Mode').trigger('click')
    await wrapper.findAll('button').find((button) => button.text() === 'Plan Sweep').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('ACCEPT 12 REQUESTS FOR 3dbigdataspace')
    const queueButton = wrapper.findAll('button').find((button) => button.text() === 'Queue Sweep')
    expect(queueButton.attributes('disabled')).toBeDefined()

    await wrapper.get('input[placeholder="Type the confirmation phrase exactly"]').setValue('ACCEPT 12 REQUESTS FOR 3dbigdataspace')
    await wrapper.findAll('button').find((button) => button.text() === 'Queue Sweep').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.launchCommunityModerationSweep).toHaveBeenCalledWith(expect.objectContaining({
      community_identifier: '3dbigdataspace',
      plan_checksum: 'checksum-1',
      confirmation_text: 'ACCEPT 12 REQUESTS FOR 3dbigdataspace',
    }))
  })
})
