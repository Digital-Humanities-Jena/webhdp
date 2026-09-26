import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

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
  afterEach(() => vi.useRealTimers())
  beforeEach(() => {
    sessionStorage.clear()
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

    const batchButton = wrapper.findAll('button').find((button) => button.text().includes('Batch upload with spreadsheet'))
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
  const mountUpload = () => mount(UploadView, { global: { stubs: { StepIndicator: true, 'router-link': true } } })
  it.each([403, 404, 410])('stops monitoring permanent upload error %s', async status => {
    vi.useFakeTimers()
    const wrapper = mountUpload()
    await flushPromises()
    mocked.api.get.mockRejectedValue({ status })
    await expect(wrapper.vm.$.setupState.pollProgress(42)).rejects.toThrow('no longer accessible')
    const calls = mocked.api.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(60000)
    expect(mocked.api.get).toHaveBeenCalledTimes(calls)
    wrapper.unmount()
  })
  it('backs off transient upload errors and cancels monitoring when leaving', async () => {
    vi.useFakeTimers()
    const wrapper = mountUpload()
    await flushPromises()
    mocked.api.get.mockReset().mockRejectedValue({ status: 503 })
    const polling = wrapper.vm.$.setupState.pollProgress(42).catch(error => error)
    await flushPromises()
    expect(mocked.api.get).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(mocked.api.get).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    expect((await polling).code).toBe('MONITOR_CANCELLED')
    await vi.advanceTimersByTimeAsync(60000)
    expect(mocked.api.get).toHaveBeenCalledTimes(2)
  })
  it('recovers a direct upload after a lost acknowledgement without uploading again', async () => {
    const wrapper = mountUpload()
    await flushPromises()
    mocked.fileService.uploadFile.mockRejectedValue(new Error('Lost response'))
    mocked.api.post.mockResolvedValue({ data: { session_id: 42, status: 'completed', foundFiles: [{ file_id: 1, name: 'model.glb' }] } })
    const input = wrapper.get('#file-upload')
    Object.defineProperty(input.element, 'files', { value: [new File(['model'], 'model.glb')], configurable: true })
    await input.trigger('change')
    await wrapper.get('[data-testid="upload-primary-action"]').trigger('click')
    await flushPromises()
    expect(mocked.fileService.uploadFile).toHaveBeenCalledTimes(1)
    const token = mocked.fileService.uploadFile.mock.calls[0][1].submit_token
    expect(mocked.api.post).toHaveBeenCalledWith('/sessions/file/recover', { submit_token: token }, expect.any(Object))
    expect(mocked.workflowStore.setSessionId).toHaveBeenCalledWith(42)
    expect(mocked.router.push).toHaveBeenCalled()
    wrapper.unmount()
  })
  it('recovers a direct upload after reload without the original File object', async () => {
    sessionStorage.setItem('single_upload_state:undefined', JSON.stringify({ submit_token: 'saved-upload', fingerprint: 'saved' }))
    mocked.api.post.mockResolvedValue({ data: { session_id: 42, status: 'completed', foundFiles: [{ file_id: 1, name: 'model.glb' }] } })
    const wrapper = mountUpload()
    await flushPromises()
    expect(mocked.fileService.uploadFile).not.toHaveBeenCalled()
    expect(mocked.workflowStore.setSessionId).toHaveBeenCalledWith(42)
    expect(mocked.router.push).toHaveBeenCalled()
    expect(sessionStorage.getItem('single_upload_state:undefined')).toBeNull()
    wrapper.unmount()
  })

  it('keeps the same direct-upload identity when the server has not accepted it yet', async () => {
    const wrapper = mountUpload()
    await flushPromises()
    mocked.fileService.uploadFile.mockRejectedValueOnce(new Error('Lost connection')).mockResolvedValueOnce({ data: { session_id: 42, foundFiles: [] } })
    mocked.api.post.mockRejectedValue({ status: 404, error: { message: 'Select the original file to retry.' } })
    const input = wrapper.get('#file-upload')
    Object.defineProperty(input.element, 'files', { value: [new File(['model'], 'model.glb')], configurable: true })
    await input.trigger('change')
    await wrapper.get('[data-testid="upload-primary-action"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Select the original file to retry.')
    const originalToken = mocked.fileService.uploadFile.mock.calls[0][1].submit_token
    await wrapper.get('[data-testid="upload-primary-action"]').trigger('click')
    await flushPromises()
    expect(mocked.fileService.uploadFile.mock.calls[1][1].submit_token).toBe(originalToken)
    wrapper.unmount()
  })

  it('allows an explicit new upload after an interrupted direct upload', async () => {
    sessionStorage.setItem('single_upload_state:undefined', JSON.stringify({ submit_token: 'interrupted-upload' }))
    mocked.api.post.mockResolvedValue({ data: { session_id: 42, status: 'failed' } })
    const wrapper = mountUpload()
    await flushPromises()
    expect(wrapper.text()).toContain('Review the saved session')
    const restart = wrapper.findAll('button').find(button => button.text() === 'Start a new upload')
    await restart.trigger('click')
    expect(sessionStorage.getItem('single_upload_state:undefined')).toBeNull()
    expect(mocked.fileService.uploadFile).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('keeps a batch retry identity when browser storage is unavailable', async () => {
    const wrapper = mountUpload()
    await flushPromises()
    const state = wrapper.vm.$.setupState
    const read = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Storage unavailable') })
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage unavailable') })
    state.zipFile = new File(['archive'], 'models.zip', { lastModified: 1 })
    const first = state.ensureDirectorySubmitState()
    expect(state.ensureDirectorySubmitState().submit_token).toBe(first.submit_token)
    state.sharingScope = 'institution'
    expect(state.ensureDirectorySubmitState().submit_token).not.toBe(first.submit_token)
    read.mockRestore(); write.mockRestore()
    wrapper.unmount()
  })

  it('does not reconnect to another user’s saved batch upload', async () => {
    sessionStorage.setItem('directory_upload_state:another-user', JSON.stringify({ submit_token: 'private-upload' }))
    const wrapper = mountUpload()
    await flushPromises()
    expect(mocked.api.post).not.toHaveBeenCalledWith('/sessions/directory/recover', expect.anything(), expect.anything())
    wrapper.unmount()
  })

  it('uses a new batch request when the metadata file or source folder changes', async () => {
    const wrapper = mountUpload()
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.zipFile = new File(['archive'], 'models.zip', { lastModified: 1 })
    state.msfFile = new File(['original'], 'metadata.csv', { lastModified: 1 })
    const first = state.ensureDirectorySubmitState().submit_token
    state.msfFile = new File(['revised!'], 'metadata.csv', { lastModified: 2 })
    const second = state.ensureDirectorySubmitState().submit_token
    expect(second).not.toBe(first)
    state.directoryPath = 'new-folder'
    expect(state.ensureDirectorySubmitState().submit_token).not.toBe(second)
    wrapper.unmount()
  })

  it('stops on a saved batch cancellation even when the queue still says pending', async () => {
    const wrapper = mountUpload()
    await flushPromises()
    mocked.api.get.mockResolvedValue({ data: { upload_progress: { current_stage: 'failed', dispatch_cancelled: true, status_message: 'Cancelled before processing' } } })
    await expect(wrapper.vm.$.setupState.pollProgress(42, 'unconfirmed-task')).rejects.toThrow('Cancelled before processing')
    expect(wrapper.vm.$.setupState.directoryUploadNeedsRestart).toBe(true)
    expect(mocked.api.get).not.toHaveBeenCalledWith('/sessions/tasks/unconfirmed-task', expect.anything())
    wrapper.unmount()
  })

  it('shows an explicit restart after reloading a cancelled batch upload', async () => {
    sessionStorage.setItem('directory_upload_state:undefined', JSON.stringify({ submit_token: 'cancelled-upload' }))
    mocked.api.post.mockResolvedValue({ data: { session_id: 42, session_status: 'failed', dispatch_cancelled: true } })
    const wrapper = mountUpload()
    await flushPromises()
    expect(wrapper.text()).toContain('cancelled before processing')
    expect(wrapper.text()).not.toContain('Resume / Retry Failed Files')
    await wrapper.findAll('button').find(button => button.text() === 'Start a new upload').trigger('click')
    expect(sessionStorage.getItem('directory_upload_state:undefined')).toBeNull()
    expect(mocked.api.post).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

})
