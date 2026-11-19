import api from './api'

const hpcLinkService = {
  getStatus(params = {}, options = {}) {
    return api.get('/hpc-link/status', { ...options, params })
  },

  listReservations(purpose) {
    return api.get('/hpc-link/reservations', { params: { purpose }, suppressGlobalError: true })
  },

  claimReservation(reservationId, payload) {
    return api.post(`/hpc-link/reservations/${encodeURIComponent(reservationId)}/claim`, payload, { suppressGlobalError: true })
  },

  requestAllocation(payload) {
    return api.post('/hpc-link/allocations', payload)
  },

  listMyAllocations(options = {}) {
    return api.get('/hpc-link/allocations', { ...options, suppressGlobalError: true })
  },

  getAllocation(allocationId, options = {}) {
    return api.get(`/hpc-link/allocations/${encodeURIComponent(allocationId)}`, options)
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

  releaseAllocation(allocationId, options = {}) {
    return api.post(`/hpc-link/allocations/${encodeURIComponent(allocationId)}/release`, {}, options)
  }
}

export default hpcLinkService
