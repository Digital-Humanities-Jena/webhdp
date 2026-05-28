import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  router: {
    push: vi.fn(),
  },
  route: {
    params: {
      id: '7',
    },
  },
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
  authStore: {
    user: { role: 'admin' },
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => mocked.router,
    useRoute: () => mocked.route,
  }
})

vi.mock('@/services/api', () => ({
  default: mocked.api,
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => mocked.authStore,
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => mocked.toast,
}))

import ReviewSubmissionView from '../src/views/admin/ReviewSubmissionView.vue'
import FileMetadataView from '../src/views/workflow/FileMetadataView.vue'
import { useWorkflowStore } from '../src/stores/workflow.js'

describe('release-critical view behavior', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.api).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    mocked.route.params = { id: '7' }
    mocked.authStore.user = { role: 'admin' }
  })

  it('does not render the unfinished admin submission retry action', async () => {
    mocked.api.get.mockResolvedValue({
      data: {
        submission: {
          id: 7,
          status: 'failed',
          created_at: '2026-05-01T10:00:00Z',
          pipeline_id: 'render',
          session_id: 3,
        },
        session: { file_count: 2 },
        user: { email: 'moderator@example.org' },
        review_history: [],
      },
    })

    const wrapper = mount(ReviewSubmissionView, {
      global: {
        stubs: {
          LoadingSpinner: true,
          Alert: true,
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Submission #7')
    expect(wrapper.text()).not.toContain('Retry Processing')
    expect(wrapper.text()).not.toContain('Retrying...')
  })

  it('loads and saves file metadata through backend file metadata endpoints', async () => {
    const workflowStore = useWorkflowStore()
    workflowStore.setSessionId(9)
    workflowStore.setSelectedFiles([{ file_id: 101, filename: 'model.glb' }])

    mocked.api.get.mockResolvedValue({
      data: {
        metadata: {
          title: 'Existing title',
          description: 'Existing description',
          keywords: 'heritage,3d',
        },
      },
    })
    mocked.api.post.mockResolvedValue({ data: { saved_fields: 3 } })

    const wrapper = mount(FileMetadataView, {
      global: {
        stubs: {
          StepIndicator: true,
        },
      },
    })
    await flushPromises()

    expect(mocked.api.get).toHaveBeenCalledWith('/metadata/file/101')
    expect(wrapper.find('input[type="text"]').element.value).toBe('Existing title')

    await wrapper.find('input[type="text"]').setValue('Updated title')
    await wrapper.find('button.bg-indigo-600').trigger('click')
    await flushPromises()

    expect(mocked.api.post).toHaveBeenCalledWith('/metadata/file/101', {
      metadata: {
        title: 'Updated title',
        description: 'Existing description',
        keywords: 'heritage,3d',
      },
    })
    expect(wrapper.text()).toContain('Metadata saved successfully!')
  })
})
