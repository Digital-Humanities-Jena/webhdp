import api from './api'

const developerService = {
  getStatus() {
    return api.get('/developer/status', { suppressGlobalError: true })
  }
}

export default developerService
