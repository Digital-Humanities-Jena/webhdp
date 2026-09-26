import api from './api'

export default {
  login(email, password) {
    return api.post('/auth/login', { email, password })
  },

  verifyLoginCode(mfaToken, code) {
    return api.post('/auth/login/verify-code', { mfa_token: mfaToken, code })
  },

  verifyRecoveryCode(mfaToken, recoveryCode) {
    return api.post('/auth/login/verify-recovery-code', { mfa_token: mfaToken, recovery_code: recoveryCode })
  },

  resendLoginCode(mfaToken) {
    return api.post('/auth/login/resend-code', { mfa_token: mfaToken })
  },

  register(email, password) {
    return api.post('/auth/register', { email, password })
  },

  logout() {
    return api.post('/auth/logout')
  },

  getCurrentUser() {
    return api.get('/auth/me')
  },

  updateCurrentUser(payload) {
    return api.put('/auth/me', payload)
  },

  updateOnboarding(action) {
    return api.put('/auth/me/onboarding', { action })
  },

  updatePassword(currentPassword, newPassword, confirmNewPassword) {
    return api.put('/auth/me/password', {
      current_password: currentPassword,
      new_password: newPassword,
      confirm_new_password: confirmNewPassword
    })
  },

  configureMfa(payload) {
    return api.post('/auth/me/mfa', payload)
  },

  verifyMfaEnrollment(payload) {
    return api.post('/auth/me/mfa/verify', payload)
  },

  getRecoveryCodes() {
    return api.get('/auth/me/recovery-codes')
  },

  regenerateRecoveryCodes(currentPassword) {
    return api.post('/auth/me/recovery-codes', { current_password: currentPassword })
  },

  getZenodoCredential(environment) {
    return api.get(`/auth/me/zenodo-credentials/${environment}`)
  },

  saveZenodoCredential(environment, token) {
    return api.put(`/auth/me/zenodo-credentials/${environment}`, { token })
  },

  deleteZenodoCredential(environment) {
    return api.delete(`/auth/me/zenodo-credentials/${environment}`)
  },

  validateZenodoCredential(environment) {
    return api.post(`/auth/me/zenodo-credentials/${environment}/validate`, {})
  },

  listZenodoCredentials() {
    return api.get('/auth/me/zenodo-credentials')
  },

  createZenodoCredential(payload) {
    return api.post('/auth/me/zenodo-credentials', payload)
  },

  renameZenodoCredential(credentialId, name) {
    return api.patch(`/auth/me/zenodo-credentials/${credentialId}`, { name })
  },

  deleteZenodoCredentialById(credentialId) {
    return api.delete(`/auth/me/zenodo-credentials/${credentialId}`)
  },

  validateZenodoCredentialById(credentialId) {
    return api.post(`/auth/me/zenodo-credentials/${credentialId}/validate`, {})
  },

  shareZenodoCredential(credentialId, recipientEmail) {
    return api.post(`/auth/me/zenodo-credentials/${credentialId}/share`, { recipient_email: recipientEmail })
  },

  setActiveZenodoCredential(environment, credentialId) {
    return api.put(`/auth/me/zenodo-active-credentials/${environment}`, { credential_id: credentialId })
  },

  acceptZenodoCredentialShare(shareId) {
    return api.post(`/auth/me/zenodo-credential-shares/${shareId}/accept`, {})
  },

  declineZenodoCredentialShare(shareId) {
    return api.post(`/auth/me/zenodo-credential-shares/${shareId}/decline`, {})
  },

  revokeZenodoCredentialShare(shareId) {
    return api.delete(`/auth/me/zenodo-credential-shares/${shareId}`)
  }
}
