import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { http } from 'msw'

import MsfAnalysisView from '../src/views/workflow/MsfAnalysisView.vue'
import { useWorkflowStore } from '../src/stores/workflow'
import { mountWithApp } from './helpers/app.mjs'
import { activateTestPinia } from './helpers/pinia.mjs'
import { apiV1Url, jsonResponse, readJsonBody } from './msw/http.mjs'
import { server } from './msw/server.mjs'

const analysisPayload = {
  msf_path: '/data/local_input/source-repaired.csv',
  summary: {
    rows_total: 12,
    error_count: 1,
    warning_count: 0,
    sample_row_number: 2,
  },
  validator: {
    checks: {
      reference_availability: {
        matched_count: 3,
        missing_count: 0,
      },
    },
  },
  issues: [
    {
      id: 'missing-title',
      severity: 'error',
      title: 'Title is missing',
      description: 'The title column is blank for one sampled row.',
      why: 'EDM titles are required.',
      leads_to: 'Generated metadata would be invalid.',
      suggested_fix: 'Apply the fallback title repair.',
      affected_lods: ['edm'],
      locations: [{ row_number: 2, column: 'title' }],
      recommendation_ids: ['fix-title'],
    },
  ],
  recommended_fixes: [
    {
      id: 'fix-title',
      label: 'Apply fallback title',
      description: 'Populate empty title cells with a deterministic fallback.',
      operations: [{ type: 'fill_missing_titles' }],
    },
  ],
  preview: {
    columns: ['title'],
    preview_rows: [{ __row_number: 2, title: '' }],
  },
  highlight_cells: [
    {
      row_number: 2,
      column: 'title',
      severity: 'error',
      issue_id: 'missing-title',
      message: 'A title is required for EDM output.',
    },
  ],
  lod_samples: {
    edm: {
      valid: false,
      minimum_viable_applied: true,
      errors: ['Title is required'],
      xml: '<edm />',
    },
    iiif: {
      valid: true,
      minimum_viable_applied: false,
      json: '{"label":"ok"}',
    },
    mets: {
      valid: true,
      minimum_viable_applied: false,
      xml: '<mets />',
    },
  },
  workflow_state: {
    requires_scan_start: true,
    target_directory: '/data/local_input/batch-a',
    active_msf_path: '/data/local_input/source-repaired.csv',
    original_msf_path: '/data/local_input/source.csv',
    active_msf_kind: 'repaired_copy',
  },
  minimum_viable_options: [
    {
      standard: 'edm',
      label: 'EDM',
      description: 'Allow placeholder values for EDM.',
      required: true,
    },
    {
      standard: 'iiif',
      label: 'IIIF',
      description: 'Allow placeholder values for IIIF.',
      required: false,
    },
    {
      standard: 'mets',
      label: 'METS',
      description: 'Allow placeholder values for METS.',
      required: false,
    },
  ],
  msf_profile: {
    parse_options: {
      use_first_row_as_header: true,
    },
  },
}

describe('MsfAnalysisView MSW integration', () => {
  let analysisRequests
  let workflowStateRequests

  beforeEach(() => {
    analysisRequests = []
    workflowStateRequests = []

    server.use(
      http.post(apiV1Url('/msf/workflow/session/42/analyze'), async ({ request }) => {
        analysisRequests.push(await readJsonBody(request))
        return jsonResponse({
          data: {
            analysis: analysisPayload,
          },
        })
      }),
      http.get(apiV1Url('/sessions/local-msf'), () => jsonResponse({
        data: {
          msf_files: [
            {
              name: 'source.csv',
              path: 'source.csv',
              full_path: '/data/local_input/source.csv',
            },
          ],
          subdirectories: [
            {
              relative_path: 'batch-a',
              name: 'batch-a',
              depth: 1,
              file_count: 3,
            },
          ],
          input_root: '/data/local_input',
        },
      })),
      http.post(apiV1Url('/msf/workflow/session/42/start-local-scan'), () => jsonResponse({
        data: {
          task_id: 'task-42',
        },
      })),
      http.get(apiV1Url('/sessions/tasks/task-42'), () => jsonResponse({
        data: {
          state: 'SUCCESS',
          status: 'completed',
        },
      })),
      http.get(apiV1Url('/sessions/42/progress'), () => jsonResponse({
        data: {
          upload_progress: {
            percent: 100,
            failed_count: 0,
            current_stage: 'completed',
            status_message: 'Local scan completed.',
          },
        },
      })),
      http.put(apiV1Url('/sessions/42/workflow-state'), async ({ request }) => {
        workflowStateRequests.push(await readJsonBody(request))
        return jsonResponse({ data: { ok: true } })
      }),
    )
  })

  it('analyzes the MSF through the API client and starts the local scan workflow', async () => {
    const pinia = activateTestPinia()
    const workflowStore = useWorkflowStore(pinia)
    workflowStore.setSessionId(42)
    workflowStore.setBatchMode(true)
    workflowStore.goToStep(2)

    const { router, wrapper } = await mountWithApp(MsfAnalysisView, {
      pinia,
      route: '/workflow/msf-analysis',
    })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('Session MSF Report')
    expect(wrapper.text()).toContain('Guided repair before scan')
    expect(analysisRequests[0]).toEqual({})
    expect(workflowStateRequests[0]).toMatchObject({
      phase: 'msf_analysis',
      current_step: 2,
      is_batch_mode: true,
    })

    const continueButton = wrapper.findAll('button').find((button) => button.text().includes('Start Scan & Continue'))
    await continueButton.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/workflow/files')
    expect(workflowStore.currentStep).toBe(3)
    expect(workflowStateRequests.at(-1)).toMatchObject({
      phase: 'files',
      current_step: 3,
      lod_minimum_viable: {
        edm: true,
        iiif: true,
        mets: true,
      },
    })

    wrapper.unmount()
  })
})
