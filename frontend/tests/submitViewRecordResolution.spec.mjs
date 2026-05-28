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
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
  workflowStore: {
    sessionId: 42,
    selectedFiles: [
      {
        absolute_path: '/tmp/dataset/model-a.glb',
        filename: 'model-a.glb',
        name: 'model-a.glb',
      },
    ],
    selectedPipeline: {
      identifier: 'render',
      name: 'Render',
    },
    submissionMetadata: {
      title: 'Batch title',
    },
    isBatchMode: true,
    setSelectedPipeline: vi.fn(),
    goToStep: vi.fn(),
    prevStep: vi.fn(),
    resetWorkflow: vi.fn(),
  },
  fileService: {
    getSession: vi.fn(),
  },
  pipelineService: {
    listPipelines: vi.fn(),
    getPipeline: vi.fn(),
    executePipelineWithPlan: vi.fn(),
    executePipeline: vi.fn(),
    executePipelineOnFiles: vi.fn(),
    getPipelineRun: vi.fn(),
  },
  submissionService: {
    getSessionRecordResolution: vi.fn(),
    getSessionRecords: vi.fn(),
    getSubmissionProgress: vi.fn(),
  },
  workflowState: {
    persistWorkflowState: vi.fn().mockResolvedValue(undefined),
    restoreWorkflowContext: vi.fn().mockResolvedValue({}),
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

vi.mock('@/services/file.service', () => ({ default: mocked.fileService }))
vi.mock('@/services/pipeline.service', () => ({ default: mocked.pipelineService }))
vi.mock('@/services/submission.service', () => ({ default: mocked.submissionService }))
vi.mock('@/utils/workflowState', () => ({
  persistWorkflowState: mocked.workflowState.persistWorkflowState,
  restoreWorkflowContext: mocked.workflowState.restoreWorkflowContext,
  shouldRestoreWorkflowContext: mocked.workflowState.shouldRestoreWorkflowContext,
}))

import SubmitView from '../src/views/workflow/SubmitView.vue'

const baseRecordResolutionCandidate = {
  decision_key: 'dataset::model-a',
  candidate_source_file: '/tmp/dataset/model-a.glb',
  candidate_filename: 'model-a.glb',
  normalized_source_file_path: 'dataset/model-a.glb',
  severity: 'version',
  recommended_action: 'create_version',
  selected_action: 'create_version',
  allowed_actions: ['create_version', 'skip'],
  recommended_target: {
    session_id: 7,
    local_record_id: 11,
    concept_rec_id: '7001',
  },
  selected_target: {
    session_id: 7,
    local_record_id: 11,
    concept_rec_id: '7001',
  },
}

describe('SubmitView record-resolution plan', () => {
  beforeEach(() => {
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    Object.values(mocked.fileService).forEach((fn) => fn.mockReset())
    Object.values(mocked.pipelineService).forEach((fn) => fn.mockReset())
    Object.values(mocked.submissionService).forEach((fn) => fn.mockReset())
    Object.values(mocked.workflowState).forEach((fn) => fn.mockClear?.())

    mocked.fileService.getSession.mockResolvedValue({
      data: {
        session: {
          publishing_context: {
            default_zenodo_environment: 'sandbox',
            effective_credential_source: 'user',
          },
          workspace: {
            type: 'personal',
          },
        },
      },
    })
    mocked.pipelineService.listPipelines.mockResolvedValue({
      data: {
        pipelines: [{ identifier: 'render', name: 'Render' }],
      },
    })
    mocked.pipelineService.getPipeline.mockResolvedValue({
      data: {
        pipeline: {
          config: {
            name: 'Render',
            steps: [],
          },
        },
      },
    })
  })

  it('keeps confirmation disabled while selected batch rows are unresolved', async () => {
    mocked.submissionService.getSessionRecordResolution.mockResolvedValue({
      data: {
        policy_preset: 'balanced',
        summary: {
          candidate_count: 1,
          clean: 0,
          warning: 0,
          version: 1,
          blocker: 0,
          resolved_count: 0,
          unresolved_count: 1,
          can_continue: false,
        },
        candidates: [
          {
            ...baseRecordResolutionCandidate,
            resolved: false,
          },
        ],
      },
    })

    const wrapper = mount(SubmitView, {
      global: {
        stubs: {
          StepIndicator: true,
          LoadingSpinner: true,
        },
      },
    })

    await flushPromises()

    const submitButton = wrapper.findAll('button').find((button) => button.text().includes('Confirm & Process'))
    expect(submitButton.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('still requires a saved record-resolution decision')
  })

  it('submits the saved mixed execution plan for batch sessions', async () => {
    mocked.submissionService.getSessionRecordResolution.mockResolvedValue({
      data: {
        policy_preset: 'balanced',
        summary: {
          candidate_count: 1,
          clean: 0,
          warning: 0,
          version: 1,
          blocker: 0,
          resolved_count: 1,
          unresolved_count: 0,
          can_continue: true,
        },
        candidates: [
          {
            ...baseRecordResolutionCandidate,
            resolved: true,
          },
        ],
      },
    })
    mocked.pipelineService.executePipelineWithPlan.mockResolvedValue({
      data: {
        run_id: 'run-plan-42',
      },
    })

    const wrapper = mount(SubmitView, {
      global: {
        stubs: {
          StepIndicator: true,
          LoadingSpinner: true,
        },
      },
    })

    await flushPromises()

    const submitButton = wrapper.findAll('button').find((button) => button.text().includes('Confirm & Process'))
    expect(submitButton.attributes('disabled')).toBeUndefined()

    await submitButton.trigger('click')
    await flushPromises()

    expect(mocked.pipelineService.executePipelineWithPlan).toHaveBeenCalledWith(
      42,
      'render',
      [
        {
          decision_key: 'dataset::model-a',
          action: 'create_version',
          source_file_path: '/tmp/dataset/model-a.glb',
          source_file_name: 'model-a.glb',
          target_session_id: 7,
          target_local_record_id: 11,
          target_concept_rec_id: '7001',
        },
      ],
      true,
      {
        asyncExecution: true,
        abortOnCriticalError: false,
      }
    )
  })

  it('locks batch execution to the session default environment', async () => {
    mocked.fileService.getSession.mockResolvedValue({
      data: {
        session: {
          publishing_context: {
            default_zenodo_environment: 'production',
            effective_credential_source: 'user',
          },
          workspace: {
            type: 'personal',
          },
        },
      },
    })
    mocked.submissionService.getSessionRecordResolution.mockResolvedValue({
      data: {
        policy_preset: 'balanced',
        summary: {
          candidate_count: 1,
          clean: 0,
          warning: 0,
          version: 1,
          blocker: 0,
          resolved_count: 1,
          unresolved_count: 0,
          can_continue: true,
        },
        candidates: [
          {
            ...baseRecordResolutionCandidate,
            resolved: true,
          },
        ],
      },
    })
    mocked.pipelineService.executePipelineWithPlan.mockResolvedValue({
      data: {
        run_id: 'run-plan-prod',
      },
    })

    const wrapper = mount(SubmitView, {
      global: {
        stubs: {
          StepIndicator: true,
          LoadingSpinner: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Locked to the session default because the batch record plan was analyzed against that environment.')
    const environmentToggle = wrapper.findAll('button').find((button) => button.attributes('disabled') !== undefined)
    expect(environmentToggle).toBeTruthy()

    const submitButton = wrapper.findAll('button').find((button) => button.text().includes('Confirm & Process'))
    await submitButton.trigger('click')
    await flushPromises()

    expect(mocked.pipelineService.executePipelineWithPlan).toHaveBeenCalledWith(
      42,
      'render',
      expect.any(Array),
      false,
      {
        asyncExecution: true,
        abortOnCriticalError: false,
      },
    )
  })
})
