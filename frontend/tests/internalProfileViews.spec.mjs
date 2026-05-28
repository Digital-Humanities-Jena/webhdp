import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  route: { params: { identifier: 'ada-curator' } },
  profileService: {
    getUserProfile: vi.fn(),
    getInstitutionProfile: vi.fn(),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => mocked.route,
}))
vi.mock('@/services/profile.service', () => ({ default: mocked.profileService }))

import InstitutionProfileView from '../src/views/profiles/InstitutionProfileView.vue'
import UserProfileView from '../src/views/profiles/UserProfileView.vue'

describe('internal profile views', () => {
  beforeEach(() => {
    mocked.route.params.identifier = 'ada-curator'
    mocked.profileService.getUserProfile.mockReset()
    mocked.profileService.getInstitutionProfile.mockReset()
  })

  it('renders a loaded user profile', async () => {
    mocked.profileService.getUserProfile.mockResolvedValue({
      data: {
        user: {
          display_name: 'Ada Curator',
          slug: 'ada-curator',
          bio: 'Digitisation lead',
          orcid: '0000-0000-0000-0001',
          affiliation: 'Museum Lab',
        },
      },
    })

    const wrapper = mount(UserProfileView)
    await flushPromises()

    expect(mocked.profileService.getUserProfile).toHaveBeenCalledWith('ada-curator')
    expect(wrapper.text()).toContain('Ada Curator')
    expect(wrapper.text()).toContain('Digitisation lead')
    expect(wrapper.text()).toContain('Museum Lab')
  })

  it('renders a not-found state for user profile errors', async () => {
    mocked.profileService.getUserProfile.mockRejectedValue({
      error: { message: 'User profile was not found' },
    })

    const wrapper = mount(UserProfileView)
    await flushPromises()

    expect(wrapper.text()).toContain('User profile was not found')
  })

  it('renders a loaded institution profile', async () => {
    mocked.route.params.identifier = 'museum-network'
    mocked.profileService.getInstitutionProfile.mockResolvedValue({
      data: {
        institution: {
          name: 'Museum Network',
          legal_name: 'Museum Network Legal',
          slug: 'museum-network',
          description: 'Shared heritage workspace',
          website_url: 'https://museum.example',
        },
      },
    })

    const wrapper = mount(InstitutionProfileView)
    await flushPromises()

    expect(mocked.profileService.getInstitutionProfile).toHaveBeenCalledWith('museum-network')
    expect(wrapper.text()).toContain('Museum Network')
    expect(wrapper.text()).toContain('Shared heritage workspace')
    expect(wrapper.text()).toContain('https://museum.example')
  })
})
