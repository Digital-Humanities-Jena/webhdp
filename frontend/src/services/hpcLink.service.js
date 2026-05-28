import api from './api'

const hpcLinkService = {
  getStatus(params = {}) {
    return api.get('/hpc-link/status', { params })
  },

  requestAllocation(payload) {
    return api.post('/hpc-link/allocations', payload)
  },

  getAllocation(allocationId) {
    return api.get(`/hpc-link/allocations/${encodeURIComponent(allocationId)}`)
  },

  preflightAllocation(allocationId, components = []) {
    return api.post(`/hpc-link/allocations/${encodeURIComponent(allocationId)}/preflight`, { components })
  },

  stageCloudFiles(allocationId, files = []) {
    return api.post(`/hpc-link/allocations/${encodeURIComponent(allocationId)}/stage/cloud`, { files })
  },

  stageCloudReferences(allocationId, files = []) {
    return api.post(`/hpc-link/allocations/${encodeURIComponent(allocationId)}/stage/cloud-references`, { files })
  },

  uploadZenodoDraft(allocationId, payload) {
    return api.post(`/hpc-link/allocations/${encodeURIComponent(allocationId)}/zenodo/upload-draft`, payload)
  },

  releaseAllocation(allocationId) {
    return api.post(`/hpc-link/allocations/${encodeURIComponent(allocationId)}/release`, {})
  }
}

export default hpcLinkService
