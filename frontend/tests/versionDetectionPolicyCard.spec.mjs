import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  adminService: {
    getVersionDetectionConfig: vi.fn(),
    updateVersionDetectionConfig: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/services/admin.service', () => ({ default: mocked.adminService }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))

import VersionDetectionPolicyCard from '../src/components/admin/VersionDetectionPolicyCard.vue'

describe('VersionDetectionPolicyCard', () => {
  beforeEach(() => {
    mocked.adminService.getVersionDetectionConfig.mockReset()
    mocked.adminService.updateVersionDetectionConfig.mockReset()
    mocked.toast.success.mockReset()
    mocked.toast.error.mockReset()
  })

  it('loads the persisted version detection policy and renders derived thresholds', async () => {
    mocked.adminService.getVersionDetectionConfig.mockResolvedValue({
      data: {
        config: {
          preset: 'permissive',
          thresholds: {
            version_recommendation_score: 0.8,
            warning_score: 0.25,
          },
          allow_force_create_fresh: false,
          enabled_signals: {
            hash_matching: true,
            metadata_similarity: false,
          },
          hash_collision_policy: {
            enabled: true,
            min_size_bytes: 1048576,
            excluded_extensions: ['.json', '.txt', '.xml'],
            exclude_generated_renders: true,
          },
        },
      },
    })

    const wrapper = mount(VersionDetectionPolicyCard)
    await flushPromises()

    expect(mocked.adminService.getVersionDetectionConfig).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="policy-preset-select"]').element.value).toBe('permissive')
    expect(wrapper.get('[data-testid="policy-allow-force"]').element.checked).toBe(false)
    expect(wrapper.get('[data-testid="policy-signal-hash"]').element.checked).toBe(true)
    expect(wrapper.get('[data-testid="policy-signal-metadata"]').element.checked).toBe(false)
    expect(wrapper.get('[data-testid="policy-hash-collision-enabled"]').element.checked).toBe(true)
    expect(wrapper.get('[data-testid="policy-hash-min-size"]').element.value).toBe('1048576')
    expect(wrapper.get('[data-testid="policy-hash-exclude-generated"]').element.checked).toBe(true)
    expect(wrapper.get('[data-testid="policy-hash-excluded-extensions"]').element.value).toContain('.json')
    expect(wrapper.get('[data-testid="policy-threshold-version_recommendation_score"]').text()).toContain('0.80')
    expect(wrapper.get('[data-testid="policy-threshold-warning_score"]').text()).toContain('0.25')
    expect(wrapper.get('[data-testid="policy-dirty-state"]').text()).toContain('Saved configuration loaded')
    expect(wrapper.get('[data-testid="policy-save"]').attributes('disabled')).toBeDefined()
  })

  it('saves edited policy values through the admin config route contract', async () => {
    mocked.adminService.getVersionDetectionConfig.mockResolvedValue({
      data: {
        config: {
          preset: 'balanced',
          thresholds: {
            version_recommendation_score: 0.9,
            warning_score: 0.35,
          },
          allow_force_create_fresh: true,
          enabled_signals: {
            hash_matching: true,
            metadata_similarity: true,
          },
          hash_collision_policy: {
            enabled: true,
            min_size_bytes: 1048576,
            excluded_extensions: ['.csv', '.json', '.log', '.md', '.text', '.tsv', '.txt', '.xml'],
            exclude_generated_renders: true,
          },
        },
      },
    })
    mocked.adminService.updateVersionDetectionConfig.mockResolvedValue({
      data: {
        config: {
          preset: 'strict',
          thresholds: {
            version_recommendation_score: 0.95,
            warning_score: 0.45,
          },
          allow_force_create_fresh: false,
          enabled_signals: {
            hash_matching: false,
            metadata_similarity: true,
          },
          hash_collision_policy: {
            enabled: true,
            min_size_bytes: 2097152,
            excluded_extensions: ['.json', '.txt'],
            exclude_generated_renders: false,
          },
        },
      },
    })

    const wrapper = mount(VersionDetectionPolicyCard)
    await flushPromises()

    await wrapper.get('[data-testid="policy-preset-select"]').setValue('strict')
    await wrapper.get('[data-testid="policy-allow-force"]').setValue(false)
    await wrapper.get('[data-testid="policy-signal-hash"]').setValue(false)
    await wrapper.get('[data-testid="policy-hash-min-size"]').setValue(2097152)
    await wrapper.get('[data-testid="policy-hash-exclude-generated"]').setValue(false)
    await wrapper.get('[data-testid="policy-hash-excluded-extensions"]').setValue('.json, txt')

    expect(wrapper.get('[data-testid="policy-dirty-state"]').text()).toContain('Unsaved changes')
    expect(wrapper.get('[data-testid="policy-threshold-version_recommendation_score"]').text()).toContain('0.95')

    await wrapper.get('[data-testid="policy-save"]').trigger('click')
    await flushPromises()

    expect(mocked.adminService.updateVersionDetectionConfig).toHaveBeenCalledWith({
      preset: 'strict',
      allow_force_create_fresh: false,
      enabled_signals: {
        hash_matching: false,
        metadata_similarity: true,
      },
      hash_collision_policy: {
        enabled: true,
        min_size_bytes: 2097152,
        excluded_extensions: ['.json', '.txt'],
        exclude_generated_renders: false,
      },
    })
    expect(mocked.toast.success).toHaveBeenCalledWith('Version detection policy updated')
    expect(wrapper.get('[data-testid="policy-dirty-state"]').text()).toContain('Saved configuration loaded')
    expect(wrapper.get('[data-testid="policy-threshold-warning_score"]').text()).toContain('0.45')
  })
})
