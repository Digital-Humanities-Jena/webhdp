import api from './api'

const datasetService = {
  listDatasets(params = {}) {
    return api.get('/datasets', { params })
  },

  getDatasetSummary(datasetKey, params = {}) {
    return api.get(`/datasets/${encodeURIComponent(datasetKey)}/summary`, { params })
  },

  getDatasetDuplicates(datasetKey, params = {}) {
    return api.get(`/datasets/${encodeURIComponent(datasetKey)}/duplicates`, { params })
  },

  getConflictReview(params = {}) {
    return api.get('/datasets/conflict-review', { params })
  },

  duplicateCheck(payload = {}) {
    return api.post('/datasets/duplicate-check', payload)
  },

  exportDataset(datasetKey, payload = {}) {
    return api.post(`/datasets/${encodeURIComponent(datasetKey)}/export`, payload)
  },
}

export default datasetService
