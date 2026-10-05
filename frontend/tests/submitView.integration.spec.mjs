import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { http } from 'msw'

import SubmitView from '../src/views/workflow/SubmitView.vue'
import { useWorkflowStore } from '../src/stores/workflow'
import { mountWithApp } from './helpers/app.mjs'
import { activateTestPinia } from './helpers/pinia.mjs'
import { apiV1Url, apiV2Url, jsonResponse, readJsonBody } from './msw/http.mjs'
import { server } from './msw/server.mjs'

describe('SubmitView MSW integration', () => {
  let executeRequest
  let workflowStateRequests
  let allocationRequests
  let preflightRequests

  beforeEach(() => {
    executeRequest = null
    workflowStateRequests = []
    allocationRequests = 0
    preflightRequests = 0

    server.use(
      http.post(apiV2Url('/pipelines/render/readiness'), () => jsonResponse({ data: {
        ready: true, blockers: [], selected_count: 1, readiness_token: 'checked-settings',
        unverified: [{ message: 'Compute connectivity is unverified until runtime preparation.' }],
      } })),
      http.get(apiV1Url('/sessions/42'), () => jsonResponse({
        data: {
          session: {
            publishing_context: {
              default_zenodo_environment: 'sandbox',
              effective_credential_source: 'institution',
            },
            workspace: {
              type: 'institution',
              institution: {
                name: 'Museum Grid',
              },
            },
          },
        },
      })),
      http.get(apiV1Url('/sessions/42/record-resolution'), () => jsonResponse({
        data: {
          policy_preset: 'balanced',
          summary: {
            candidate_count: 1,
            resolved_count: 1,
            unresolved_count: 0,
            can_continue: true,
          },
          candidates: [
            {
              decision_key: 'dataset::model-a',
              candidate_source_file: '/tmp/dataset/model-a.glb',
              candidate_filename: 'model-a.glb',
              normalized_source_file_path: 'dataset/model-a.glb',
              severity: 'version',
              recommended_action: 'create_version',
              selected_action: 'create_version',
              allowed_actions: ['create_version', 'skip'],
              resolved: true,
              recommended_target: {
                session_id: 7,
                local_record_id: 11,
                concept_rec_id: '7001',
              },
              selected_target: {
                session_id: 7,
                local_record_id: 11,
                concept_rec_id: '7001',
              },
            },
          ],
        },
      })),
      http.get(apiV1Url('/hpc-link/status'), () => jsonResponse({
        data: {
          enabled: false,
          available: false,
          can_allocate: false,
          deployment_class: 'workstation-local',
          component_runtime: {
            fast_renderer: {
              component_key: 'fast_renderer',
              status: 'local_allowed',
              allocation_required: false,
              active_hpc_allocation: false,
              local_execution_allowed: true,
              local_healthy: true,
            },
            any_to_usdz: {
              component_key: 'any_to_usdz',
              status: 'local_allowed',
              allocation_required: false,
              active_hpc_allocation: false,
              local_execution_allowed: true,
              local_healthy: true,
            },
          },
        },
      })),
      http.post(apiV1Url('/hpc-link/allocations'), () => {
        allocationRequests += 1
        return jsonResponse({
          data: {
            allocation: {
              allocation_id: 'alloc-42',
              status: 'running',
              requested_partition: 'partition-a',
            },
          },
        })
      }),
      http.post(apiV1Url('/hpc-link/allocations/alloc-42/preflight'), () => {
        preflightRequests += 1
        return jsonResponse({
          data: {
            allocation: {
              allocation_id: 'alloc-42',
              status: 'running',
            },
            preflight: {
              success: true,
            },
          },
        })
      }),
      http.get(apiV2Url('/pipelines'), () => jsonResponse({
        data: {
          pipelines: [
            {
              identifier: 'render',
              name: 'Render',
              steps: [
                { id: 'fast_renderer', name: 'Render', enabled: true },
                { id: 'any_to_usdz', name: 'USDZ', enabled: true },
              ],
            },
          ],
        },
      })),
      http.get(apiV2Url('/pipelines/render'), () => jsonResponse({
        data: {
          pipeline: {
            config: {
              name: 'Render',
              steps: [
                { id: 'fast_renderer', name: 'Render', enabled: true, description: 'Render previews' },
                { id: 'any_to_usdz', name: 'USDZ', enabled: true, description: 'Convert to USDZ' },
              ],
            },
          },
        },
      })),
      http.post(apiV2Url('/pipelines/render/execute'), async ({ request }) => {
        executeRequest = await readJsonBody(request)
        return jsonResponse({
          data: {
            run_id: 'run-42',
          },
        })
      }),
      http.get(apiV2Url('/runs/run-42'), () => jsonResponse({
        data: {
          run: {
            run_id: 'run-42',
            status: 'completed',
            result: {
              success: true,
              progress: {
                current_stage: 'completed',
                status_message: 'Completed successfully.',
              },
              details: [
                {
                  render: { status: 'completed' },
                  usdz: { status: 'completed' },
                },
              ],
            },
            timings: {
              total: 1.2,
            },
          },
        },
      })),
      http.put(apiV1Url('/sessions/42/workflow-state'), async ({ request }) => {
        workflowStateRequests.push(await readJsonBody(request))
        return jsonResponse({ data: { ok: true } })
      }),
    )
  })

  it('executes the saved batch record plan through the native pipeline boundary', async () => {
    const pinia = activateTestPinia()
    const workflowStore = useWorkflowStore(pinia)
    workflowStore.setSessionId(42)
    workflowStore.setBatchMode(true)
    workflowStore.setUploadedFiles([
      {
        file_id: 1,
        absolute_path: '/tmp/dataset/model-a.glb',
        filename: 'model-a.glb',
        name: 'model-a.glb',
      },
    ])
    workflowStore.setSelectedFiles([
      {
        file_id: 1,
        absolute_path: '/tmp/dataset/model-a.glb',
        filename: 'model-a.glb',
        name: 'model-a.glb',
      },
    ])
    workflowStore.setSelectedPipeline({
      identifier: 'render',
      name: 'Render',
    })
    workflowStore.setSubmissionMetadata({
      title: 'Batch title',
    })

    const { wrapper } = await mountWithApp(SubmitView, {
      pinia,
      route: '/workflow/submit',
    })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('Batch record plan')

    const submitButton = wrapper.findAll('button').find((button) => button.text().includes('Confirm & Process'))
    await submitButton.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(executeRequest).toMatchObject({
      session_id: 42,
      is_sandbox: true,
      async_execution: true,
      abort_on_critical_error: false,
      execution_items: [
        {
          decision_key: 'dataset::model-a',
          action: 'create_version',
          source_file_path: '/tmp/dataset/model-a.glb',
          source_file_name: 'model-a.glb',
          target_session_id: 7,
          target_local_record_id: 11,
          target_concept_rec_id: '7001',
        },
      ],
    })
    expect(allocationRequests).toBe(0)
    expect(preflightRequests).toBe(0)
    expect(workflowStateRequests.some((payload) => payload.phase === 'processing')).toBe(true)
    expect(workflowStateRequests.at(-1)).toMatchObject({
      phase: 'completed',
      pipeline_run_id: 'run-42',
    })
    expect(wrapper.text()).toContain('Processing Complete!')

    wrapper.unmount()
  })

  it('requests HPC-Link allocation for server-mode compute components', async () => {
    server.use(
      http.get(apiV1Url('/hpc-link/status'), () => jsonResponse({
        data: {
          enabled: true,
          available: true,
          can_allocate: true,
          deployment_class: 'server',
          active_hpc_allocation: false,
          component_runtime: {
            fast_renderer: {
              component_key: 'fast_renderer',
              status: 'hpc_required',
              allocation_required: true,
              active_hpc_allocation: false,
              local_execution_allowed: false,
              local_healthy: false,
            },
            any_to_usdz: {
              component_key: 'any_to_usdz',
              status: 'hpc_required',
              allocation_required: true,
              active_hpc_allocation: false,
              local_execution_allowed: false,
              local_healthy: false,
            },
          },
        },
      })),
    )
    const pinia = activateTestPinia()
    const workflowStore = useWorkflowStore(pinia)
    workflowStore.setSessionId(42)
    workflowStore.setBatchMode(true)
    workflowStore.setUploadedFiles([
      {
        file_id: 1,
        absolute_path: '/tmp/dataset/model-a.glb',
        filename: 'model-a.glb',
        name: 'model-a.glb',
      },
    ])
    workflowStore.setSelectedFiles([
      {
        file_id: 1,
        absolute_path: '/tmp/dataset/model-a.glb',
        filename: 'model-a.glb',
        name: 'model-a.glb',
      },
    ])
    workflowStore.setSelectedPipeline({
      identifier: 'render',
      name: 'Render',
    })
    workflowStore.setSubmissionMetadata({
      title: 'Batch title',
    })

    const { wrapper } = await mountWithApp(SubmitView, {
      pinia,
      route: '/workflow/submit',
    })
    await flushPromises()
    await flushPromises()

    const submitButton = wrapper.findAll('button').find((button) => button.text().includes('Confirm & Process'))
    await submitButton.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(allocationRequests).toBe(1)
    expect(preflightRequests).toBe(1)
    expect(executeRequest).toMatchObject({
      session_id: 42,
      async_execution: true,
    })

    wrapper.unmount()
  })
  async function mountReview() {
    const pinia = activateTestPinia()
    const store = useWorkflowStore(pinia)
    store.setSessionId(42)
    store.setBatchMode(true)
    const files = [{ file_id: 1, absolute_path: '/tmp/dataset/model-a.glb', filename: 'model-a.glb' }]
    store.setUploadedFiles(files)
    store.setSelectedFiles(files)
    store.setSelectedPipeline({ identifier: 'render', name: 'Render' })
    store.setSubmissionMetadata({ title: 'Museum collection' })
    const mounted = await mountWithApp(SubmitView, { pinia, route: '/workflow/submit' })
    await flushPromises()
    await flushPromises()
    return mounted.wrapper
  }

  it('shows actionable blockers and makes no allocation or execution requests', async () => {
    server.use(http.post(apiV2Url('/pipelines/render/readiness'), () => jsonResponse({ data: {
      ready: false, selected_count: 1,
      blockers: [{ source: 'model-a.glb', message: 'Export a static GLB first.', route: '/workflow/files' }],
      unverified: [{ message: 'Compute connectivity is unverified.' }],
    } })))
    const wrapper = await mountReview()
    expect(wrapper.get('[data-testid="submit-confirm"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('a[href="/workflow/files"]').text()).toContain('Review files')
    expect(wrapper.get('[data-testid="submission-readiness"] details').attributes('open')).toBeUndefined()
    expect(allocationRequests).toBe(0)
    expect(executeRequest).toBeNull()
    wrapper.unmount()
  })

  it('rechecks immediately before submission and stops on newly discovered blockers', async () => {
    let checks = 0
    server.use(http.post(apiV2Url('/pipelines/render/readiness'), () => jsonResponse({ data: ++checks === 1 ? {
      ready: true, blockers: [], selected_count: 1, readiness_token: 'first-check',
    } : { ready: false, selected_count: 1, blockers: [{ message: 'The spreadsheet row is missing.', route: '/workflow/edm-selection' }] } })))
    const wrapper = await mountReview()
    await wrapper.get('[data-testid="submit-confirm"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(checks).toBe(2)
    expect(wrapper.text()).toContain('The spreadsheet row is missing.')
    expect(allocationRequests).toBe(0)
    expect(executeRequest).toBeNull()
    wrapper.unmount()
  })

  it('keeps an unavailable check unverified and recovers through the inline retry', async () => {
    let checks = 0
    server.use(http.post(apiV2Url('/pipelines/render/readiness'), () => ++checks === 1
      ? jsonResponse({ error: { message: 'Readiness temporarily unavailable' } }, { status: 503 })
      : jsonResponse({ data: { ready: true, blockers: [], selected_count: 1, readiness_token: 'recovered-check' } })))
    const wrapper = await mountReview()
    expect(wrapper.text()).toContain('Readiness is unverified.')
    expect(wrapper.get('[data-testid="submit-confirm"]').attributes('disabled')).toBeDefined()
    await wrapper.findAll('button').find(button => button.text() === 'Check again').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Local checks passed for 1 selected source.')
    expect(wrapper.get('[data-testid="submit-confirm"]').attributes('disabled')).toBeUndefined()
    expect(allocationRequests).toBe(0)
    expect(executeRequest).toBeNull()
    wrapper.unmount()
  })

  it('requires new readiness after a rejected stale execution', async () => {
    server.use(http.post(apiV2Url('/pipelines/render/execute'), () => jsonResponse({ error: {
      code: 'OPERATION_CONFLICT', message: 'The source changed. Check readiness again.', details: { readiness_stale: true },
    } }, { status: 409 })))
    const wrapper = await mountReview()
    await wrapper.get('[data-testid="submit-confirm"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(wrapper.text()).toContain('The source changed. Check readiness again.')
    expect(wrapper.get('[data-testid="submit-confirm"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('Local checks passed')
    wrapper.unmount()
  })

  it('keeps failed record details in review and invalidates the earlier readiness', async () => {
    server.use(http.get(apiV2Url('/runs/run-42'), () => jsonResponse({ data: { run: {
      run_id: 'run-42', status: 'failed', result: {
        success: false, error: 'Processing stopped before draft creation.',
        failed_records: [{ file_path: 'model-a.glb', error: 'Source changed while queued.' }],
      },
    } } })))
    const wrapper = await mountReview()
    await wrapper.get('[data-testid="submit-confirm"]').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(wrapper.text()).toContain('Processing stopped before draft creation.')
    expect(wrapper.text()).toContain('model-a.glb: Source changed while queued.')
    expect(wrapper.get('[data-testid="submit-confirm"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('Local checks passed')
    expect(executeRequest).not.toBeNull()
    wrapper.unmount()
  })

})
