import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import authService from '@/services/auth.service'
import { clearBrowserDrafts } from '@/utils/browserDrafts'

function parseCapabilitiesValue(value) {
  if (Array.isArray(value)) {
    return value
  }
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }
  return []
}

function parseGroupsValue(value) {
  if (Array.isArray(value)) {
    return value
  }
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }
  return []
}

export function getNormalizedCapabilities(rawUser) {
  const merged = [
    ...parseCapabilitiesValue(rawUser?.capabilities),
    ...parseCapabilitiesValue(rawUser?.capabilities_json),
  ]
    .map((entry) => String(entry || '').trim())
    .filter(Boolean)

  return Array.from(new Set(merged))
}

export function getNormalizedGroups(rawUser) {
  const groups = parseGroupsValue(rawUser?.groups)
    .map((entry) => String(entry || '').trim())
    .filter(Boolean)
  return Array.from(new Set(groups))
}

export function normalizeAuthUser(rawUser) {
  if (!rawUser || typeof rawUser !== 'object') {
    return rawUser
  }
  const capabilities = getNormalizedCapabilities(rawUser)
  const groups = getNormalizedGroups(rawUser)
  return {
    ...rawUser,
    capabilities,
    capabilities_json: capabilities,
    groups,
  }
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)

  // Clean up potential bad state from previous bugs
  const legacyToken = localStorage.getItem('token')
  if (legacyToken) {
    localStorage.removeItem('token')
  }
  const storedToken = sessionStorage.getItem('token')
  const isValidToken = storedToken && storedToken !== 'undefined' && storedToken !== 'null'
  const token = ref(isValidToken ? storedToken : null)

  // If we found a bad token, clean it up immediately
  if (storedToken && !isValidToken) {
    sessionStorage.removeItem('token')
  }

  const isAuthenticated = computed(() => !!token.value)
  const capabilities = computed(() => getNormalizedCapabilities(user.value))
  const groups = computed(() => getNormalizedGroups(user.value))
  const institutions = computed(() => Array.isArray(user.value?.institutions) ? user.value.institutions : [])
  const memberships = computed(() => Array.isArray(user.value?.memberships) ? user.value.memberships : [])

  function setUser(nextUser) {
    user.value = normalizeAuthUser(nextUser)
  }

  function hasCapability(capability) {
    const normalizedCapability = String(capability || '').trim().toLowerCase()
    if (!normalizedCapability) {
      return false
    }
    return capabilities.value.some((entry) => entry.toLowerCase() === normalizedCapability)
  }

  function hasGroup(group) {
    const normalizedGroup = String(group || '').trim().toLowerCase()
    if (!normalizedGroup) {
      return false
    }
    return groups.value.some((entry) => entry.toLowerCase() === normalizedGroup)
  }

  async function login(email, password) {
    try {
      const response = await authService.login(email, password)

      if (response.data?.mfa_required) {
        setUser(null)
        token.value = null
        sessionStorage.removeItem('token')
        localStorage.removeItem('token')
        return response
      }

      setUser(response.data.user)

      if (response.data.access_token) {
        token.value = response.data.access_token
        sessionStorage.setItem('token', token.value)
        console.log('Login successful - Token stored')
      } else {
        console.warn('Login successful but no token received')
      }

      return response
    } catch (error) {
      console.error('Login failed:', error)
      throw error
    }
  }

  async function verifyLoginCode(mfaToken, code) {
    try {
      const response = await authService.verifyLoginCode(mfaToken, code)
      setUser(response.data.user)

      if (response.data.access_token) {
        token.value = response.data.access_token
        sessionStorage.setItem('token', token.value)
        console.log('MFA verification successful - Token stored')
      } else {
        console.warn('MFA verification successful but no token received')
      }

      return response
    } catch (error) {
      console.error('MFA verification failed:', error)
      throw error
    }
  }

  async function verifyRecoveryCode(mfaToken, recoveryCode) {
    try {
      const response = await authService.verifyRecoveryCode(mfaToken, recoveryCode)
      setUser(response.data.user)

      if (response.data.access_token) {
        token.value = response.data.access_token
        sessionStorage.setItem('token', token.value)
        console.log('Recovery code verification successful - Token stored')
      } else {
        console.warn('Recovery code verification successful but no token received')
      }

      return response
    } catch (error) {
      console.error('Recovery code verification failed:', error)
      throw error
    }
  }

  async function resendLoginCode(mfaToken) {
    return authService.resendLoginCode(mfaToken)
  }

  async function register(email, password) {
    try {
      const response = await authService.register(email, password)
      // Do not log in immediately after registration as email verification is required
      // user.value = response.data.user
      // token.value = response.data.access_token
      console.log('Registration successful - Verification required')
      return response
    } catch (error) {
      console.error('Registration failed:', error)
      throw error
    }
  }

  function logout({ preserveDrafts = false } = {}) {
    if (!preserveDrafts) clearBrowserDrafts()
    setUser(null)
    token.value = null
    sessionStorage.removeItem('token')
    localStorage.removeItem('token')
    console.log('Logged out - Token removed')
  }

  async function fetchCurrentUser() {
    if (token.value) {
      try {
        const response = await authService.getCurrentUser()
        setUser(response.data.user)
        console.log('User fetched:', user.value?.email)
        return response
      } catch (error) {
        console.error('Failed to fetch user - clearing invalid token:', error)
        // Clear invalid token
        logout({ preserveDrafts: true })
        throw error
      }
    }
  }

  async function updateCurrentUser(payload) {
    const response = await authService.updateCurrentUser(payload)
    setUser(response.data.user)
    return response
  }

  async function updateOnboarding(action) {
    const response = await authService.updateOnboarding(action)
    setUser(response.data.user)
    return response
  }

  async function updatePassword(currentPassword, newPassword, confirmNewPassword) {
    const response = await authService.updatePassword(currentPassword, newPassword, confirmNewPassword)
    if (response.data?.user) {
      setUser(response.data.user)
    }
    if (response.data?.access_token) {
      token.value = response.data.access_token
      sessionStorage.setItem('token', token.value)
    }
    return response
  }

  return {
    user,
    token,
    isAuthenticated,
    capabilities,
    groups,
    institutions,
    memberships,
    login,
    verifyLoginCode,
    verifyRecoveryCode,
    resendLoginCode,
    register,
    logout,
    fetchCurrentUser,
    updateCurrentUser,
    updateOnboarding,
    updatePassword,
    setUser,
    hasCapability,
    hasGroup
  }
})
