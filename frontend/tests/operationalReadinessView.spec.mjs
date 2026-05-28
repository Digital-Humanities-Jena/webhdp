import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'

const mocked = vi.hoisted(() => ({
  adminService: {
    getSetupGuidance: vi.fn(),
  },
}))

vi.mock('@/services/admin.service', () => ({ default: mocked.adminService }))

import OperationalReadinessView from '../src/views/admin/OperationalReadinessView.vue'

describe('OperationalReadinessView', () => {
  beforeEach(() => {
    mocked.adminService.getSetupGuidance.mockReset()
    mocked.adminService.getSetupGuidance.mockResolvedValue({
      data: {
        deployment_label: 'Server/VPS',
        deployment_mode: 'server',
        deployment_class: 'server',
        storage_mode: 'pure_cloud',
        summary: {
          mandatory_open: ['cloud_storage'],
          recommended_open: ['backup_policy'],
        },
        sections: [
          {
            id: 'storage',
            title: 'Storage',
            items: [
              {
                id: 'cloud_storage',
                label: 'Cloud storage availability',
                required_level: 'Mandatory',
                status: 'action_required',
                severity: 'error',
                route: '/settings/cloud-testing',
                message: 'Dropbox or Google Drive must be reachable.',
              },
              {
                id: 'local_folder_workflows',
                label: 'Local mounted-folder workflows',
                required_level: 'Optional',
                status: 'optional',
                severity: 'info',
                route: '/settings/storage',
                message: 'Only for mounted local workflows.',
              },
            ],
          },
          {
            id: 'backups',
            title: 'Backups',
            items: [
              {
                id: 'backup_policy',
                label: 'Backup policy and latest backup',
                required_level: 'Recommended',
                status: 'action_required',
                severity: 'warning',
                route: '/admin/dashboard',
                message: 'Create encrypted backups.',
              },
            ],
          },
        ],
      },
    })
  })

  it('shows readiness labels and action links', async () => {
    const wrapper = mount(OperationalReadinessView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="readiness-mode"]').text()).toContain('Server/VPS')
    expect(wrapper.text()).toContain('Mandatory')
    expect(wrapper.text()).toContain('Recommended')
    expect(wrapper.text()).toContain('Optional')
    expect(wrapper.get('[data-testid="readiness-item-cloud_storage"]').text()).toContain('Action needed')

    const actions = wrapper.findAll('[data-testid="readiness-action"]')
    expect(actions.map((action) => action.attributes('href'))).toContain('/settings/cloud-testing')
    expect(actions.map((action) => action.attributes('href'))).toContain('/settings/storage')
  })
})
