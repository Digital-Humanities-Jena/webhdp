import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { http } from 'msw'

import SubmissionMetadataView from '../src/views/workflow/SubmissionMetadataView.vue'
import { useAuthStore } from '../src/stores/auth'
import { useWorkflowStore } from '../src/stores/workflow'
import { mountWithApp } from './helpers/app.mjs'
import { activateTestPinia } from './helpers/pinia.mjs'
import { apiV1Url, jsonResponse, readJsonBody } from './msw/http.mjs'
import { server } from './msw/server.mjs'

describe('SubmissionMetadataView MSW integration', () => {
  let metadataSaveRequest
  let workflowStateRequests

  beforeEach(() => {
    sessionStorage.setItem('token', 'test-token')
    metadataSaveRequest = null
    workflowStateRequests = []

    server.use(
      http.get(apiV1Url('/metadata/zenodo-community-override'), () => jsonResponse({
        data: {
          config: {
            enabled: false,
          },
        },
      })),
      http.get(apiV1Url('/metadata/schema'), () => jsonResponse({
        data: {
          standard_fields: [
            {
              key: 'title',
              label: 'Title',
              type: 'text',
              mandatory: true,
            },
            {
              key: 'keywords',
              label: 'Keywords',
              type: 'tags',
            },
          ],
          complex_fields: {},
          vocabularies: {},
        },
      })),
      http.get(apiV1Url('/metadata/user/42'), () => jsonResponse({
        data: {
          metadata: {},
        },
      })),
      http.put(apiV1Url('/metadata/user/42'), async ({ request }) => {
        metadataSaveRequest = await readJsonBody(request)
        return jsonResponse({ data: { ok: true } })
      }),
      http.put(apiV1Url('/sessions/42/workflow-state'), async ({ request }) => {
        workflowStateRequests.push(await readJsonBody(request))
        return jsonResponse({ data: { ok: true } })
      }),
    )
  })

  it('loads schema over the API client, saves metadata, and advances the workflow', async () => {
    const pinia = activateTestPinia()
    useAuthStore(pinia).setUser({ id: 1 })
    const workflowStore = useWorkflowStore(pinia)
    workflowStore.setSessionId(42)
    workflowStore.setUploadedFiles([{ file_id: 1, name: 'asset.glb' }])
    workflowStore.setSelectedFiles([{ file_id: 1, name: 'asset.glb' }])

    const { router, wrapper } = await mountWithApp(SubmissionMetadataView, {
      pinia,
      route: '/workflow/metadata',
    })
    await flushPromises()

    await wrapper.get('#field-title').setValue('Batch-safe title')
    await wrapper.get('#field-keywords').setValue('alpha, beta')

    const continueButton = wrapper.findAll('button').find((button) => button.text().includes('Save & Continue'))
    await continueButton.trigger('click')
    await flushPromises()

    expect(metadataSaveRequest).toEqual({
      title: 'Batch-safe title',
      keywords: ['alpha', 'beta'],
    })
    expect(workflowStore.submissionMetadata).toEqual({
      title: 'Batch-safe title',
      keywords: ['alpha', 'beta'],
    })
    expect(workflowStateRequests.at(-1)).toMatchObject({
      phase: 'edm_selection',
      current_step: 5,
    })
    expect(router.currentRoute.value.path).toBe('/workflow/edm-selection')

    wrapper.unmount()
  })
  it('saves an edited draft after the debounce and restores it on remount', async () => {
    const pinia = activateTestPinia()
    useAuthStore(pinia).setUser({ id: 1 })
    const workflowStore = useWorkflowStore(pinia)
    workflowStore.setSessionId(42)
    workflowStore.setUploadedFiles([{ file_id: 1, name: 'asset.glb' }])
    workflowStore.setSelectedFiles([{ file_id: 1, name: 'asset.glb' }])
    let draft = {}
    server.use(
      http.put(apiV1Url('/metadata/user/42/draft'), async ({ request }) => {
        draft = await readJsonBody(request)
        return jsonResponse({ data: { ok: true } })
      }),
      http.get(apiV1Url('/metadata/user/42'), () => jsonResponse({ data: { metadata: { zenodo_metadata_draft: draft } } })),
    )
    let mounted = await mountWithApp(SubmissionMetadataView, { pinia, route: '/workflow/metadata' })
    await flushPromises()
    vi.useFakeTimers()
    await mounted.wrapper.get('#field-title').setValue('Recoverable draft')
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(draft.title).toBe('Recoverable draft')
    expect(mounted.wrapper.text()).toContain('Draft saved at')
    mounted.wrapper.unmount()
    vi.useRealTimers()
    mounted = await mountWithApp(SubmissionMetadataView, { pinia, route: '/workflow/metadata' })
    await flushPromises()
    expect(mounted.wrapper.get('#field-title').element.value).toBe('Recoverable draft')
    mounted.wrapper.unmount()
  })

  it('shows a failed autosave without a saved timestamp and permits retry', async () => {
    const pinia = activateTestPinia()
    useAuthStore(pinia).setUser({ id: 1 })
    const workflowStore = useWorkflowStore(pinia)
    workflowStore.setSessionId(42)
    workflowStore.setUploadedFiles([{ file_id: 1, name: 'asset.glb' }])
    workflowStore.setSelectedFiles([{ file_id: 1, name: 'asset.glb' }])
    server.use(http.put(apiV1Url('/metadata/user/42/draft'), () => jsonResponse({ error: { message: 'Storage unavailable' } }, { status: 503 })))
    const { wrapper } = await mountWithApp(SubmissionMetadataView, { pinia, route: '/workflow/metadata' })
    await flushPromises()
    vi.useFakeTimers()
    await wrapper.get('#field-title').setValue('Unsaved title')
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(wrapper.text()).toContain('Draft save failed')
    expect(wrapper.text()).not.toContain('Draft saved at')
    server.use(http.put(apiV1Url('/metadata/user/42/draft'), () => jsonResponse({ data: { ok: true } })))
    await wrapper.findAll('button').find(button => button.text() === 'Retry save').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Draft saved at')
    server.use(http.put(apiV1Url('/metadata/user/42/draft'), () => jsonResponse({ error: { message: 'Storage unavailable' } }, { status: 503 })))
    await wrapper.get('#field-title').setValue('A newer unsaved revision')
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(wrapper.text()).toContain('Draft save failed')
    expect(wrapper.text()).not.toContain('Draft saved at')
    wrapper.unmount()
  })

})
