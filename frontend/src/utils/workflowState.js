import fileService from '@/services/file.service'

export const WORKFLOW_PHASE_TO_STEP = {
  upload: 1,
  msf_analysis: 2,
  files: 3,
  metadata: 4,
  edm_selection: 5,
  pipeline: 6,
  submit: 7,
  processing: 7,
  completed: 7,
  failed: 7
}

const SESSION_STATE_ALIASES = {
  pending: 'queued',
  queued: 'queued',
  active: 'scanned',
  ready: 'scanned',
  scanned: 'scanned',
  processing: 'submitting',
  submitting: 'submitting',
  completed: 'completed',
  failed: 'failed'
}

const FILE_STATE_ALIASES = {
  pending: 'queued',
  queued: 'queued',
  processing: 'queued',
  uploaded: 'registered',
  ready: 'registered',
  scanned: 'registered',
  registered: 'registered',
  selected: 'selected',
  processed: 'processed',
  completed: 'processed',
  failed: 'missing',
  missing: 'missing',
  error: 'failed',
  invalid: 'failed'
}

export const normalizeSessionState = (status) => {
  const normalized = String(status || '').trim().toLowerCase()
  return SESSION_STATE_ALIASES[normalized] || (normalized || 'queued')
}

export const isDownloadableSessionState = (status) => {
  return ['scanned', 'submitting', 'completed'].includes(normalizeSessionState(status))
}

export const sessionStateClass = (status) => {
  switch (normalizeSessionState(status)) {
    case 'queued':
      return 'bg-amber-100 text-amber-800'
    case 'scanned':
      return 'bg-emerald-100 text-emerald-800'
    case 'submitting':
      return 'bg-indigo-100 text-indigo-800'
    case 'completed':
      return 'bg-blue-100 text-blue-800'
    case 'failed':
      return 'bg-red-100 text-red-800'
    default:
      return 'bg-gray-100 text-gray-800'
  }
}

export const normalizeSourceFileState = (status) => {
  const normalized = String(status || '').trim().toLowerCase()
  return FILE_STATE_ALIASES[normalized] || (normalized || 'queued')
}

export const sourceFileStateClass = (status) => {
  switch (normalizeSourceFileState(status)) {
    case 'registered':
      return 'bg-blue-100 text-blue-800'
    case 'queued':
      return 'bg-amber-100 text-amber-800'
    case 'missing':
      return 'bg-red-100 text-red-800'
    case 'selected':
      return 'bg-violet-100 text-violet-800'
    case 'processed':
      return 'bg-emerald-100 text-emerald-800'
    case 'failed':
      return 'bg-red-100 text-red-800'
    default:
      return 'bg-gray-100 text-gray-800'
  }
}

export const getNodeResumeKey = (node) => {
  if (!node || typeof node !== 'object') return ''
  return String(node.file_id || node.absolute_path || node.path || node.relative_path || node.name || '').trim()
}

export const recordFileStatusLabel = (status) => ({
  validation_pending: 'Validation required',
  validation_pending_uploaded: 'Uploaded; revalidation required',
  pending: 'Pending upload',
  removal_pending: 'Pending removal from draft',
  disabled: 'Not included',
  uploaded: 'Uploaded',
  upload_error: 'Upload failed',
}[status] || String(status || 'pending').replaceAll('_', ' '))

const hasObjectKeys = (value) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length > 0

const flattenNodes = (nodes = []) => {
  const flat = []
  nodes.forEach((node) => {
    if (!node || typeof node !== 'object') return
    flat.push(node)
    if (Array.isArray(node.children) && node.children.length > 0) {
      flat.push(...flattenNodes(node.children))
    }
  })
  return flat
}

const selectNodesByKeys = (nodes, selectedFileKeys = []) => {
  const flatNodes = flattenNodes(nodes)
  const nodeMap = new Map(flatNodes.map(node => [getNodeResumeKey(node), node]))
  return selectedFileKeys
    .map(key => nodeMap.get(String(key || '').trim()))
    .filter(Boolean)
}

export const persistWorkflowState = async (workflowStore, phase, overrides = {}) => {
  if (!workflowStore.sessionId) return null

  const selectedPipeline = overrides.selectedPipeline === undefined
    ? workflowStore.selectedPipeline
    : overrides.selectedPipeline

  const payload = {
    phase,
    current_step: overrides.currentStep ?? WORKFLOW_PHASE_TO_STEP[phase] ?? workflowStore.currentStep ?? 1,
    is_batch_mode: overrides.isBatchMode ?? workflowStore.isBatchMode,
    selected_file_keys: overrides.selectedFileKeys
      ?? (workflowStore.selectedFiles || []).map(getNodeResumeKey).filter(Boolean),
    selected_pipeline: selectedPipeline
      ? {
          identifier: selectedPipeline.identifier || selectedPipeline.id,
          name: selectedPipeline.name || null,
          description: selectedPipeline.description || null
        }
      : null,
    msf_path: overrides.msfPath ?? workflowStore.msfPath ?? null,
    msf_mapping: overrides.msfMapping ?? workflowStore.msfMapping ?? {},
    lod_minimum_viable: overrides.lodMinimumViable ?? workflowStore.lodMinimumViablePrefs ?? {}
  }

  if (Object.prototype.hasOwnProperty.call(overrides, 'submissionId')) {
    payload.submission_id = overrides.submissionId ?? null
  }

  if (Object.prototype.hasOwnProperty.call(overrides, 'pipelineRunId')) {
    payload.pipeline_run_id = overrides.pipelineRunId ?? null
  }

  return fileService.updateWorkflowState(workflowStore.sessionId, payload)
}

export const buildWorkflowResumeLocation = (sessionId, workflowHint = {}, fallbackPath = '/workflow/upload') => {
  const query = {}
  const normalizedSessionId = String(sessionId || '').trim()
  if (normalizedSessionId) {
    query.sessionId = normalizedSessionId
  }

  const resumeMode = String(workflowHint?.requires_msf_repair ? 'repair' : 'workflow').trim()
  if (resumeMode) {
    query.resume = resumeMode
  }

  if (workflowHint?.pipeline_run_id) {
    query.runId = String(workflowHint.pipeline_run_id)
  }

  if (workflowHint?.submission_id) {
    query.submissionId = String(workflowHint.submission_id)
  }

  return {
    path: workflowHint?.resume_route || fallbackPath,
    query
  }
}

export const shouldRestoreWorkflowContext = (
  workflowStore,
  sessionId,
  {
    force = false,
    requireUploadedFiles = false,
    requireSelectedFiles = false,
    requireSubmissionMetadata = false,
    requireSelectedPipeline = false,
    requireBatchMetadata = false,
    requireMsfPath = false
  } = {}
) => {
  const parsedSessionId = Number.parseInt(sessionId, 10)
  if (!Number.isInteger(parsedSessionId) || parsedSessionId <= 0) {
    return false
  }

  if (force) return true
  if (!workflowStore.sessionId || workflowStore.sessionId !== parsedSessionId) return true
  if (requireUploadedFiles && (!Array.isArray(workflowStore.uploadedFiles) || workflowStore.uploadedFiles.length === 0)) return true
  if (requireSelectedFiles && (!Array.isArray(workflowStore.selectedFiles) || workflowStore.selectedFiles.length === 0)) return true
  if (requireSubmissionMetadata && !hasObjectKeys(workflowStore.submissionMetadata)) return true
  if (requireSelectedPipeline && !workflowStore.selectedPipeline?.identifier && !workflowStore.selectedPipeline?.id) return true
  if (requireBatchMetadata && workflowStore.isBatchMode && !hasObjectKeys(workflowStore.fileMetadataMap)) return true
  if (requireMsfPath && !workflowStore.msfPath) return true
  return false
}

export const restoreWorkflowContext = async (
  workflowStore,
  sessionId,
  { includeNodes = true, includeDraft = true } = {}
) => {
  const parsedSessionId = Number.parseInt(sessionId, 10)
  if (!Number.isInteger(parsedSessionId) || parsedSessionId <= 0) {
    throw new Error('Invalid session ID for workflow restoration.')
  }

  const requests = [
    fileService.getWorkflowState(parsedSessionId, { suppressGlobalError: true })
  ]

  if (includeNodes) {
    requests.push(fileService.getNodes(parsedSessionId, { suppressGlobalError: true }))
  }

  const [stateResponse, nodesResponse] = await Promise.all(requests)
  const statePayload = stateResponse?.data || {}
  const workflowState = statePayload.state || {}
  const nodes = nodesResponse?.data?.nodes || []

  workflowStore.setSessionId(parsedSessionId)
  workflowStore.setBatchMode(workflowState.is_batch_mode === true)
  workflowStore.goToStep(
    Number.isInteger(workflowState.current_step)
      ? workflowState.current_step
      : (WORKFLOW_PHASE_TO_STEP[workflowState.phase] || 1)
  )

  if (includeNodes) {
    workflowStore.setUploadedFiles(nodes)
    if (Array.isArray(workflowState.selected_file_keys) && workflowState.selected_file_keys.length > 0) {
      workflowStore.setSelectedFiles(selectNodesByKeys(nodes, workflowState.selected_file_keys))
    } else {
      workflowStore.setSelectedFiles([])
    }
  }

  const selectedPipeline = workflowState.selected_pipeline
  if (selectedPipeline?.identifier) {
    workflowStore.setSelectedPipeline({
      id: selectedPipeline.identifier,
      identifier: selectedPipeline.identifier,
      name: selectedPipeline.name || selectedPipeline.identifier,
      description: selectedPipeline.description || ''
    })
  }

  if (statePayload.msf_profile && typeof statePayload.msf_profile === 'object') {
    workflowStore.setMsfProfile(statePayload.msf_profile)
    workflowStore.setMsfParseOptions(statePayload.msf_profile.parse_options || {})
  }

  if (workflowState.msf_path || statePayload.msf_profile?.source_file_path || statePayload.msf_profile?.file_path) {
    workflowStore.setMsfPath(
      workflowState.msf_path
        || statePayload.msf_profile?.source_file_path
        || statePayload.msf_profile?.file_path
    )
  }

  workflowStore.setMsfMapping(workflowState.msf_mapping || {})
  workflowStore.setFileMetadataMap(statePayload.file_metadata_map || {})
  workflowStore.setLodMinimumViablePrefs(workflowState.lod_minimum_viable || {})

  if (includeDraft && statePayload.draft_metadata && Object.keys(statePayload.draft_metadata).length > 0) {
    workflowStore.setSubmissionMetadata(statePayload.draft_metadata)
  }

  return {
    state: workflowState,
    nodes,
    draftMetadata: statePayload.draft_metadata || {},
    msfProfile: statePayload.msf_profile || {},
    fileMetadataMap: statePayload.file_metadata_map || {},
    workflowHint: statePayload.workflow_hint || {}
  }
}
