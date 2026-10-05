import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { http } from 'msw'

import PipelineView from '../src/views/workflow/PipelineView.vue'
import { useWorkflowStore } from '../src/stores/workflow'
import { mountWithApp } from './helpers/app.mjs'
import { activateTestPinia } from './helpers/pinia.mjs'
import { apiV1Url, apiV2Url, jsonResponse, readJsonBody } from './msw/http.mjs'
import { server } from './msw/server.mjs'

describe('PipelineView MSW integration', () => {
  let workflowStateRequests

  beforeEach(() => {
    workflowStateRequests = []

    server.use(
      http.get(apiV2Url('/pipelines'), () => jsonResponse({
        data: {
          pipelines: [
            {
              identifier: 'render',
              name: 'Render',
              description: 'Render previews',
              version: '2.0.0',
              config: {
                steps: [
                  { id: 'render', name: 'Render', enabled: true },
                ],
              },
            },
            {
              identifier: 'metadata_only',
              name: 'Metadata Only',
              description: 'Metadata-only processing',
              version: '1.0.0',
            },
          ],
        },
      })),
      http.put(apiV1Url('/sessions/42/workflow-state'), async ({ request }) => {
        workflowStateRequests.push(await readJsonBody(request))
        return jsonResponse({ data: { ok: true } })
      }),
    )
  })

  it('loads pipelines through the real API client and persists the submit transition', async () => {
    const pinia = activateTestPinia()
    const workflowStore = useWorkflowStore(pinia)
    workflowStore.setSessionId(42)
    workflowStore.setUploadedFiles([{ file_id: 1, name: 'asset.glb' }])
    workflowStore.setSelectedFiles([{ file_id: 1, name: 'asset.glb' }])

    const { router, wrapper } = await mountWithApp(PipelineView, {
      pinia,
      route: '/workflow/pipeline',
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Render previews')
    expect(workflowStateRequests).toHaveLength(1)
    expect(workflowStateRequests[0]).toMatchObject({
      phase: 'pipeline',
      current_step: 6,
      selected_file_keys: ['1'],
    })

    expect(wrapper.get('#metadata_only').element.checked).toBe(true)
    await wrapper.get('#render').setValue(true)
    const continueButton = wrapper.findAll('button').find((button) => button.text().includes('Continue to Summary'))
    await continueButton.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/workflow/submit')
    expect(workflowStore.selectedPipeline).toMatchObject({
      identifier: 'render',
      name: 'Render',
    })
    expect(workflowStateRequests.at(-1)).toMatchObject({
      phase: 'submit',
      current_step: 7,
      selected_pipeline: {
        identifier: 'render',
        name: 'Render',
        description: 'Render previews',
      },
    })

    wrapper.unmount()
  })
})
