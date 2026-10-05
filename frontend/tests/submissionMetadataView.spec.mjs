import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  route: {
    query: {},
  },
  router: {
    push: vi.fn(),
  },
  workflowStore: {
    sessionId: null,
    isBatchMode: false,
    msfPath: null,
    msfMapping: {},
    fileMetadataMap: {},
    prevStep: vi.fn(),
    nextStep: vi.fn(),
    setSubmissionMetadata: vi.fn(),
  },
  api: {
    get: vi.fn(),
    put: vi.fn(),
  },
  workflowState: {
    persistWorkflowState: vi.fn().mockResolvedValue(undefined),
    restoreWorkflowContext: vi.fn().mockResolvedValue(undefined),
    shouldRestoreWorkflowContext: vi.fn(() => false),
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
    useRouter: () => mocked.router,
  }
})

vi.mock('@/stores/workflow', () => ({
  useWorkflowStore: () => mocked.workflowStore,
}))

vi.mock('@/services/api', () => ({
  default: mocked.api,
}))

vi.mock('@/utils/workflowState', () => ({
  persistWorkflowState: mocked.workflowState.persistWorkflowState,
  restoreWorkflowContext: mocked.workflowState.restoreWorkflowContext,
  shouldRestoreWorkflowContext: mocked.workflowState.shouldRestoreWorkflowContext,
}))

import SubmissionMetadataView from '../src/views/workflow/SubmissionMetadataView.vue'

const schemaPayload = {
  standard_fields: [
    { key: 'title', label: 'Title', type: 'text', mandatory: true },
  ],
  complex_fields: {},
  vocabularies: {},
}

describe('SubmissionMetadataView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(mocked.router).forEach((fn) => fn.mockReset())
    Object.values(mocked.api).forEach((fn) => fn.mockReset())
    Object.values(mocked.workflowState).forEach((fn) => fn.mockClear?.())
    mocked.workflowStore.sessionId = null
    mocked.workflowStore.isBatchMode = false
    mocked.workflowStore.msfPath = null
    mocked.workflowStore.msfMapping = {}
    mocked.workflowStore.fileMetadataMap = {}
    mocked.workflowStore.prevStep.mockReset()
    mocked.workflowStore.nextStep.mockReset()
    mocked.workflowStore.setSubmissionMetadata.mockReset()
    mocked.route.query = {}
  })

  it('shows an expired-session error when the workflow session is missing', async () => {
    const wrapper = mount(SubmissionMetadataView, {
      global: {
        stubs: {
          StepIndicator: true,
          LoadingSpinner: true,
          Alert: {
            props: ['message'],
            template: '<div class="alert-stub">{{ message }}</div>',
          },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Your session has expired or was not found. Please start a new upload.')
  })

  it('renders batch metadata context and advances without saving metadata drafts', async () => {
    mocked.workflowStore.sessionId = 42
    mocked.workflowStore.isBatchMode = true
    mocked.workflowStore.msfPath = '/tmp/source.xlsx'
    mocked.workflowStore.msfMapping = { Filename: '_filename', Title: 'title' }
    mocked.workflowStore.fileMetadataMap = {
      'model-a.glb': { title: 'Model A' },
    }
    mocked.api.get.mockImplementation((url) => {
      if (url === '/metadata/zenodo-community-override') {
        return Promise.resolve({ data: { config: { enabled: false } } })
      }
      if (url === '/metadata/schema') {
        return Promise.resolve({ data: schemaPayload })
      }
      if (url === '/metadata/user/42') {
        return Promise.resolve({ data: { metadata: {} } })
      }
      throw new Error(`Unexpected GET ${url}`)
    })

    const wrapper = mount(SubmissionMetadataView, {
      global: {
        stubs: {
          StepIndicator: true,
          LoadingSpinner: true,
          Alert: {
            props: ['message'],
            template: '<div class="alert-stub">{{ message }}</div>',
          },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Batch Mode Active')
    expect(wrapper.text()).toContain('/tmp/source.xlsx')
    expect(wrapper.text()).toContain('Filename')
    expect(wrapper.text()).toContain('Model A')

    const continueButton = wrapper.findAll('button').find((button) => button.text().includes('Save & Continue'))
    await continueButton.trigger('click')
    await flushPromises()

    expect(mocked.api.put).not.toHaveBeenCalledWith('/metadata/user/42', expect.anything())
    expect(mocked.workflowStore.nextStep).toHaveBeenCalledTimes(1)
    expect(mocked.workflowState.persistWorkflowState).toHaveBeenLastCalledWith(mocked.workflowStore, 'edm_selection')
    expect(mocked.router.push).toHaveBeenCalledWith('/workflow/edm-selection')
  })

  it('links complex-field errors to their original entry and single-object inputs', async () => {
    mocked.workflowStore.sessionId = 42
    mocked.api.get.mockImplementation((url) => {
      if (url === '/metadata/zenodo-community-override') return Promise.resolve({ data: { config: { enabled: false } } })
      if (url === '/metadata/schema') return Promise.resolve({ data: { ...schemaPayload, complex_fields: {
        creators: { label: 'Creators', item_label: 'Creator', attributes: [
          { key: 'name', label: 'Name', mandatory: true }, { key: 'affiliation', label: 'Affiliation' },
        ] },
        journal: { label: 'Journal', allow_multiple: false, attributes: [
          { key: 'title', label: 'Journal title' }, { key: 'year', label: 'Year', mandatory: true },
        ] },
      } } })
      if (url === '/metadata/user/42') return Promise.resolve({ data: { metadata: { zenodo_metadata_draft: {
        title: 'Museum model', creators: [{}, { affiliation: 'Museum' }], journal: { title: 'Collection' },
      } } } })
      throw new Error(`Unexpected GET ${url}`)
    })
    const wrapper = mount(SubmissionMetadataView, {
      attachTo: document.body,
      global: { stubs: { StepIndicator: true, LoadingSpinner: true } },
    })
    try {
      await flushPromises()
      await wrapper.findAll('button').find(button => button.text().includes('Save & Continue')).trigger('click')
      await flushPromises()
      const creator = wrapper.get('#field-creators-1-name')
      expect(document.activeElement).toBe(creator.element)
      expect(creator.attributes('aria-describedby')).toBe('field-creators-1-name-error')
      expect(wrapper.get('#field-creators-1-name-error').text()).toBe('Creator 2: Name is required.')
      expect(wrapper.get('#field-journal-year').attributes('aria-describedby')).toBe('field-journal-year-error')
      expect(wrapper.get('#field-journal-year-error').text()).toBe('Journal: Year is required.')
      expect(mocked.api.put).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
    }
  })
})
