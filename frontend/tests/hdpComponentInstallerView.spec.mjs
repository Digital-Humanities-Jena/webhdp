import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'

const mocked = vi.hoisted(() => ({
  route: { path: '/tools/hdp-components/install' },
  toolsService: {
    getContext: vi.fn(),
    listHdpComponentCatalog: vi.fn(),
    getHdpComponentCatalogDiagnostics: vi.fn(),
    listHdpComponentInstallations: vi.fn(),
    validateHdpComponentInstall: vi.fn(),
    installHdpComponent: vi.fn(),
    testHdpComponentInstallation: vi.fn(),
  },
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => mocked.route,
}))

vi.mock('@/services/tools.service', () => ({ default: mocked.toolsService }))

vi.mock('@/composables/useToast', () => ({
  useToast: () => ({
    success: mocked.toast.success,
    warning: mocked.toast.warning,
    error: mocked.toast.error,
  }),
}))

import ToolsLayout from '../src/views/tools/ToolsLayout.vue'
import HdpComponentInstallerView from '../src/views/tools/HdpComponentInstallerView.vue'

describe('HDP component installer tools UI', () => {
  beforeEach(() => {
    mocked.toolsService.getContext.mockReset()
    mocked.toolsService.listHdpComponentCatalog.mockReset()
    mocked.toolsService.getHdpComponentCatalogDiagnostics.mockReset()
    mocked.toolsService.listHdpComponentInstallations.mockReset()
    mocked.toolsService.validateHdpComponentInstall.mockReset()
    mocked.toolsService.installHdpComponent.mockReset()
    mocked.toolsService.testHdpComponentInstallation.mockReset()
    mocked.toast.success.mockReset()
    mocked.toast.warning.mockReset()
    mocked.toast.error.mockReset()
    mocked.toolsService.getContext.mockResolvedValue({
      data: {
        features: {
          native_playground: { enabled: true },
          pipeline_constructor: { enabled: true },
          pipeline_preflight: { enabled: true },
          hpc_diagnostics: { enabled: true },
          hdp_component_installer: { enabled: true },
        },
      },
    })
    mocked.toolsService.listHdpComponentCatalog.mockResolvedValue({
      data: {
        components: [
          {
            component_key: 'gltf_validator',
            version: '1.0.0',
            label: 'glTF/GLB Validator',
            description: 'Validate glTF and GLB assets.',
            category: '3D QA',
            tags: ['3d', 'validation'],
            manifest_text: 'metadata:\n  name: gltf_validator\n  version: "1.0.0"\n',
            manifest: {
              metadata: {
                name: 'gltf_validator',
                version: '1.0.0',
                category: '3D QA',
              },
            },
            profile: { id: 'hpc_singularity' },
            has_smoke_test: true,
            catalog_source: 'local',
            trust_level: 'local',
            source_path: 'external_code/gltf_validator/component.yaml',
            warnings: [],
          },
        ],
        summary: { total: 1, installable: 1, warnings: [] },
      },
    })
    mocked.toolsService.getHdpComponentCatalogDiagnostics.mockResolvedValue({
      data: {
        schema: 'webhdp.component-index.v1',
        configured: false,
        sources: [],
        min_trust_level: 'unknown',
      },
    })
    mocked.toolsService.listHdpComponentInstallations.mockResolvedValue({ data: { installations: [] } })
  })

  it('shows the installer navigation item when the admin feature is enabled', async () => {
    const wrapper = mount(ToolsLayout, {
      global: {
        stubs: {
          RouterView: true,
          RouterLink: {
            props: ['to'],
            template: '<a :href="to"><slot /></a>',
          },
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('HDP Component Installer')
    expect(wrapper.html()).toContain('/tools/hdp-components/install')
  })

  it('loads catalog components and installs the selected manifest', async () => {
    mocked.toolsService.validateHdpComponentInstall.mockResolvedValue({
      data: {
        component_key: 'gltf_validator',
        version: '1.0.0',
        profile: { id: 'hpc_singularity' },
        sif: { source_type: 'remote_path' },
        checks: { hpc_link: { success: true }, manifest_schema: { success: true } },
      },
    })
    mocked.toolsService.installHdpComponent.mockResolvedValue({
      data: {
        installation: {
          installation_id: 'install-1',
          component_key: 'gltf_validator',
          version: '1.0.0',
          status: 'installed',
        },
      },
    })

    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    expect(wrapper.text()).toContain('glTF/GLB Validator')
    expect(wrapper.text()).toContain('Manifest Review')

    await wrapper.find('input[type="text"]').setValue('/work/components/gltf_validator.sif')
    await wrapper.findAll('button').find((button) => button.text() === 'Validate Package').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Install on HPC').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.validateHdpComponentInstall).toHaveBeenCalled()
    expect(mocked.toolsService.validateHdpComponentInstall.mock.calls[0][0].manifest_text).toContain('gltf_validator')
    expect(mocked.toolsService.installHdpComponent).toHaveBeenCalled()
    expect(wrapper.text()).toContain('installed')
  })

  it('blocks install when HPC-Link validation returns a warning', async () => {
    mocked.toolsService.validateHdpComponentInstall.mockResolvedValue({
      data: {
        component_key: 'gltf_validator',
        version: '1.0.0',
        checks: {
          hpc_link: { success: false, error: 'HPC-Link is disabled' },
          manifest_schema: { success: true },
          profile: { success: true },
          sif_source: { success: true },
        },
      },
    })

    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    await wrapper.find('input[type="text"]').setValue('/work/components/gltf_validator.sif')
    await wrapper.findAll('button').find((button) => button.text() === 'Validate Package').trigger('click')
    await flushPromises()

    const installButton = wrapper.findAll('button').find((button) => button.text() === 'Install on HPC')
    expect(installButton.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('hpc_link')
    expect(wrapper.text()).toContain('warning')
    expect(mocked.toast.warning).toHaveBeenCalledWith('Package checks completed, but HPC-Link is not ready.')
    expect(mocked.toolsService.installHdpComponent).not.toHaveBeenCalled()
  })

  it('supports the local Docker install strategy', async () => {
    const localCatalog = {
      data: {
        components: [
          {
            component_key: 'gltf_validator',
            version: '1.0.0',
            label: 'glTF/GLB Validator',
            manifest_text: 'metadata:\n  name: gltf_validator\n  version: "1.0.0"\n',
            manifest: { metadata: { name: 'gltf_validator', version: '1.0.0' } },
            profile: { id: 'local_docker', image: 'webhdp-gltf-validator:local' },
            install_strategy: 'local_container',
            install_strategies: [{ id: 'local_container', image: 'webhdp-gltf-validator:local' }],
            has_smoke_test: false,
          },
        ],
        summary: { total: 1, installable: 1, warnings: [] },
      },
    }
    mocked.toolsService.validateHdpComponentInstall.mockResolvedValue({
      data: {
        component_key: 'gltf_validator',
        version: '1.0.0',
        profile: { id: 'local_docker' },
        container: { source_type: 'docker_image', image: 'webhdp-gltf-validator:local' },
        checks: { local_container: { success: true }, manifest_schema: { success: true } },
      },
    })
    mocked.toolsService.installHdpComponent.mockResolvedValue({
      data: {
        installation: {
          installation_id: 'install-local-1',
          component_key: 'gltf_validator',
          version: '1.0.0',
          status: 'installed',
          install_strategy: 'local_container',
          container_image: 'webhdp-gltf-validator:local',
        },
      },
    })

    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    mocked.toolsService.listHdpComponentCatalog.mockResolvedValueOnce(localCatalog)
    await wrapper.findAll('button').find((button) => button.text() === 'Local Docker').trigger('click')
    await flushPromises()
    expect(wrapper.find('input[type="text"]').element.value).toBe('webhdp-gltf-validator:local')

    await wrapper.findAll('button').find((button) => button.text() === 'Validate Package').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Install Locally').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.listHdpComponentCatalog).toHaveBeenLastCalledWith({ install_strategy: 'local_container', source: 'all' })
    expect(mocked.toolsService.validateHdpComponentInstall.mock.calls[0][0]).toMatchObject({
      install_strategy: 'local_container',
      container_image: 'webhdp-gltf-validator:local',
    })
    expect(mocked.toolsService.installHdpComponent.mock.calls[0][0]).toMatchObject({
      install_strategy: 'local_container',
      container_image: 'webhdp-gltf-validator:local',
    })
    expect(wrapper.text()).toContain('Local Docker')
  })

  it('supports custom manifest mode', async () => {
    mocked.toolsService.validateHdpComponentInstall.mockResolvedValue({
      data: {
        component_key: 'custom_validator',
        version: '1.0.0',
        checks: { hpc_link: { success: true } },
      },
    })

    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Custom manifest').trigger('click')
    await wrapper.find('textarea').setValue('metadata:\n  name: custom_validator\n  version: "1.0.0"\n')
    await wrapper.find('input[type="text"]').setValue('/work/components/custom_validator.sif')
    await wrapper.findAll('button').find((button) => button.text() === 'Validate Package').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.validateHdpComponentInstall.mock.calls[0][0].manifest_text).toContain('custom_validator')
    expect(wrapper.text()).toContain('custom_validator')
  })

  it('includes custom checksum and digest fields in custom install payloads', async () => {
    mocked.toolsService.validateHdpComponentInstall.mockResolvedValue({
      data: {
        component_key: 'custom_validator',
        version: '1.0.0',
        checks: { hpc_link: { success: true } },
      },
    })

    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Custom manifest').trigger('click')
    await wrapper.find('textarea').setValue('metadata:\n  name: custom_validator\n  version: "1.0.0"\n')
    const inputs = wrapper.findAll('input[type="text"]')
    await inputs[0].setValue('/work/components/custom_validator.sif')
    await inputs[1].setValue('a'.repeat(64))
    await wrapper.findAll('button').find((button) => button.text() === 'Validate Package').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.validateHdpComponentInstall.mock.calls[0][0]).toMatchObject({
      sif_source: '/work/components/custom_validator.sif',
      sif_sha256: 'a'.repeat(64),
    })
  })

  it('reloads the catalog with the selected source filter', async () => {
    mocked.toolsService.listHdpComponentCatalog.mockResolvedValueOnce({
      data: { components: [], summary: { total: 0, installable: 0, warnings: [], source: 'remote' } },
    })

    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Remote indexes').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.listHdpComponentCatalog).toHaveBeenLastCalledWith({ install_strategy: 'hpc_sif', source: 'remote' })
  })

  it('shows remote catalog provenance and includes catalog metadata in install payloads', async () => {
    const remoteCatalog = {
      data: {
        components: [
          {
            component_key: 'remote_validator',
            version: '1.0.0',
            label: 'Remote Validator',
            manifest_text: 'metadata:\n  name: remote_validator\n  version: "1.0.0"\n',
            manifest: { metadata: { name: 'remote_validator', version: '1.0.0' } },
            profile: { id: 'local_docker', image: 'ghcr.io/hdp-components/remote-validator@sha256:abc' },
            install_strategy: 'local_container',
            catalog_source: 'remote_index',
            trust_level: 'community-reviewed',
            catalog_ref: {
              source: '/catalog/index.json',
              component_key: 'remote_validator',
              version: '1.0.0',
              manifest_url: '/catalog/component.yaml',
            },
            git: { url: 'https://github.com/example/remote-validator', tag: 'v1.0.0' },
            zenodo: { doi: '10.5281/zenodo.123', record_url: 'https://zenodo.org/records/123' },
            docker_digest: 'sha256:abc',
            install_strategies: [{ id: 'local_container', image: 'ghcr.io/hdp-components/remote-validator@sha256:abc' }],
            has_smoke_test: true,
          },
        ],
        summary: { total: 1, installable: 1, warnings: [], source: 'remote' },
      },
    }
    mocked.toolsService.validateHdpComponentInstall.mockResolvedValue({
      data: {
        component_key: 'remote_validator',
        version: '1.0.0',
        profile: { id: 'local_docker' },
        container: { source_type: 'docker_image', image: 'ghcr.io/hdp-components/remote-validator@sha256:abc' },
        checks: { local_container: { success: true }, manifest_schema: { success: true } },
      },
    })
    mocked.toolsService.installHdpComponent.mockResolvedValue({
      data: {
        installation: {
          installation_id: 'install-remote-1',
          component_key: 'remote_validator',
          version: '1.0.0',
          status: 'installed',
          install_strategy: 'local_container',
        },
      },
    })

    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    mocked.toolsService.listHdpComponentCatalog.mockResolvedValueOnce(remoteCatalog)
    await wrapper.findAll('button').find((button) => button.text() === 'Local Docker').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Remote Validator')
    expect(wrapper.text()).toContain('Community reviewed')
    expect(wrapper.text()).toContain('Remote index')
    expect(wrapper.find('input[type="text"]').element.value).toBe('ghcr.io/hdp-components/remote-validator@sha256:abc')

    await wrapper.findAll('button').find((button) => button.text() === 'Validate Package').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Install Locally').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.validateHdpComponentInstall.mock.calls[0][0]).toMatchObject({
      install_strategy: 'local_container',
      catalog_source: 'remote_index',
      trust_level: 'community-reviewed',
      docker_digest: 'sha256:abc',
      catalog_ref: {
        component_key: 'remote_validator',
        version: '1.0.0',
      },
    })
    expect(mocked.toolsService.installHdpComponent.mock.calls[0][0]).toMatchObject({
      catalog_source: 'remote_index',
      trust_level: 'community-reviewed',
    })
  })

  it('shows smoke test response details after testing an installed component', async () => {
    mocked.toolsService.listHdpComponentInstallations.mockResolvedValue({
      data: {
        installations: [
          {
            installation_id: 'install-1',
            component_key: 'gltf_validator',
            version: '1.0.0',
            status: 'installed',
            updated_at: '2026-01-01T00:00:00',
          },
        ],
      },
    })
    mocked.toolsService.testHdpComponentInstallation.mockResolvedValue({
      data: {
        installation: {
          installation_id: 'install-1',
          component_key: 'gltf_validator',
          version: '1.0.0',
          status: 'installed',
        },
        test: {
          success: true,
          remote_test_dir: '/work/apps/webhdp/test-runs/test-1',
          logs: { stdout: 'ok', stderr: '' },
        },
      },
    })

    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === 'Test').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.testHdpComponentInstallation).toHaveBeenCalledWith('install-1')
    expect(wrapper.text()).toContain('Smoke Test Details')
    expect(wrapper.text()).toContain('/work/apps/webhdp/test-runs/test-1')
  })

  it('shows the admin-only disabled state for non-admin users', async () => {
    mocked.toolsService.getContext.mockResolvedValueOnce({
      data: {
        features: {
          native_playground: { enabled: true },
          hdp_component_installer: { enabled: false, reason: 'Requires admin' },
        },
      },
    })

    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()

    expect(wrapper.text()).toContain('Requires Admin role.')
    await wrapper.find('input[type="text"]').setValue('/work/components/gltf_validator.sif')
    const validateButton = wrapper.findAll('button').find((button) => button.text() === 'Validate Package')
    expect(validateButton.attributes('disabled')).toBeDefined()
    expect(mocked.toolsService.validateHdpComponentInstall).not.toHaveBeenCalled()
  })
  it('ignores a validation response for a source that has changed', async () => {
    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    await wrapper.find('input[type="text"]').setValue('/work/one.sif')
    let resolve
    mocked.toolsService.validateHdpComponentInstall.mockImplementation(() => new Promise(done => { resolve = done }))
    await wrapper.findAll('button').find(button => button.text() === 'Validate Package').trigger('click')
    await wrapper.find('input[type="text"]').setValue('/work/two.sif')
    resolve({ data: { checks: { hpc_link: { success: true } } } })
    await flushPromises()
    expect(wrapper.findAll('button').find(button => button.text() === 'Install on HPC').attributes('disabled')).toBeDefined()
    expect(mocked.toast.success).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not carry a previous component source into another package', async () => {
    const initial = await mocked.toolsService.listHdpComponentCatalog()
    const second = { ...initial.data.components[0], component_key: 'second', label: 'Second component', manifest_text: 'metadata: {name: second}' }
    mocked.toolsService.listHdpComponentCatalog.mockResolvedValue({ data: { components: [...initial.data.components, second] } })
    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    await wrapper.find('input[type="text"]').setValue('/work/first.sif')
    await wrapper.findAll('button').find(button => button.text().includes('Second component')).trigger('click')
    expect(wrapper.find('input[type="text"]').element.value).toBe('')
    expect(wrapper.findAll('button').find(button => button.text() === 'Validate Package').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('does not attach catalog provenance to a custom manifest', async () => {
    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === 'Custom manifest').trigger('click')
    await wrapper.get('textarea').setValue('metadata: {name: custom, version: 1.0.0}')
    await wrapper.find('input[type="text"]').setValue('/work/custom.sif')
    mocked.toolsService.validateHdpComponentInstall.mockResolvedValue({ data: { checks: { hpc_link: { success: true } } } })
    await wrapper.findAll('button').find(button => button.text() === 'Validate Package').trigger('click')
    await flushPromises()
    expect(mocked.toolsService.validateHdpComponentInstall.mock.calls[0][0].catalog_source).toBeUndefined()
    wrapper.unmount()
  })

  it('reports unsuccessful smoke tests without a success notification', async () => {
    mocked.toolsService.listHdpComponentInstallations.mockResolvedValue({ data: { installations: [{ installation_id: 'test-1', component_key: 'validator', status: 'installed' }] } })
    mocked.toolsService.testHdpComponentInstallation.mockResolvedValue({ data: { test: { success: false, error: 'Expected report missing' } } })
    const wrapper = mount(HdpComponentInstallerView)
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === 'Test').trigger('click')
    await flushPromises()
    expect(mocked.toast.success).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('Expected report missing')
    wrapper.unmount()
  })

})
