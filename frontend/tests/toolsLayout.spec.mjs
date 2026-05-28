import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  toolsService: {
    getContext: vi.fn(),
  },
  route: {
    path: '/tools/pipeline-constructor',
  },
}))

vi.mock('@/services/tools.service', () => ({ default: mocked.toolsService }))
vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
  }
})

import ToolsLayout from '../src/views/tools/ToolsLayout.vue'

function feature(enabled, reason = '') {
  return { enabled, reason }
}

async function mountToolsLayout(features) {
  mocked.toolsService.getContext.mockResolvedValue({
    data: {
      features,
    },
  })

  const wrapper = mount(ToolsLayout, {
    global: {
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a :href="to"><slot /></a>',
        },
        RouterView: { template: '<div data-testid="tools-router-view" />' },
      },
    },
  })

  await flushPromises()
  return wrapper
}

describe('ToolsLayout feature navigation', () => {
  beforeEach(() => {
    mocked.toolsService.getContext.mockReset()
    mocked.route.path = '/tools/pipeline-constructor'
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
    expect(wrapper.text()).toContain('Some tools are disabled because of role, capability, or runtime requirements.')
  })
})
