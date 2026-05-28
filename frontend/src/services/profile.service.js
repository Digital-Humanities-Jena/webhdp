import api from './api'

export default {
  getUserProfile(identifier) {
    return api.get(`/profiles/users/${encodeURIComponent(identifier)}`)
  },

  getInstitutionProfile(identifier) {
    return api.get(`/profiles/institutions/${encodeURIComponent(identifier)}`)
  },
}
