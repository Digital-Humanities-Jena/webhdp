import api from './api'

const toolsService = {
  async getContext() {
    return api.get('/tools/context')
  },

  async runPipelinePreflightLocal(payload) {
    return api.post('/tools/pipeline-preflight/local', payload)
  },

  async runMetadataNormalizerLocal(payload) {
    return api.post('/tools/metadata-normalizer/local', payload)
  },

  async runOutputPreviewLocal(payload) {
    return api.post('/tools/output-preview/local', payload)
  },

  async getHpcDiagnostics() {
    return api.get('/tools/hpc-diagnostics')
  },

  async validateHdpComponentInstall(payload) {
    return api.post('/tools/hdp-components/validate', payload)
  },

  async listHdpComponentCatalog(params = {}) {
    return api.get('/tools/hdp-components/catalog', { params, timeout: 30000 })
  },

  async getHdpComponentCatalogDiagnostics() {
    return api.get('/tools/hdp-components/catalog/diagnostics', { timeout: 15000, suppressGlobalError: true })
  },

  async installHdpComponent(payload) {
    return api.post('/tools/hdp-components/install', payload)
  },

  async listHdpComponentInstallations() {
    return api.get('/tools/hdp-components/installations')
  },

  async getHdpComponentInstallation(installationId) {
    return api.get(`/tools/hdp-components/installations/${encodeURIComponent(installationId)}`, { timeout: 15000, suppressGlobalError: true })
  },

  async testHdpComponentInstallation(installationId, payload = {}) {
    return api.post(`/tools/hdp-components/installations/${encodeURIComponent(installationId)}/test`, payload)
  },

  async getZenodoBatchOperationRecords(params = {}) {
    return api.get('/tools/zenodo-batch-operations/records', { params })
  },

  async launchZenodoCommunityOperation(payload) {
    return api.post('/tools/zenodo-batch-operations/community-operations', payload)
  },

  async getZenodoBatchOperationTask(taskId) {
    return api.get(`/tools/zenodo-batch-operations/tasks/${taskId}`, { suppressGlobalError: true })
  },

  async getZenodoBatchOperationHistory(params = {}) {
    return api.get('/tools/zenodo-batch-operations/history', { params })
  },

  async getZenodoAccountRetrievalContext() {
    return api.get('/tools/zenodo-account-retrieval/context')
  },

  async getZenodoAccountRetrievalCoverage(params = {}) {
    return api.get('/tools/zenodo-account-retrieval/coverage', { params })
  },

  async launchZenodoAccountRetrieval(payload) {
    return api.post('/tools/zenodo-account-retrieval/jobs', payload)
  },

  async preflightZenodoAccountRetrieval(payload) {
    return api.post('/tools/zenodo-account-retrieval/preflight', payload)
  },

  async listZenodoAccountRetrievalJobs(params = {}) {
    return api.get('/tools/zenodo-account-retrieval/jobs', { params })
  },

  async getZenodoAccountRetrievalJob(retrievalId) {
    return api.get(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}`, { suppressGlobalError: true })
  },

  async getZenodoAccountRetrievalDiagnostics(retrievalId) {
    return api.get(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/diagnostics`, { suppressGlobalError: true })
  },

  async pauseZenodoAccountRetrieval(retrievalId) {
    return api.post(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/pause`, {})
  },

  async resumeZenodoAccountRetrieval(retrievalId) {
    return api.post(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/resume`, {})
  },

  async cancelZenodoAccountRetrieval(retrievalId) {
    return api.post(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/cancel`, {})
  },

  async deleteZenodoAccountRetrieval(retrievalId) {
    return api.delete(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}`)
  },

  async searchZenodoAccountRetrievalRecords(retrievalId, params = {}) {
    return api.get(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/records`, { params })
  },

  async runZenodoAccountRetrievalDetector(retrievalId, params = {}) {
    return api.get(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/detectors`, { params })
  },

  async compactZenodoAccountRetrieval(retrievalId, payload = {}) {
    return api.post(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/compact`, payload)
  },

  async deleteZenodoAccountRetrievalCompactedShards(retrievalId) {
    return api.delete(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/compacted-shards`)
  },

  async updateZenodoAccountRetrievalRetention(retrievalId, payload = {}) {
    return api.patch(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/retention`, payload)
  },

  async updateZenodoAccountRetrievalSchedule(retrievalId, payload = {}) {
    return api.patch(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/schedule`, payload)
  },

  async runZenodoAccountRetrievalScheduleNow(retrievalId) {
    return api.post(`/tools/zenodo-account-retrieval/jobs/${encodeURIComponent(retrievalId)}/schedule/run-now`, {})
  },

  async getZenodoOaiHarvestContext() {
    return api.get('/tools/zenodo-oai-harvest/context')
  },

  async preflightZenodoOaiHarvest(payload) {
    return api.post('/tools/zenodo-oai-harvest/preflight', payload)
  },

  async launchZenodoOaiHarvest(payload) {
    return api.post('/tools/zenodo-oai-harvest/jobs', payload)
  },

  async listZenodoOaiHarvestJobs(params = {}) {
    return api.get('/tools/zenodo-oai-harvest/jobs', { params })
  },

  async getZenodoOaiHarvestJob(harvestId) {
    return api.get(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}`, { suppressGlobalError: true })
  },

  async pauseZenodoOaiHarvest(harvestId) {
    return api.post(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}/pause`, {})
  },

  async resumeZenodoOaiHarvest(harvestId) {
    return api.post(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}/resume`, {})
  },

  async cancelZenodoOaiHarvest(harvestId) {
    return api.post(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}/cancel`, {})
  },

  async deleteZenodoOaiHarvest(harvestId) {
    return api.delete(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}`)
  },

  async searchZenodoOaiHarvestRecords(harvestId, params = {}) {
    return api.get(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}/records`, { params })
  },

  async runZenodoOaiHarvestDetector(harvestId, params = {}) {
    return api.get(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}/detectors`, { params })
  },

  async exportZenodoOaiHarvest(harvestId, format) {
    return api.get(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}/export/${encodeURIComponent(format)}`, {
      responseType: 'blob',
    })
  },

  async compactZenodoOaiHarvest(harvestId, payload = {}) {
    return api.post(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}/compact`, payload)
  },

  async updateZenodoOaiHarvestSchedule(harvestId, payload = {}) {
    return api.patch(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}/schedule`, payload)
  },

  async runZenodoOaiHarvestScheduleNow(harvestId) {
    return api.post(`/tools/zenodo-oai-harvest/jobs/${encodeURIComponent(harvestId)}/schedule/run-now`, {})
  },

  async getCommunityMigrationContext() {
    return api.get('/tools/community-migrations/context')
  },

  async planCommunityMigration(payload) {
    return api.post('/tools/community-migrations/plan', payload)
  },

  async launchCommunityMigration(payload) {
    return api.post('/tools/community-migrations/jobs', payload)
  },

  async listCommunityMigrationJobs(params = {}) {
    return api.get('/tools/community-migrations/jobs', { params })
  },

  async getCommunityMigrationJob(jobId, params = {}) {
    return api.get(`/tools/community-migrations/jobs/${encodeURIComponent(jobId)}`, { params, suppressGlobalError: true })
  },

  async resumeCommunityMigration(jobId) {
    return api.post(`/tools/community-migrations/jobs/${encodeURIComponent(jobId)}/resume`, {})
  },

  async cancelCommunityMigration(jobId) {
    return api.post(`/tools/community-migrations/jobs/${encodeURIComponent(jobId)}/cancel`, {})
  },

  async getCommunityModerationRequests(params = {}) {
    return api.get('/tools/community-moderation/requests', { params })
  },

  async getCommunityModerationSummary(params = {}) {
    return api.get('/tools/community-moderation/summary', { params })
  },

  async launchCommunityModerationBatch(payload) {
    return api.post('/tools/community-moderation/actions', payload)
  },

  async getCommunityModerationTask(taskId) {
    return api.get(`/tools/community-moderation/tasks/${taskId}`, { suppressGlobalError: true })
  },

  async getCommunityModerationHistory(params = {}) {
    return api.get('/tools/community-moderation/history', { params })
  },

  async planCommunityModerationSweep(payload) {
    return api.post('/tools/community-moderation/sweeps/plan', payload)
  },

  async launchCommunityModerationSweep(payload) {
    return api.post('/tools/community-moderation/sweeps', payload)
  },

  async listCommunityModerationSweeps(params = {}) {
    return api.get('/tools/community-moderation/sweeps', { params })
  },

  async getCommunityModerationSweep(jobId, params = {}) {
    return api.get(`/tools/community-moderation/sweeps/${encodeURIComponent(jobId)}`, { params, suppressGlobalError: true })
  },

  async cancelCommunityModerationSweep(jobId) {
    return api.post(`/tools/community-moderation/sweeps/${encodeURIComponent(jobId)}/cancel`, {})
  },

  async exportCommunityModerationSweep(jobId, format = 'json') {
    return api.get(`/tools/community-moderation/sweeps/${encodeURIComponent(jobId)}/export`, {
      params: { format },
      responseType: format === 'csv' ? 'blob' : 'json',
      suppressGlobalError: true,
    })
  },

  async analyzeSessionCleanup(payload) {
    return api.post('/tools/session-cleanup/analyze', payload)
  },

  async executeSessionCleanup(payload) {
    return api.post('/tools/session-cleanup/execute', payload)
  }
}

export default toolsService
