import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  router: {
    push: vi.fn(),
  },
  systemStore: {
    checkHealth: vi.fn(),
    testRender: vi.fn(),
    createAdmin: vi.fn(),
    completeSetup: vi.fn(),
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRouter: () => mocked.router,
  }
})

vi.mock('@/stores/system', () => ({
  useSystemStore: () => mocked.systemStore,
}))

import SetupView from '../src/views/setup/SetupView.vue'

describe('SetupView', () => {
  beforeEach(() => {
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.systemStore).forEach((fn) => fn.mockReset())
  })

  it('runs health checks and allows setup to continue when rendering is unavailable', async () => {
    mocked.systemStore.checkHealth.mockResolvedValue({
      data: {
        renderer_enabled: false,
        blender_reachable: true,
        zenodo_sandbox_status: 'Not Configured',
        zenodo_production_status: 'Reachable',
      },
    })
    mocked.systemStore.createAdmin.mockResolvedValue({ data: { ok: true } })
    mocked.systemStore.completeSetup.mockResolvedValue({ data: { ok: true } })

    const wrapper = mount(SetupView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(mocked.systemStore.checkHealth).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Zenodo Production (Env)')

    const skipButton = wrapper.findAll('button').find((button) => button.text().includes('Skip Rendering'))
    await skipButton.trigger('click')
    await flushPromises()

    await wrapper.get('#email').setValue('admin@example.com')
    await wrapper.get('#password').setValue('secret')
    await wrapper.get('form').trigger('submit.prevent')
    await flushPromises()

    expect(mocked.systemStore.createAdmin).toHaveBeenCalledWith({
      email: 'admin@example.com',
      password: 'secret',
    })
    expect(mocked.systemStore.completeSetup).toHaveBeenCalledTimes(1)
    expect(mocked.router.push).toHaveBeenCalledWith('/login')
  })

  it('renders detected deployment mode and mandatory readiness preview', async () => {
    mocked.systemStore.checkHealth.mockResolvedValue({
      data: {
        renderer_enabled: true,
        blender_reachable: false,
        zenodo_sandbox_status: 'Not Configured',
        zenodo_production_status: 'Not Configured',
        setup_guidance: {
          deployment_label: 'Server/VPS',
          storage_mode: 'pure_cloud',
          checklist: [
            {
              id: 'cloud_storage',
              label: 'Cloud storage availability',
              required_level: 'Mandatory',
              status: 'action_required',
              message: 'Dropbox or Google Drive must be reachable.',
            },
            {
              id: 'backup_policy',
              label: 'Backup policy and latest backup',
              required_level: 'Recommended',
              status: 'action_required',
              message: 'Create a backup.',
            },
          ],
        },
      },
    })

    const wrapper = mount(SetupView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    await wrapper.find('[data-testid="setup-start"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="setup-deployment-mode"]').text()).toContain('Server/VPS')
    expect(wrapper.text()).toContain('Cloud storage availability')
    expect(wrapper.text()).not.toContain('Backup policy and latest backup')
  })
})
