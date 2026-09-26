import { apiV2 } from './api'

// Load pipeline ID from environment variable for default use across the app.
// Example: VITE_PIPELINE_ID=glb_simple in your .env file
const DEFAULT_PIPELINE_ID = import.meta.env.VITE_PIPELINE_ID || 'render'

function requestV2(config) {
  return apiV2(config)
}

export default {
  // List all available pipelines (optionally filter by status)
  listPipelines(status = null) {
    const params = status ? { status } : {}
    return requestV2({ method: 'get', url: '/pipelines', params })
  },

  // Retrieve details for a specific pipeline
  getPipeline(identifier = DEFAULT_PIPELINE_ID) {
    return requestV2({ method: 'get', url: `/pipelines/${identifier}` })
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
        preflight_token: options.preflightToken
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

  getPlaygroundRun(runId) {
    return requestV2({
      method: 'get',
      url: `/playground/runs/${runId}`
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
        preflight_token: options.preflightToken
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
        preflight_token: options.preflightToken
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
