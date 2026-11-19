import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { activateTestPinia } from './helpers/pinia.mjs'

const mocked = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
  },
  authService: {
    getCurrentUser: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({ default: mocked.api }))
vi.mock('@/services/auth.service', () => ({ default: mocked.authService }))

import router from '../src/router/index.js'
import { useAuthStore } from '../src/stores/auth.js'
import { useSystemStore } from '../src/stores/system.js'

async function navigateTo(path) {
  await router.push(path)
  await flushPromises()
  return router.currentRoute.value
}

describe('router pipeline author guard', () => {
  beforeEach(async () => {
    mocked.api.get.mockReset()
    mocked.authService.getCurrentUser.mockReset()
    mocked.api.get.mockImplementation((url) => {
      if (url === '/setup/status') {
        return Promise.resolve({ data: { initialized: true } })
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    activateTestPinia()

    const authStore = useAuthStore()
    authStore.logout()

    await navigateTo('/login')
  })

  it('redirects unauthenticated users away from protected routes', async () => {
    const route = await navigateTo('/dashboard')

    expect(route.fullPath).toBe('/login')
  })

  it('serves the landing page at the root route for unauthenticated visitors', async () => {
    mocked.api.get.mockReset()

    const route = await navigateTo('/')

    expect(route.name).toBe('Landing')
    expect(mocked.api.get).not.toHaveBeenCalled()
  })

  it('redirects authenticated root-route visits to the dashboard', async () => {
    const authStore = useAuthStore()
    authStore.token = 'token'
    authStore.setUser({
      id: 8,
      role: 'user',
    })

    const route = await navigateTo('/')

    expect(route.fullPath).toBe('/dashboard')
  })

  it('redirects onboarding-required users to first steps from protected routes', async () => {
    const authStore = useAuthStore()
    authStore.token = 'token'
    authStore.setUser({
      id: 18,
      role: 'user',
      onboarding_required: true,
    })

    const route = await navigateTo('/workflow/upload')

    expect(route.fullPath).toBe('/onboarding')
  })

  it('keeps first-visit links through sign-in and allows setup and practice before completing onboarding', async () => {
    expect((await navigateTo('/onboarding?tour=1')).query.redirect).toBe('/onboarding?tour=1')
    expect((await navigateTo('/tutorial/3d')).query.redirect).toBe('/tutorial/3d')
    expect((await navigateTo('/account/setup')).query.redirect).toBe('/account/setup')

    const authStore = useAuthStore()
    authStore.token = 'token'
    authStore.setUser({ id: 18, role: 'user', onboarding_required: true })

    expect((await navigateTo('/tutorial/3d')).name).toBe('ModelPublicationTutorial')
    expect((await navigateTo('/account/setup')).name).toBe('AccountSetup')
    expect(authStore.user.onboarding_required).toBe(true)
    expect((await navigateTo('/dashboard')).name).toBe('Onboarding')
  })

  it('requires authentication for internal profile routes', async () => {
    const route = await navigateTo('/profiles/users/ada-curator')

    expect(route.fullPath).toBe('/login')
  })

  it('redirects to setup when the system is not initialized', async () => {
    mocked.api.get.mockImplementation((url) => {
      if (url === '/setup/status') {
        return Promise.resolve({ data: { initialized: false } })
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    const route = await navigateTo('/dashboard')

    expect(route.fullPath).toBe('/setup')
  })

  it('preserves the setup token when redirecting to setup', async () => {
    const systemStore = useSystemStore()
    systemStore.isInitialized = false
    mocked.api.get.mockImplementation((url) => {
      if (url === '/setup/status') {
        return Promise.resolve({ data: { initialized: false } })
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    const route = await navigateTo('/dashboard?setup_token=bootstrap-token')

    expect(route.fullPath).toBe('/setup?setup_token=bootstrap-token')
  })

  it('allows documentation routes while setup is incomplete', async () => {
    mocked.api.get.mockImplementation((url) => {
      if (url === '/setup/status') {
        return Promise.resolve({ data: { initialized: false } })
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    const route = await navigateTo('/docs')

    expect(route.name).toBe('DocumentationHub')
  })

  it('allows legal routes without setup or auth checks', async () => {
    mocked.api.get.mockReset()

    const creditsRoute = await navigateTo('/credits')
    expect(creditsRoute.name).toBe('Credits')

    const impressumRoute = await navigateTo('/impressum')
    expect(impressumRoute.name).toBe('Impressum')

    const privacyRoute = await navigateTo('/privacy')
    expect(privacyRoute.name).toBe('PrivacyPolicy')

    const cookieRoute = await navigateTo('/cookies')
    expect(cookieRoute.name).toBe('CookiePolicy')
    expect(mocked.api.get).not.toHaveBeenCalled()
  })

  it('allows public record and embed routes without setup or auth checks', async () => {
    mocked.api.get.mockReset()

    const publicRoute = await navigateTo('/p/records/zenodo/123')
    expect(publicRoute.name).toBe('PublicRecord')

    const embedRoute = await navigateTo('/embed/records/zenodo/123')
    expect(embedRoute.name).toBe('EmbedRecord')
    expect(mocked.api.get).not.toHaveBeenCalled()
  })

  it('redirects initialized users away from setup', async () => {
    const authStore = useAuthStore()
    authStore.token = 'token'
    authStore.setUser({
      id: 9,
      role: 'user',
    })

    const route = await navigateTo('/setup')

    expect(route.fullPath).toBe('/dashboard')
  })

  it('allows pipeline authors provided via capabilities_json into the constructor route', async () => {
    const authStore = useAuthStore()
    authStore.token = 'token'
    authStore.setUser({
      id: 2,
      role: 'user',
      capabilities_json: ['native_pipeline_author'],
    })

    const route = await navigateTo('/tools/pipeline-constructor')

    expect(route.name).toBe('PipelineConstructor')
  })

  it('fetches the current user and allows constructor access when fetched capabilities_json grants authoring', async () => {
    const authStore = useAuthStore()
    authStore.token = 'token'
    mocked.authService.getCurrentUser.mockResolvedValue({
      data: {
        user: {
          id: 3,
          role: 'user',
          capabilities_json: ['native_pipeline_author'],
        },
      },
    })

    const route = await navigateTo('/tools/pipeline-constructor')

    expect(mocked.authService.getCurrentUser).toHaveBeenCalledTimes(1)
    expect(route.name).toBe('PipelineConstructor')
    expect(authStore.capabilities).toEqual(['native_pipeline_author'])
  })

  it('redirects authenticated non-moderators away from moderator-only routes', async () => {
    const authStore = useAuthStore()
    authStore.token = 'token'
    authStore.setUser({
      id: 5,
      role: 'user',
    })

    const route = await navigateTo('/tools/zenodo-batch-operations')

    expect(route.fullPath).toBe('/dashboard')
  })

  it('redirects authenticated users without pipeline author capability away from the constructor route', async () => {
    const authStore = useAuthStore()
    authStore.token = 'token'
    authStore.setUser({
      id: 4,
      role: 'user',
      capabilities: [],
    })

    const route = await navigateTo('/tools/pipeline-constructor')

    expect(route.fullPath).toBe('/dashboard')
  })

  it('allows users with developer access into developer mode', async () => {
    const authStore = useAuthStore()
    authStore.token = 'token'
    authStore.setUser({
      id: 6,
      role: 'user',
      capabilities: ['developer_access'],
    })

    const route = await navigateTo('/developer')

    expect(route.name).toBe('DeveloperMode')
  })

  it('redirects regular authenticated users away from developer mode', async () => {
    const authStore = useAuthStore()
    authStore.token = 'token'
    authStore.setUser({
      id: 7,
      role: 'user',
      capabilities: [],
    })

    const route = await navigateTo('/developer')

    expect(route.fullPath).toBe('/dashboard')
  })
})
