import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  fileService: {
    getWorkflowState: vi.fn(),
    getNodes: vi.fn(),
    updateWorkflowState: vi.fn(),
  },
}))

vi.mock('@/services/file.service', () => ({
  default: mocked.fileService,
}))

import {
  isDownloadableSessionState,
  normalizeSessionState,
  normalizeSourceFileState,
  buildWorkflowResumeLocation,
  persistWorkflowState,
  restoreWorkflowContext,
  sessionStateClass,
  sourceFileStateClass,
  shouldRestoreWorkflowContext,
} from '../src/utils/workflowState.js'

function createWorkflowStoreDouble(overrides = {}) {
  const store = {
    sessionId: overrides.sessionId ?? null,
    selectedFiles: overrides.selectedFiles ?? [],
    selectedPipeline: overrides.selectedPipeline ?? null,
    msfPath: overrides.msfPath ?? null,
    msfMapping: overrides.msfMapping ?? {},
    lodMinimumViablePrefs: overrides.lodMinimumViablePrefs ?? { edm: true, iiif: true, mets: true },
    uploadedFiles: overrides.uploadedFiles ?? [],
    submissionMetadata: overrides.submissionMetadata ?? {},
    isBatchMode: overrides.isBatchMode ?? false,
    fileMetadataMap: overrides.fileMetadataMap ?? {},
    currentStep: overrides.currentStep ?? 1,
  }

  store.setSessionId = vi.fn((value) => {
    store.sessionId = value
  })
  store.setBatchMode = vi.fn((value) => {
    store.isBatchMode = value
  })
  store.goToStep = vi.fn((value) => {
    store.currentStep = value
  })
  store.setUploadedFiles = vi.fn((value) => {
    store.uploadedFiles = value
  })
  store.setSelectedFiles = vi.fn((value) => {
    store.selectedFiles = value
  })
  store.setSelectedPipeline = vi.fn((value) => {
    store.selectedPipeline = value
  })
  store.setMsfProfile = vi.fn()
  store.setMsfParseOptions = vi.fn()
  store.setMsfPath = vi.fn((value) => {
    store.msfPath = value
  })
  store.setMsfMapping = vi.fn((value) => {
    store.msfMapping = value
  })
  store.setFileMetadataMap = vi.fn((value) => {
    store.fileMetadataMap = value
  })
  store.setLodMinimumViablePrefs = vi.fn((value) => {
    store.lodMinimumViablePrefs = value
  })
  store.setSubmissionMetadata = vi.fn((value) => {
    store.submissionMetadata = value
  })

  return store
}

describe('workflowState helpers', () => {
  beforeEach(() => {
    Object.values(mocked.fileService).forEach((mockFn) => mockFn.mockReset())
  })

  it('persists workflow state with normalized file keys and pipeline metadata', async () => {
    const store = createWorkflowStoreDouble({
      sessionId: 42,
      selectedFiles: [
        { file_id: 7, absolute_path: '/tmp/model.glb' },
        { absolute_path: '/tmp/alt.glb' },
      ],
      selectedPipeline: { id: 'render', name: 'Render', description: 'Renders previews' },
      msfPath: '/tmp/source.xlsx',
      msfMapping: { Title: 'title' },
      isBatchMode: true,
    })
    mocked.fileService.updateWorkflowState.mockResolvedValue({ data: { ok: true } })

    await persistWorkflowState(store, 'submit', { submissionId: 18, pipelineRunId: 'run-42' })

    expect(mocked.fileService.updateWorkflowState).toHaveBeenCalledWith(42, {
      phase: 'submit',
      current_step: 7,
      is_batch_mode: true,
      selected_file_keys: ['7', '/tmp/alt.glb'],
      selected_pipeline: {
        identifier: 'render',
        name: 'Render',
        description: 'Renders previews',
      },
      msf_path: '/tmp/source.xlsx',
      msf_mapping: { Title: 'title' },
      lod_minimum_viable: { edm: true, iiif: true, mets: true },
      submission_id: 18,
      pipeline_run_id: 'run-42',
    })
  })

  it('restores original bundles without reselecting generated artifacts', async () => {
    const store = createWorkflowStoreDouble()
    const reference = { file_id: 2, filename: 'site.tif', file_type: 'source', children: [] }
    const model = { file_id: 1, filename: 'site.glb', file_type: 'primary_source', children: [reference] }
    mocked.fileService.getWorkflowState.mockResolvedValue({ data: {
      state: { selected_file_keys: ['1', '3'] },
    } })
    mocked.fileService.getNodes.mockResolvedValue({ data: { nodes: [
      model,
      { file_id: 3, filename: 'site_georeferenced.glb', file_type: 'generated' },
      { file_id: 4, filename: 'alignment_overlay.png', file_type: 'generated' },
    ] } })
    await restoreWorkflowContext(store, 42)
    expect(store.uploadedFiles).toEqual([model])
    expect(store.selectedFiles).toEqual([model])
    expect(store.uploadedFiles[0].children).toEqual([reference])
  })

  it('decides when workflow restoration is required', () => {
    const store = createWorkflowStoreDouble({
      sessionId: 42,
      uploadedFiles: [{ file_id: 1 }],
      selectedFiles: [{ file_id: 1 }],
      submissionMetadata: { title: 'Ready' },
      selectedPipeline: { identifier: 'render' },
      isBatchMode: true,
      fileMetadataMap: { 'model.glb': { title: 'Ready' } },
      msfPath: '/tmp/source.xlsx',
    })

    expect(shouldRestoreWorkflowContext(store, 42, {})).toBe(false)
    expect(shouldRestoreWorkflowContext(store, 7, {})).toBe(true)
    expect(shouldRestoreWorkflowContext(store, 42, { requireSubmissionMetadata: true })).toBe(false)
    expect(shouldRestoreWorkflowContext(createWorkflowStoreDouble({ sessionId: 42 }), 42, { requireUploadedFiles: true })).toBe(true)
    expect(shouldRestoreWorkflowContext(store, 42, { force: true })).toBe(true)
  })

  it('restores workflow state, selected files, and draft metadata from the backend payload', async () => {
    const store = createWorkflowStoreDouble()
    mocked.fileService.getWorkflowState.mockResolvedValue({
      data: {
        state: {
          phase: 'pipeline',
          current_step: 6,
          is_batch_mode: true,
          selected_file_keys: ['child-1'],
          selected_pipeline: {
            identifier: 'render',
            name: 'Render',
            description: 'Renders previews',
          },
          msf_path: '/tmp/source.xlsx',
          msf_mapping: { Title: 'title' },
          lod_minimum_viable: { edm: false, iiif: true, mets: true },
        },
        draft_metadata: { title: 'Recovered draft' },
        msf_profile: {
          source_file_path: '/tmp/profile.xlsx',
          parse_options: { sheet_name: 'Sheet1' },
        },
        file_metadata_map: {
          'model.glb': { title: 'Recovered title' },
        },
        workflow_hint: { resume_route: '/workflow/pipeline' },
      },
    })
    mocked.fileService.getNodes.mockResolvedValue({
      data: {
        nodes: [
          {
            file_id: 'root-1',
            children: [
              {
                file_id: 'child-1',
                absolute_path: '/tmp/model.glb',
                children: [],
              },
            ],
          },
        ],
      },
    })

    const result = await restoreWorkflowContext(store, 42)

    expect(mocked.fileService.getWorkflowState).toHaveBeenCalledWith(42, { suppressGlobalError: true })
    expect(mocked.fileService.getNodes).toHaveBeenCalledWith(42, { suppressGlobalError: true })
    expect(store.setSessionId).toHaveBeenCalledWith(42)
    expect(store.goToStep).toHaveBeenCalledWith(6)
    expect(store.setSelectedFiles).toHaveBeenCalledWith([
      {
        file_id: 'child-1',
        absolute_path: '/tmp/model.glb',
        children: [],
      },
    ])
    expect(store.setSelectedPipeline).toHaveBeenCalledWith({
      id: 'render',
      identifier: 'render',
      name: 'Render',
      description: 'Renders previews',
    })
    expect(store.setSubmissionMetadata).toHaveBeenCalledWith({ title: 'Recovered draft' })
    expect(result.workflowHint).toEqual({ resume_route: '/workflow/pipeline' })
  })

  it('builds workflow resume locations from workflow hints', () => {
    expect(buildWorkflowResumeLocation(42, {
      resume_route: '/workflow/submit',
      submission_id: 9,
      pipeline_run_id: 'run-9',
    })).toEqual({
      path: '/workflow/submit',
      query: {
        sessionId: '42',
        resume: 'workflow',
        runId: 'run-9',
        submissionId: '9',
      },
    })
  })

  it('handles status normalization helpers and early-return restoration branches', async () => {
    expect(normalizeSessionState('ACTIVE')).toBe('scanned')
    expect(isDownloadableSessionState('processing')).toBe(true)
    expect(isDownloadableSessionState('failed')).toBe(false)
    expect(sessionStateClass('failed')).toContain('bg-red-100')
    expect(sessionStateClass('mystery')).toContain('bg-gray-100')
    expect(normalizeSourceFileState('uploaded')).toBe('registered')
    expect(sourceFileStateClass('selected')).toContain('bg-violet-100')
    expect(sourceFileStateClass('mystery')).toContain('bg-gray-100')

    await expect(restoreWorkflowContext(createWorkflowStoreDouble(), 'invalid')).rejects.toThrow('Invalid session ID')
    await expect(persistWorkflowState(createWorkflowStoreDouble(), 'upload')).resolves.toBeNull()
    expect(shouldRestoreWorkflowContext(createWorkflowStoreDouble({ sessionId: 7 }), 7, { requireMsfPath: true })).toBe(true)

    expect(buildWorkflowResumeLocation(7, {
      requires_msf_repair: true,
    })).toEqual({
      path: '/workflow/upload',
      query: {
        sessionId: '7',
        resume: 'repair',
      },
    })
  })

  it('supports restoration without nodes or draft metadata when those payloads are omitted', async () => {
    const store = createWorkflowStoreDouble()
    mocked.fileService.getWorkflowState.mockResolvedValue({
      data: {
        state: {
          phase: 'upload',
          current_step: 1,
          is_batch_mode: false,
        },
      },
    })

    const result = await restoreWorkflowContext(store, 15, { includeNodes: false, includeDraft: false })

    expect(mocked.fileService.getWorkflowState).toHaveBeenCalledWith(15, { suppressGlobalError: true })
    expect(mocked.fileService.getNodes).not.toHaveBeenCalled()
    expect(store.setUploadedFiles).not.toHaveBeenCalled()
    expect(store.setSubmissionMetadata).not.toHaveBeenCalled()
    expect(result.nodes).toEqual([])
    expect(result.draftMetadata).toEqual({})
  })
})
