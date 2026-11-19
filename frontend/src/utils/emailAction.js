export function readEmailActionToken(hash = '') {
  const value = new URLSearchParams(hash.slice(1)).get('token')
  return value && /^[A-Za-z0-9_-]{32,128}$/.test(value) ? value : ''
}

export const institutionInvitationPath = '/institution-invitation'
export const invitationStorageKey = 'webhdp:institution-invitation'
export const verificationStorageKey = 'webhdp:email-verification'

export function getEmailActionToken(key) {
  try {
    return sessionStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

export function setEmailActionToken(key, token) {
  try {
    if (token) sessionStorage.setItem(key, token)
    else sessionStorage.removeItem(key)
  } catch {
    // The original email link can be opened again if browser storage is unavailable.
  }
}

export function identityActionError(error, fallback) {
  const message = error?.error?.message || error?.error
  return typeof message === 'string' && message ? message : fallback
}
