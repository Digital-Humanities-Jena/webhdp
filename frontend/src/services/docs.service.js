import api from './api'

const docsService = {
  listDocuments() {
    return api.get('/docs/index', { suppressGlobalError: true })
  },

  getDocument(docId) {
    return api.get(`/docs/content/${encodeURIComponent(docId)}`, { suppressGlobalError: true })
  }
}

export default docsService
