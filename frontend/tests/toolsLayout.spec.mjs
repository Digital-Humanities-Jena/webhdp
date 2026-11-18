import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  toolsService: {
    getContext: vi.fn(),
    runPipelinePreflightLocal: vi.fn(),
  },
  route: {
    path: '/tools/pipeline-preflight',
    name: 'PipelinePreflight',
    query: {},
    hash: '',
  },
  replace: vi.fn(),
}))

vi.mock('@/services/tools.service', () => ({ default: mocked.toolsService }))
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
    useRouter: () => ({ replace: mocked.replace }),
  }
})

import ToolsLayout from '../src/views/tools/ToolsLayout.vue'
import PipelinePreflightView from '../src/views/tools/PipelinePreflightView.vue'

function feature(enabled, reason = '') {
  return { enabled, reason }
}

async function mountToolsLayout(features, context = {}, child = null) {
  mocked.toolsService.getContext.mockResolvedValue({
    data: { features, ...context },
  })

  const wrapper = mount(ToolsLayout, {
    global: {
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :href="to"><slot /></a>',
        },
        RouterView: child ? { render: () => h(child) } : { template: '<div data-testid="tools-router-view" />' },
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('ToolsLayout feature navigation', () => {
  beforeEach(() => {
    mocked.toolsService.getContext.mockReset()
    mocked.toolsService.runPipelinePreflightLocal.mockReset()
    mocked.replace.mockReset()
    Object.assign(mocked.route, { path: '/tools/pipeline-preflight', name: 'PipelinePreflight', query: {}, hash: '' })
  })

  it('renders the pipeline constructor as an enabled tool when the backend context allows it', async () => {
    const wrapper = await mountToolsLayout({
      native_playground: feature(true, 'Requires authentication'),
      pipeline_constructor: feature(true, 'Requires admin or native_pipeline_author capability'),
      pipeline_preflight: feature(false, 'Requires admin and local mode'),
    })

    expect(wrapper.get('[data-testid="tools-nav-enabled-pipeline_constructor"]').text()).toContain('Pipeline Constructor')

    const disabledPreflight = wrapper.get('[data-testid="tools-nav-disabled-pipeline_preflight"]')
    expect(disabledPreflight.text()).toContain('Pipeline Preflight')
    expect(disabledPreflight.text()).toContain('Requires admin and local mode')
  })

  it('renders the pipeline constructor as disabled with its capability reason when unavailable', async () => {
    const wrapper = await mountToolsLayout({
      native_playground: feature(true, 'Requires authentication'),
      pipeline_constructor: feature(false, 'Requires admin or native_pipeline_author capability'),
      pipeline_preflight: feature(false, 'Requires admin and local mode'),
    })

    const disabledConstructor = wrapper.get('[data-testid="tools-nav-disabled-pipeline_constructor"]')
    expect(disabledConstructor.text()).toContain('Pipeline Constructor')
    expect(disabledConstructor.text()).toContain('Requires admin or native_pipeline_author capability')
    expect(wrapper.text()).toContain('Unavailable tools')
  })

  it('lands on the first tool allowed by the active deployment', async () => {
    Object.assign(mocked.route, { path: '/tools', name: 'ToolsOverview' })
    await mountToolsLayout({
      native_playground: feature(false, 'Disabled in the core workflow profile'),
      pipeline_preflight: feature(false, 'Requires admin and local mode'),
      hpc_diagnostics: feature(true),
    }, { core_only: true })

    expect(mocked.replace).toHaveBeenCalledOnce()
    expect(mocked.replace).toHaveBeenCalledWith({ path: '/tools/hpc-diagnostics', query: {}, hash: '' })
  })

  it('shows an empty state when the account has no available tools', async () => {
    Object.assign(mocked.route, { path: '/tools', name: 'ToolsOverview' })
    const wrapper = await mountToolsLayout({ native_playground: feature(false) }, { core_only: true })

    expect(mocked.replace).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('No tools are available for your account')
    expect(wrapper.get('a[href="/uploads"]').text()).toBe('Open Uploads')
  })

  it('keeps a server preflight deep link and guides the user to submission readiness', async () => {
    const wrapper = await mountToolsLayout({
      native_playground: feature(true),
      pipeline_preflight: feature(false, 'Requires admin and local mode'),
    }, { storage_mode: 'server_only', core_only: true }, PipelinePreflightView)

    expect(mocked.replace).not.toHaveBeenCalled()
    expect(mocked.toolsService.getContext).toHaveBeenCalledOnce()
    expect(wrapper.get('#readiness-guidance').text()).toBe('Submission readiness')
    expect(wrapper.get('a[href="/uploads"]').text()).toBe('Open Uploads')
    expect(wrapper.find('select').exists()).toBe(false)
  })

  it('runs workstation preflight with the MSF from the shared tools context', async () => {
    const wrapper = await mountToolsLayout({ pipeline_preflight: feature(true) }, {
      storage_mode: 'local',
      msf_files: [{ path: 'input.msf.xlsx', full_path: '/data/local_input/input.msf.xlsx' }],
    }, PipelinePreflightView)
    mocked.toolsService.runPipelinePreflightLocal.mockResolvedValue({ data: { readiness: { status: 'ready', can_run: true } } })
    await wrapper.get('select').setValue('/data/local_input/input.msf.xlsx')
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(mocked.toolsService.getContext).toHaveBeenCalledOnce()
    expect(mocked.toolsService.runPipelinePreflightLocal).toHaveBeenCalledWith({
      msf_path: '/data/local_input/input.msf.xlsx',
      directory_path: '',
      recursive: true,
      duplicate_scan_columns: ['filename', 'title'],
    })
    expect(wrapper.text()).toContain('ready')
  })
})
