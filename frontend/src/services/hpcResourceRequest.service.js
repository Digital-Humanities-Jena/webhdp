import api from './api'

const hpcResourceRequestService = {
  getMyStatus() {
    return api.get('/hpc-resource-requests/me')
  },

  submitRequest(payload) {
    return api.post('/hpc-resource-requests', payload)
  }
}

export default hpcResourceRequestService
