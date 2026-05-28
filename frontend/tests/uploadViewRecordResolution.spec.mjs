import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  router: {
    push: vi.fn(),
  },
  authStore: {
    institutions: [],
    user: null,
  },
  workflowStore: {
    sessionId: null,
    msfPath: null,
    msfMapping: {},
    fileMetadataMap: {},
    msfProfile: {},
    isBatchMode: false,
    resetWorkflow: vi.fn(),
    setMsfData: vi.fn(),
    setSessionId: vi.fn(),
    setUploadedFiles: vi.fn(),
    setBatchMode: vi.fn(),
    goToStep: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
  fileService: {
    uploadFile: vi.fn(),
  },
  msfService: {
    prepareLocalWorkflowSession: vi.fn(),
  },
  submissionService: {
    analyzeSessionRecordResolution: vi.fn(),
    getSessionRecordResolution: vi.fn(),
    updateSessionRecordResolution: vi.fn(),
  },
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => mocked.router,
  }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => mocked.authStore,
}))

vi.mock('@/stores/workflow', () => ({
  useWorkflowStore: () => mocked.workflowStore,
}))

vi.mock('@/composables/useToast', () => ({
  useToast: () => mocked.toast,
}))

vi.mock('@/services/file.service', () => ({ default: mocked.fileService }))
vi.mock('@/services/msf.service', () => ({ default: mocked.msfService }))
vi.mock('@/services/submission.service', () => ({ default: mocked.submissionService }))
vi.mock('@/services/api', () => ({ default: mocked.api }))

import UploadView from '../src/views/workflow/UploadView.vue'

describe('UploadView record-resolution gating', () => {
  beforeEach(() => {
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.toast).forEach((fn) => fn.mockReset())
    Object.values(mocked.fileService).forEach((fn) => fn.mockReset())
    Object.values(mocked.msfService).forEach((fn) => fn.mockReset())
    Object.values(mocked.submissionService).forEach((fn) => fn.mockReset())
    Object.values(mocked.api).forEach((fn) => fn.mockReset())

    mocked.workflowStore.sessionId = null
    mocked.workflowStore.msfPath = null
    mocked.workflowStore.msfMapping = {}
    mocked.workflowStore.fileMetadataMap = {}
    mocked.workflowStore.msfProfile = {}
    mocked.workflowStore.isBatchMode = false
    mocked.workflowStore.resetWorkflow.mockImplementation(() => {
      mocked.workflowStore.sessionId = null
      mocked.workflowStore.msfPath = null
      mocked.workflowStore.msfMapping = {}
      mocked.workflowStore.fileMetadataMap = {}
      mocked.workflowStore.msfProfile = {}
      mocked.workflowStore.isBatchMode = false
    })
    mocked.workflowStore.setMsfData.mockImplementation((path, validation, mapping = {}, metadataMap = {}, profile = {}) => {
      mocked.workflowStore.msfPath = path
      mocked.workflowStore.msfMapping = mapping
      mocked.workflowStore.fileMetadataMap = metadataMap
      mocked.workflowStore.msfProfile = profile
      mocked.workflowStore.isBatchMode = true
    })
    mocked.workflowStore.setSessionId.mockImplementation((sessionId) => {
      mocked.workflowStore.sessionId = sessionId
    })
    mocked.workflowStore.setBatchMode.mockImplementation((value) => {
      mocked.workflowStore.isBatchMode = value
    })

    mocked.api.get.mockImplementation((url) => {
      if (url === '/admin/storage-status') {
        return Promise.resolve({
          data: {
            active_storage: 'dropbox',
            active_message: 'Cloud storage ready',
            config: { storage_mode: 'pure_cloud' },
          },
        })
      }
      if (url === '/sessions/42/progress') {
        return Promise.resolve({
          data: {
            upload_progress: {
              percent: 100,
              failed_count: 0,
              current_stage: 'completed',
              status_message: 'Processing complete',
            },
          },
        })
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    mocked.api.post.mockImplementation((url, payload, config = {}) => {
      if (url === '/sessions/directory' && config?.params?.validate_only) {
        return Promise.resolve({
          data: {
            msf_validation: {
              is_valid: true,
              matched_count: 1,
              matched_files: ['model-a.glb'],
            },
            msf_mapping: {},
            file_metadata_map: {},
            msf_profile: {
              parse_options: {},
            },
          },
        })
      }
      if (url === '/sessions/directory') {
        return Promise.resolve({
          data: {
            task_id: null,
            session_id: 42,
            submit_token: 'submit-token-42',
          },
        })
      }
      throw new Error(`Unexpected POST ${url}`)
    })

    mocked.submissionService.analyzeSessionRecordResolution.mockResolvedValue({
      data: {
        policy_preset: 'balanced',
        summary: {
          candidate_count: 1,
          affected_count: 1,
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
            decision_key: 'dataset::model-a',
            candidate_filename: 'model-a.glb',
            candidate_source_file: '/tmp/dataset/model-a.glb',
            normalized_source_file_path: 'dataset/model-a.glb',
            severity: 'version',
            recommended_action: 'create_version',
            selected_action: 'create_version',
            allowed_actions: ['create_version', 'skip'],
            confidence: { label: 'high', score: 1 },
            explanation: 'Same-lineage exact path match.',
            matched_record_count: 1,
            matched_records: [],
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
            reason_codes: ['exact_path_same_lineage'],
            evidence: {},
            resolved: false,
          },
        ],
      },
    })
  })

  it('stops ZIP/cloud batch uploads on the record-resolution review step when affected candidates remain', async () => {
    const wrapper = mount(UploadView, {
      global: {
        stubs: {
          StepIndicator: true,
          'router-link': true,
          RecordResolutionReview: {
            template: '<div data-test="record-review">record review</div>',
          },
        },
      },
    })

    const batchButton = wrapper.findAll('button').find((button) => button.text().includes('MSF-driven batch workflow'))
    await batchButton.trigger('click')
    await flushPromises()

    const fileInputs = wrapper.findAll('input[type="file"]')
    Object.defineProperty(fileInputs[0].element, 'files', {
      value: [new File(['zip'], 'models.zip', { type: 'application/zip' })],
      configurable: true,
    })
    await fileInputs[0].trigger('change')
    Object.defineProperty(fileInputs[1].element, 'files', {
      value: [new File(['msf'], 'models.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })],
      configurable: true,
    })
    await fileInputs[1].trigger('change')
    await flushPromises()

    const validateButton = wrapper.findAll('button').find((button) => button.text().includes('Validate MSF'))
    await validateButton.trigger('click')
    await flushPromises()

    const primaryButton = wrapper.findAll('button').find((button) => button.text().includes('Scan & Continue'))
    await primaryButton.trigger('click')
    await flushPromises()

    expect(mocked.submissionService.analyzeSessionRecordResolution).toHaveBeenCalledWith(42, {})
    expect(wrapper.find('[data-test="record-review"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Review the affected candidates below and save the plan before continuing.')
    expect(mocked.router.push).not.toHaveBeenCalled()
  })
})
