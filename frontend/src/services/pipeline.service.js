import { apiV2 } from './api'
import { readinessStream } from '@/utils/readinessStream'

// Load pipeline ID from environment variable for default use across the app.
// Example: VITE_PIPELINE_ID=glb_simple in your .env file
const DEFAULT_PIPELINE_ID = import.meta.env.VITE_PIPELINE_ID || 'render'

function requestV2(config) {
  return apiV2(config)
}

export default {
  // List all available pipelines (optionally filter by status)
  listPipelines(status = null, { authoring = false } = {}) {
    const params = status ? { status } : {}
    if (authoring) params.scope = 'constructor'
    return requestV2({ method: 'get', url: '/pipelines', params })
  },

  // Retrieve details for a specific pipeline
  getPipeline(identifier = DEFAULT_PIPELINE_ID, { authoring = false } = {}) {
    const params = authoring ? { scope: 'constructor' } : undefined
    return requestV2({ method: 'get', url: `/pipelines/${identifier}`, params })
  },

  listComponents(options = {}) {
    const params = {}
    if (options.playgroundOnly) {
      params.playground_only = true
    }
    return requestV2({ method: 'get', url: '/components', params })
  },

  validateComponentManifest(componentPath) {
    return requestV2({
      method: 'post',
      url: '/components/validate',
      data: { component_path: componentPath }
    })
  },

  importComponent(componentPath) {
    return requestV2({
      method: 'post',
      url: '/components/import',
      data: { component_path: componentPath }
    })
  },

  validatePipelineConfig(config) {
    return requestV2({
      method: 'post',
      url: '/pipelines/validate',
      data: config
    })
  },

  createPipelineVersion(identifier = DEFAULT_PIPELINE_ID, config, options = {}) {
    return requestV2({
      method: 'post',
      url: `/pipelines/${identifier}/versions`,
      data: {
        ...config,
        activate: options.activate !== false,
        request_id: options.requestId
      }
    })
  },

  getPipelineConstructorSupport() {
    return requestV2({
      method: 'get',
      url: '/pipelines/constructor-support'
    })
  },

  preflightPipelineConstructor(payload) {
    return requestV2({
      method: 'post',
      url: '/pipelines/constructor/preflight',
      data: payload
    })
  },

  async checkSubmissionReadiness(identifier, payload, options = {}) {
    const stream = readinessStream(options.onProgress)
    let streamError
    const response = await requestV2({
      method: 'post', url: `/pipelines/${identifier}/readiness?stream=1`, data: payload,
      timeout: 600000, suppressGlobalError: true, responseType: 'text', signal: options.signal,
      onDownloadProgress: event => {
        const text = event.event?.target?.responseText
        if (text && !streamError) {
          try { stream.consume(text) } catch (error) { streamError = error }
        }
      },
    })
    if (streamError) throw streamError
    return stream.consume(response, true)
  },

  // Execute pipeline on existing record IDs for a specific session.
  executePipeline(
    sessionId,
    identifier = DEFAULT_PIPELINE_ID,
    recordIds = [],
    isSandbox = true,
    options = {}
  ) {
    return requestV2({
      method: 'post',
      url: `/pipelines/${identifier}/execute`,
      data: {
        session_id: sessionId,
        record_ids: recordIds,
        is_sandbox: isSandbox,
        async_execution: options.asyncExecution === true,
        abort_on_critical_error: options.abortOnCriticalError === true,
        request_id: options.requestId,
        expected_version: options.expectedVersion,
        preflight_token: options.preflightToken,
        readiness_token: options.readinessToken,
        resume_from_run_id: options.resumeFromRunId
      }
    })
  },

  executePlayground(payload, requestOptions = {}) {
    return requestV2({
      method: 'post',
      url: '/playground/execute',
      data: payload,
      ...requestOptions
    })
  },

  getPlaygroundRun(runId, requestOptions = {}) {
    return requestV2({
      method: 'get',
      url: `/playground/runs/${runId}`,
      timeout: 15000,
      suppressGlobalError: true,
      ...requestOptions
    })
  },

  cancelPlaygroundRun(runId) {
    return requestV2({ method: 'post', url: `/playground/runs/${runId}/cancel`, suppressGlobalError: true })
  },

  cancelPipelineRun(runId) {
    return requestV2({ method: 'post', url: `/runs/${runId}/cancel`, suppressGlobalError: true })
  },

  downloadPipelineArtifact(runId, artifactId) {
    return requestV2({
      method: 'get',
      url: `/runs/${encodeURIComponent(runId)}/artifacts/${artifactId}`,
      responseType: 'blob',
      suppressGlobalError: true
    })
  },

  downloadPlaygroundArtifact(runId, artifactIndex, requestOptions = {}) {
    return requestV2({
      method: 'get',
      url: `/playground/runs/${runId}/artifacts/${artifactIndex}`,
      responseType: 'blob',
      ...requestOptions
    })
  },

  getPlaygroundSessionFile(sessionId, path, requestOptions = {}) {
    return requestV2({
      method: 'get',
      url: `/playground/sessions/${sessionId}/file`,
      params: { path },
      responseType: 'blob',
      ...requestOptions
    })
  },

  getPipelineRun(runId) {
    return requestV2({
      method: 'get',
      url: `/runs/${runId}`,
      timeout: 15000,
      suppressGlobalError: true
    })
  },

  getPipelineRecovery(runId) {
    return requestV2({ method: 'get', url: `/runs/${runId}/recovery`, suppressGlobalError: true })
  },

  // Execute pipeline on local files through the native v2 execution surface.
  executePipelineOnFiles(
    sessionId,
    localFilePaths,
    isSandbox = true,
    identifier = DEFAULT_PIPELINE_ID,
    options = {}
  ) {
    return requestV2({
      method: 'post',
      url: `/pipelines/${identifier}/execute`,
      data: {
        session_id: sessionId,
        local_file_paths: localFilePaths,
        is_sandbox: isSandbox,
        async_execution: options.asyncExecution === true,
        abort_on_critical_error: options.abortOnCriticalError === true,
        request_id: options.requestId,
        expected_version: options.expectedVersion,
        preflight_token: options.preflightToken,
        readiness_token: options.readinessToken
      }
    })
  },

  executePipelineWithPlan(
    sessionId,
    identifier = DEFAULT_PIPELINE_ID,
    executionItems = [],
    isSandbox = true,
    options = {}
  ) {
    return requestV2({
      method: 'post',
      url: `/pipelines/${identifier}/execute`,
      data: {
        session_id: sessionId,
        execution_items: executionItems,
        is_sandbox: isSandbox,
        async_execution: options.asyncExecution === true,
        abort_on_critical_error: options.abortOnCriticalError === true,
        request_id: options.requestId,
        expected_version: options.expectedVersion,
        preflight_token: options.preflightToken,
        readiness_token: options.readinessToken
      }
    })
  },

  // Retrieve execution or processing status
  getExecutionStatus(executionUuid) {
    return requestV2({
      method: 'get',
      url: `/runs/${executionUuid}`
    })
  }
}
