import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { http } from 'msw'

import UploadView from '../src/views/workflow/UploadView.vue'
import { useWorkflowStore } from '../src/stores/workflow'
import { activateTestPinia } from './helpers/pinia.mjs'
import { mountWithApp } from './helpers/app.mjs'
import { apiV1Url, jsonResponse } from './msw/http.mjs'
import { server } from './msw/server.mjs'

describe('UploadView MSW integration', () => {
  beforeEach(() => {
    server.use(
      http.get(apiV1Url('/admin/storage-status'), () => jsonResponse({
        data: {
          active_storage: 'dropbox',
          active_message: 'Cloud storage ready',
          config: {
            storage_mode: 'cloud_backup',
          },
        },
      })),
      http.get(apiV1Url('/hpc-link/status'), () => jsonResponse({
        data: {
          enabled: false,
          available: false,
          can_allocate: false,
          deployment_class: 'server',
          deployment_label: 'Server/VPS',
          component_runtime: {},
        },
      })),
      http.post(apiV1Url('/sessions/directory'), ({ request }) => {
        const url = new URL(request.url)
        if (url.searchParams.get('validate_only') === 'true') {
          return jsonResponse({
            data: {
              msf_validation: {
                is_valid: true,
                matched_count: 1,
                matched_files: ['model-a.glb'],
              },
              msf_mapping: {},
              file_metadata_map: {},
              msf_profile: {
                parse_options: {},
              },
            },
          })
        }

        return jsonResponse({
          data: {
            task_id: null,
            session_id: 42,
            submit_token: 'submit-token-42',
          },
        })
      }),
      http.get(apiV1Url('/sessions/42/progress'), () => jsonResponse({
        data: {
          upload_progress: {
            percent: 100,
            failed_count: 0,
            current_stage: 'completed',
            status_message: 'Processing complete',
          },
        },
      })),
      http.post(apiV1Url('/sessions/42/record-resolution/analyze'), () => jsonResponse({
        data: {
          policy_preset: 'balanced',
          summary: {
            candidate_count: 1,
            affected_count: 1,
            resolved_count: 0,
            unresolved_count: 1,
            can_continue: false,
          },
          candidates: [
            {
              decision_key: 'dataset::model-a',
              candidate_filename: 'model-a.glb',
              candidate_source_file: '/tmp/dataset/model-a.glb',
              normalized_source_file_path: 'dataset/model-a.glb',
              severity: 'version',
              recommended_action: 'create_version',
              selected_action: 'create_version',
              allowed_actions: ['create_version', 'skip'],
              confidence: { label: 'high', score: 1 },
              explanation: 'Same-lineage exact path match.',
              matched_record_count: 1,
              matched_records: [],
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
              reason_codes: ['exact_path_same_lineage'],
              evidence: {},
              resolved: false,
            },
          ],
        },
      })),
    )
  })

  it('drives the ZIP batch path through validation, upload, polling, and record-resolution review', async () => {
    const pinia = activateTestPinia()
    const workflowStore = useWorkflowStore(pinia)

    const { router, wrapper } = await mountWithApp(UploadView, {
      pinia,
      route: '/workflow/upload',
      global: {
        stubs: {
          RecordResolutionReview: {
            template: '<div data-test="record-review">record review</div>',
          },
        },
      },
    })

    const batchButton = wrapper.findAll('button').find((button) => button.text().includes('Batch upload with spreadsheet'))
    await batchButton.trigger('click')
    await flushPromises()

    const fileInputs = wrapper.findAll('input[type="file"]')
    Object.defineProperty(fileInputs[0].element, 'files', {
      value: [new File(['zip'], 'models.zip', { type: 'application/zip' })],
      configurable: true,
    })
    await fileInputs[0].trigger('change')
    Object.defineProperty(fileInputs[1].element, 'files', {
      value: [new File(['msf'], 'models.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })],
      configurable: true,
    })
    await fileInputs[1].trigger('change')
    await flushPromises()

    const validateButton = wrapper.findAll('button').find((button) => button.text().includes('Validate MSF'))
    await validateButton.trigger('click')
    await flushPromises()

    const continueButton = wrapper.findAll('button').find((button) => button.text().includes('Scan & Continue'))
    await continueButton.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(wrapper.find('[data-test="record-review"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Review the affected candidates below and save the plan before continuing.')
    expect(router.currentRoute.value.path).toBe('/workflow/upload')
    expect(workflowStore.sessionId).toBe(42)
    expect(workflowStore.isBatchMode).toBe(true)
  })

  it('hides HPC resources and labels local storage for workstation-local directory scans', async () => {
    server.use(
      http.get(apiV1Url('/hpc-link/status'), () => jsonResponse({
        data: {
          enabled: false,
          available: false,
          can_allocate: false,
          deployment_class: 'workstation-local',
          deployment_label: 'Local workstation',
          component_runtime: {},
        },
      })),
      http.get(apiV1Url('/admin/storage-status'), () => jsonResponse({
        data: {
          active_storage: 'server',
          active_message: 'Local storage mode enabled',
          config: {
            storage_mode: 'local',
          },
        },
      })),
      http.get(apiV1Url('/sessions/local-msf'), () => jsonResponse({
        data: {
          input_root: '/data/local_input',
          msf_files: [],
          directories: [],
        },
      })),
    )
    const pinia = activateTestPinia()

    const { wrapper } = await mountWithApp(UploadView, {
      pinia,
      route: '/workflow/upload',
    })

    await flushPromises()
    const batchButton = wrapper.findAll('button').find((button) => button.text().includes('Batch upload with spreadsheet'))
    await batchButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('Rendering resources (HPC)')
    expect(wrapper.text()).toContain('Local folder scan path')
    expect(wrapper.text()).toContain('Local Workstation')
    expect(wrapper.text()).toContain('Local Folder Storage')
    expect(wrapper.findAll('input[type="search"]')[0].attributes('placeholder')).toBe('Filter nested local folders by name or path')
    expect(wrapper.text()).toContain('inside the selected local folder')
    expect(wrapper.text()).not.toContain('HPC environment')

    wrapper.unmount()
  })

  it('keeps HPC resources and labels attached filesystem for server-mode directory scans', async () => {
    server.use(
      http.get(apiV1Url('/hpc-link/status'), () => jsonResponse({
        data: {
          enabled: false,
          available: false,
          can_allocate: true,
          deployment_class: 'server',
          deployment_label: 'Server/VPS',
          component_runtime: {},
        },
      })),
      http.get(apiV1Url('/admin/storage-status'), () => jsonResponse({
        data: {
          active_storage: 'server',
          active_message: 'Local storage mode enabled',
          config: {
            storage_mode: 'local',
          },
        },
      })),
      http.get(apiV1Url('/sessions/local-msf'), () => jsonResponse({
        data: {
          input_root: '/data/local_input',
          msf_files: [],
          directories: [],
        },
      })),
    )
    const pinia = activateTestPinia()

    const { wrapper } = await mountWithApp(UploadView, {
      pinia,
      route: '/workflow/upload',
    })

    await flushPromises()
    const batchButton = wrapper.findAll('button').find((button) => button.text().includes('Batch upload with spreadsheet'))
    await batchButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Rendering resources (HPC)')
    expect(wrapper.text()).toContain('Server/VPS deployments require HPC-Link')
    expect(wrapper.text()).toContain('Server/HPC directory scan path')
    expect(wrapper.text()).toContain('Server/HPC Filesystem')
    expect(wrapper.text()).toContain('Server/HPC Filesystem Storage')
    expect(wrapper.findAll('input[type="search"]')[0].attributes('placeholder')).toBe('Filter nested server/HPC directories by name or path')
    expect(wrapper.text()).toContain('inside the selected server/HPC directory')
    expect(wrapper.text()).not.toContain('HPC Local')

    wrapper.unmount()
  })
})
