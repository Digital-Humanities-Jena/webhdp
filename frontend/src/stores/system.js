import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/services/api'

const SETUP_TOKEN_STORAGE_KEY = 'setup_token'

function tokenFromCurrentUrl() {
  if (typeof window === 'undefined') return ''
  return new URLSearchParams(window.location.search).get('setup_token')?.trim() || ''
}

export const useSystemStore = defineStore('system', () => {
  const coreOnly = ref(false)
  const isInitialized = ref(true)
  const statusChecked = ref(false)
  const loading = ref(true)
  const setupToken = ref(
    typeof window !== 'undefined'
      ? sessionStorage.getItem(SETUP_TOKEN_STORAGE_KEY) || ''
      : ''
  )

  function captureSetupToken() {
    const token = tokenFromCurrentUrl()
    if (!token) return setupToken.value
    setupToken.value = token
    sessionStorage.setItem(SETUP_TOKEN_STORAGE_KEY, token)
    return token
  }

  function setupRequestConfig() {
    const token = captureSetupToken()
    if (!token) return undefined
    return {
      headers: {
        'X-Setup-Token': token,
      },
    }
  }

  function clearSetupToken() {
    setupToken.value = ''
    if (typeof window !== 'undefined') {
      sessionStorage.removeItem(SETUP_TOKEN_STORAGE_KEY)
    }
  }

  async function checkStatus() {
    if (statusChecked.value) return
    try {
      const response = await api.get('/setup/status')
      coreOnly.value = Boolean(response.data.core_only)
      isInitialized.value = response.data.initialized
      statusChecked.value = true
    } catch (error) {
      console.error('Failed to check system status:', error)
      isInitialized.value = true
    } finally {
      loading.value = false
    }
  }

  async function checkHealth() {
    return api.post('/setup/check', undefined, setupRequestConfig())
  }

  async function testRender() {
    return api.post('/setup/test-render', undefined, setupRequestConfig())
  }

  async function verifyZenodo(keys) {
    return api.post('/setup/verify-zenodo', {
      api_key: keys.apiKey,
      sandbox_key: keys.sandboxKey
    }, setupRequestConfig())
  }

  async function createAdmin(credentials) {
    return api.post('/setup/create-admin', credentials, setupRequestConfig())
  }

  async function completeSetup() {
    await api.post('/setup/complete', undefined, setupRequestConfig())
    isInitialized.value = true
    clearSetupToken()
  }

  async function resetSystem() {
    await api.post('/setup/reset')
    isInitialized.value = false
  }

  return {
    coreOnly,
    isInitialized,
    loading,
    setupToken,
    captureSetupToken,
    clearSetupToken,
    checkStatus,
    checkHealth,
    testRender,
    verifyZenodo,
    createAdmin,
    completeSetup,
    resetSystem
  }
})
