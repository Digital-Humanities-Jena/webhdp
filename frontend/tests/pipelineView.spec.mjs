import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  route: {
    query: {},
  },
  router: {
    push: vi.fn(),
    replace: vi.fn(),
  },
  workflowStore: {
    sessionId: null,
    selectedFiles: [],
    selectedPipeline: null,
    goToStep: vi.fn(),
    prevStep: vi.fn(),
    nextStep: vi.fn(),
    setPipeline: vi.fn(),
  },
  toast: {
    error: vi.fn(),
  },
  pipelineService: {
    listPipelines: vi.fn(),
  },
  workflowState: {
    persistWorkflowState: vi.fn().mockResolvedValue(undefined),
    restoreWorkflowContext: vi.fn().mockResolvedValue(undefined),
    shouldRestoreWorkflowContext: vi.fn(() => false),
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
    useRouter: () => mocked.router,
  }
})

vi.mock('@/stores/workflow', () => ({
  useWorkflowStore: () => mocked.workflowStore,
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => mocked.toast,
}))

vi.mock('@/services/pipeline.service', () => ({
  default: mocked.pipelineService,
}))

vi.mock('@/utils/workflowState', () => ({
  persistWorkflowState: mocked.workflowState.persistWorkflowState,
  restoreWorkflowContext: mocked.workflowState.restoreWorkflowContext,
  shouldRestoreWorkflowContext: mocked.workflowState.shouldRestoreWorkflowContext,
}))

import PipelineView from '../src/views/workflow/PipelineView.vue'

describe('PipelineView', () => {
  beforeEach(() => {
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    Object.values(mocked.pipelineService).forEach((fn) => fn.mockReset())
    Object.values(mocked.workflowState).forEach((fn) => fn.mockClear?.())
    Object.values(mocked.workflowStore).forEach((value) => value?.mockReset?.())
    mocked.workflowStore.sessionId = null
    mocked.workflowStore.selectedFiles = []
    mocked.workflowStore.selectedPipeline = null
    mocked.route.query = {}
  })

  it('redirects back to upload when the workflow session is missing', async () => {
    const wrapper = mount(PipelineView, {
      global: {
        stubs: {
          StepIndicator: true,
          LoadingSpinner: true,
          Alert: true,
        },
      },
    })
    await flushPromises()

    expect(mocked.toast.error).toHaveBeenCalledWith('Your workflow session is missing. Please start again from upload.')
    expect(mocked.router.replace).toHaveBeenCalledWith('/workflow/upload')
    expect(wrapper.text()).toContain('Select Pipeline')
  })

  it('loads pipelines and submits the chosen pipeline to the next step', async () => {
    mocked.workflowStore.sessionId = 42
    mocked.workflowStore.selectedFiles = [{ file_id: 1, name: 'asset.glb' }]
    mocked.pipelineService.listPipelines.mockResolvedValue({
      data: {
        pipelines: [
          {
            identifier: 'render',
            name: 'Render',
            description: 'Render previews',
            version: '2.0.0',
            config: { steps: [{ id: 'render-step', name: 'Render' }] },
          },
          {
            identifier: 'validate',
            name: 'Validate',
            description: 'Validate only',
            version: '1.0.0',
          },
        ],
      },
    })

    const wrapper = mount(PipelineView, {
      global: {
        stubs: {
          StepIndicator: true,
          LoadingSpinner: true,
          Alert: true,
        },
      },
    })
    await flushPromises()

    expect(mocked.pipelineService.listPipelines).toHaveBeenCalledTimes(1)
    expect(mocked.workflowState.persistWorkflowState).toHaveBeenCalledWith(mocked.workflowStore, 'pipeline')
    expect(wrapper.text()).toContain('Render previews')

    const continueButton = wrapper.findAll('button').find((button) => button.text().includes('Continue to Summary'))
    await continueButton.trigger('click')
    await flushPromises()

    expect(mocked.workflowStore.setPipeline).toHaveBeenCalledWith(expect.objectContaining({
      identifier: 'render',
      name: 'Render',
    }))
    expect(mocked.workflowStore.nextStep).toHaveBeenCalledTimes(1)
    expect(mocked.workflowState.persistWorkflowState).toHaveBeenLastCalledWith(
      mocked.workflowStore,
      'submit',
      expect.objectContaining({
        selectedPipeline: expect.objectContaining({ identifier: 'render' }),
      }),
    )
    expect(mocked.router.push).toHaveBeenCalledWith('/workflow/submit')
  })
  it('recovers from a failed pipeline request without refreshing or losing the session', async () => {
    mocked.workflowStore.sessionId = 42
    mocked.workflowStore.selectedFiles = [{ file_id: 1 }]
    mocked.pipelineService.listPipelines.mockRejectedValueOnce(new Error('Offline')).mockResolvedValue({ data: { pipelines: [{ identifier: 'render', name: 'Render' }] } })
    const wrapper = mount(PipelineView, { global: { stubs: { StepIndicator: true, LoadingSpinner: true, Alert: true } } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === 'Try again').trigger('click')
    await flushPromises()
    expect(wrapper.get('input[type="radio"]').element.checked).toBe(true)
    expect(mocked.pipelineService.listPipelines).toHaveBeenCalledTimes(2)
    expect(mocked.router.replace).not.toHaveBeenCalled()
  })

  it('keeps the user on pipeline selection when saving fails and allows retry', async () => {
    mocked.workflowStore.sessionId = 42
    mocked.workflowStore.selectedFiles = [{ file_id: 1 }]
    mocked.pipelineService.listPipelines.mockResolvedValue({ data: { pipelines: [{ identifier: 'render', name: 'Render' }] } })
    const wrapper = mount(PipelineView, { global: { stubs: { StepIndicator: true, LoadingSpinner: true } } })
    await flushPromises()
    mocked.workflowState.persistWorkflowState.mockRejectedValueOnce(new Error('Offline'))
    await wrapper.get('[data-testid="pipeline-continue"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('processing has not started')
    expect(mocked.workflowStore.nextStep).not.toHaveBeenCalled()
    expect(mocked.router.push).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="pipeline-continue"]').trigger('click')
    await flushPromises()
    expect(mocked.router.push).toHaveBeenCalledWith('/workflow/submit')
  })

})
