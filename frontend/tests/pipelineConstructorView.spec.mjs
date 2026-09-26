import { flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { activateTestPinia, mountWithPinia } from './helpers/pinia.mjs'

const mocked = vi.hoisted(() => ({
  pipelineService: {
    listPipelines: vi.fn(),
    getPipeline: vi.fn(),
    listComponents: vi.fn(),
    getPipelineConstructorSupport: vi.fn(),
    validatePipelineConfig: vi.fn(),
    createPipelineVersion: vi.fn(),
    validateComponentManifest: vi.fn(),
    importComponent: vi.fn(),
    preflightPipelineConstructor: vi.fn(),
    executePipelineOnFiles: vi.fn(),
    getPipelineRun: vi.fn(),
  },
  fileService: {
    getNodes: vi.fn(),
    listSessions: vi.fn().mockResolvedValue({ data: { sessions: [{ id: 42, name: 'Test session' }] } }),
  },
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  route: {
    path: '/admin/pipelines',
  },
}))

vi.mock('@/services/pipeline.service', () => ({ default: mocked.pipelineService }))
vi.mock('@/services/file.service', () => ({ default: mocked.fileService }))
vi.mock('@/composables/useToast', () => ({ useToast: () => mocked.toast }))
vi.mock('vue-router', () => ({ useRoute: () => mocked.route, onBeforeRouteLeave: vi.fn() }))

import PipelineConfigView from '../src/views/admin/PipelineConfigView.vue'
import { useAuthStore } from '../src/stores/auth.js'

function createComponent({
  key,
  title,
  inputs = [],
  outputs = [],
  tags = [],
  category = 'Testing',
  profiles = [{ id: 'builtin_default' }],
}) {
  return {
    key,
    name: title,
    description: `${title} description`,
    constructor_schema: {
      title,
      metadata: {
        category,
        tags,
        keywords: [],
      },
      inputs,
      outputs,
      profiles,
    },
    playground_schema: {
      version: 1,
      title,
      description: `${title} description`,
      metadata: {
        name: key,
        label: title,
        version: '1.0.0',
        tags,
        category,
      },
      inputs: [],
      outputs,
      parameter_groups: [],
      result: {
        artifact_views: [],
        show_result_json: true,
        show_logs: true,
      },
    },
  }
}

const baseSupportData = {
  trigger_operators: [
    { id: 'eq', label: 'eq' },
    { id: 'neq', label: 'neq' },
  ],
  file_facts: [
    { field: 'extension', label: 'Extension', value_type: 'string', operators: ['eq', 'neq'] },
  ],
  transforms: [
    { id: 'trim' },
  ],
  overwrite_policies: [
    { id: 'overwrite' },
    { id: 'append' },
  ],
  zenodo_target_paths: [
    { path: 'title', label: 'Title' },
    { path: 'description', label: 'Description' },
  ],
  edm_metadata_target_paths: [
    { path: 'point_count', label: '3D point count', action_type: 'edm_metadata_field' },
  ],
  metadata_target_paths: [
    { path: 'description', label: 'Description', action_type: 'zenodo_metadata_field' },
    { path: 'title', label: 'Title', action_type: 'zenodo_metadata_field' },
    { path: 'point_count', label: '3D point count', action_type: 'edm_metadata_field' },
  ],
}

const fileInput = {
  name: 'input_file',
  label: 'Input File',
  type: 'file_path',
  required: true,
  supported_source_kinds: ['pipeline_source_file', 'artifact_file'],
}

const componentsFixture = {
  metadata_source: createComponent({
    key: 'metadata_source',
    title: 'Metadata Source',
    outputs: [
      { name: 'metadata_json', label: 'Metadata JSON', type: 'json', selector_examples: ['$.title'] },
    ],
  }),
  convert_model: createComponent({
    key: 'convert_model',
    title: 'Convert Model',
    inputs: [fileInput],
    outputs: [
      { name: 'converted_file', label: 'Converted File', type: 'file_path' },
      { name: 'conversion_report', label: 'Conversion Report', type: 'json', selector_examples: ['$.status'] },
    ],
  }),
  consumer: createComponent({
    key: 'consumer',
    title: 'Consumer',
    inputs: [fileInput],
  }),
  render_component: createComponent({
    key: 'render_component',
    title: 'Render Component',
    inputs: [fileInput],
  }),
  json_mapper: createComponent({
    key: 'json_mapper',
    title: 'JSON Mapper',
    outputs: [
      { name: 'metadata_json', label: 'Metadata JSON', type: 'json', selector_examples: ['$.title'] },
      { name: 'audit_json', label: 'Audit JSON', type: 'json', selector_examples: ['$.message'] },
    ],
  }),
}

function resetServiceMocks() {
  Object.values(mocked.pipelineService).forEach((mockFn) => mockFn.mockReset())
  Object.values(mocked.fileService).forEach((mockFn) => mockFn.mockReset())
  Object.values(mocked.toast).forEach((mockFn) => mockFn.mockReset())
}

async function mountConstructorView({
  pipelineConfig,
  components = Object.values(componentsFixture),
  user = { id: 1, role: 'admin', capabilities: ['native_pipeline_author'] },
  routePath = '/admin/pipelines',
}) {
  resetServiceMocks()
  mocked.fileService.listSessions.mockResolvedValue({ data: { sessions: [{ id: 42, name: 'Test session' }] } })
  mocked.route.path = routePath
  mocked.pipelineService.listPipelines.mockResolvedValue({
    data: {
      pipelines: [{ identifier: pipelineConfig.identifier, name: pipelineConfig.name }],
    },
  })
  mocked.pipelineService.listComponents.mockResolvedValue({
    data: {
      components,
    },
  })
  mocked.pipelineService.getPipelineConstructorSupport.mockResolvedValue({
    data: baseSupportData,
  })
  mocked.pipelineService.getPipeline.mockResolvedValue({
    data: {
      pipeline: {
        config: pipelineConfig,
      },
    },
  })
  mocked.pipelineService.validatePipelineConfig.mockResolvedValue({
    data: {
      valid: true,
      errors: [],
      warnings: [],
    },
  })
  mocked.pipelineService.createPipelineVersion.mockResolvedValue({
    data: {
      pipeline: {
        identifier: pipelineConfig.identifier,
        active_version: pipelineConfig.version,
      },
    },
  })
  mocked.pipelineService.executePipelineOnFiles.mockResolvedValue({
    data: {
      run_id: 'run-3d',
      result: {
        summary: {
          successful_count: 1,
          failed_count: 0,
          processed_count: 1,
        },
      },
    },
  })
  mocked.pipelineService.getPipelineRun.mockResolvedValue({
    data: {
      run: {
        run_id: 'run-3d',
        status: 'completed',
        result: {
          summary: {
            successful_count: 1,
            failed_count: 0,
            processed_count: 1,
          },
        },
        steps: [
          {
            id: 1,
            pipeline_step_id: 11,
            step_key: 'profile_model',
            component_key: 'model_profiler',
            status: 'completed',
            result: {
              outputs: {
                analysis_report: '/tmp/report.json',
              },
            },
          },
        ],
        artifacts: [
          {
            name: 'sample_model_profiler_report.json',
            path: '/tmp/report.json',
            metadata: {
              role: 'analysis_report',
            },
          },
        ],
      },
    },
  })
  mocked.fileService.getNodes.mockResolvedValue({ data: { nodes: [] } })

  const pinia = activateTestPinia()
  const authStore = useAuthStore()
  authStore.setUser ? authStore.setUser(user) : (authStore.user = user)

  const { wrapper } = mountWithPinia(PipelineConfigView, {
    pinia,
    global: {
      stubs: {
        LoadingSpinner: { template: '<div data-testid="loading-spinner" />' },
        PlaygroundFieldRenderer: { template: '<div class="playground-field-renderer-stub" />' },
      },
    },
  })

  await flushPromises()
  await nextTick()
  return wrapper
}

async function validateAndGetPayload(wrapper) {
  await wrapper.get('[data-testid="validate-pipeline"]').trigger('click')
  await flushPromises()
  expect(mocked.pipelineService.validatePipelineConfig).toHaveBeenCalledTimes(1)
  return mocked.pipelineService.validatePipelineConfig.mock.calls[0][0]
}

async function runPreflightAndGetPayload(wrapper) {
  await wrapper.get('[data-testid="run-preflight"]').trigger('click')
  await flushPromises()
  expect(mocked.pipelineService.preflightPipelineConstructor).toHaveBeenCalledTimes(1)
  return mocked.pipelineService.preflightPipelineConstructor.mock.calls[0][0]
}

async function dragAndDrop(wrapper, handleSelector, targetSelector) {
  await wrapper.get(handleSelector).trigger('dragstart')
  await wrapper.get(targetSelector).trigger('dragover')
  await wrapper.get(targetSelector).trigger('drop')
  await wrapper.get(handleSelector).trigger('dragend')
  await nextTick()
}

describe('PipelineConfigView constructor interactions', () => {
  beforeEach(() => {
  sessionStorage.clear()
  mocked.fileService.listSessions.mockResolvedValue({ data: { sessions: [{ id: 42, name: 'Test session' }] } })
    mocked.route.path = '/admin/pipelines'
  })

  it('filters mapping source steps and outputs by compatibility in the rendered view', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'compatibility_pipeline',
        name: 'Compatibility Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'metadata',
            name: 'Metadata',
            component_ref: 'metadata_source',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
          },
          {
            id: 'convert',
            name: 'Convert',
            component_ref: 'convert_model',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
          },
          {
            id: 'consumer',
            name: 'Consumer',
            component_ref: 'consumer',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
          },
        ],
      },
    })

    const sourceStepSelect = wrapper.get('[data-testid="binding-source-step-consumer-input_file"]')
    const sourceStepOptions = sourceStepSelect.findAll('option').map((option) => option.text())
    expect(sourceStepOptions).toContain('Convert (convert)')
    expect(sourceStepOptions).not.toContain('Metadata (metadata)')

    const sourceOutputSelect = wrapper.get('[data-testid="binding-source-output-consumer-input_file"]')
    const sourceOutputOptions = sourceOutputSelect.findAll('option').map((option) => option.text())
    expect(sourceOutputOptions).toContain('Converted File')
    expect(sourceOutputOptions).not.toContain('Conversion Report')
    expect(sourceOutputSelect.element.value).toBe('converted_file')
  })

  it('filters the catalog by tag and execution profile', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'catalog_filter_pipeline',
        name: 'Catalog Filter Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [],
      },
      components: [
        createComponent({
          key: 'mesh_renderer',
          title: 'Mesh Renderer',
          tags: ['mesh'],
          profiles: [{ id: 'gpu' }, { id: 'builtin_default' }],
        }),
        createComponent({
          key: 'cloud_renderer',
          title: 'Cloud Renderer',
          tags: ['point-cloud'],
          profiles: [{ id: 'cpu' }],
        }),
      ],
    })

    await wrapper.get('[data-testid="catalog-tag-filter"]').setValue('mesh')
    await wrapper.get('[data-testid="catalog-profile-filter"]').setValue('gpu')
    await nextTick()

    expect(wrapper.find('[data-testid="catalog-add-mesh_renderer"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="catalog-add-cloud_renderer"]').exists()).toBe(false)

    await wrapper.get('[data-testid="catalog-clear-filters"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-testid="catalog-add-cloud_renderer"]').exists()).toBe(true)
  })

  it('serializes step order after drag-and-drop reordering', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'step_reorder_pipeline',
        name: 'Step Reorder Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'convert',
            name: 'Convert',
            component_ref: 'convert_model',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
          },
          {
            id: 'consume',
            name: 'Consume',
            component_ref: 'consumer',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
          },
        ],
      },
    })

    await dragAndDrop(wrapper, '[data-testid="step-drag-handle-consume"]', '[data-testid="step-card-convert"]')

    const payload = await validateAndGetPayload(wrapper)
    expect(payload.steps.map((step) => step.id)).toEqual(['consume', 'convert'])
  })

  it('serializes trigger rules in the reordered UI order', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'trigger_pipeline',
        name: 'Trigger Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'render',
            name: 'Render',
            component_ref: 'render_component',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
            triggers: {
              default_behavior: 'run',
              rules: [
                {
                  id: 'mesh_rule',
                  label: 'Mesh',
                  action: 'run',
                  conditions: [
                    { source_type: 'file_fact', field: 'extension', operator: 'eq', value: '.glb' },
                  ],
                },
                {
                  id: 'cloud_rule',
                  label: 'Cloud',
                  action: 'skip',
                  conditions: [
                    { source_type: 'file_fact', field: 'extension', operator: 'eq', value: '.ply' },
                  ],
                },
              ],
            },
          },
        ],
      },
    })

    await wrapper.get('[data-testid="trigger-rule-down-render-0"]').trigger('click')
    await nextTick()

    const payload = await validateAndGetPayload(wrapper)
    expect(payload.steps[0].triggers.rules.map((rule) => rule.id)).toEqual(['cloud_rule', 'mesh_rule'])
  })

  it('serializes trigger rules after drag-and-drop reordering', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'trigger_drag_pipeline',
        name: 'Trigger Drag Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'render',
            name: 'Render',
            component_ref: 'render_component',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
            triggers: {
              default_behavior: 'run',
              rules: [
                {
                  id: 'mesh_rule',
                  label: 'Mesh',
                  action: 'run',
                  conditions: [
                    { source_type: 'file_fact', field: 'extension', operator: 'eq', value: '.glb' },
                  ],
                },
                {
                  id: 'cloud_rule',
                  label: 'Cloud',
                  action: 'skip',
                  conditions: [
                    { source_type: 'file_fact', field: 'extension', operator: 'eq', value: '.ply' },
                  ],
                },
              ],
            },
          },
        ],
      },
    })

    await dragAndDrop(wrapper, '[data-testid="trigger-rule-drag-handle-render-1"]', '[data-testid="trigger-rule-render-0"]')

    const payload = await validateAndGetPayload(wrapper)
    expect(payload.steps[0].triggers.rules.map((rule) => rule.id)).toEqual(['cloud_rule', 'mesh_rule'])
  })

  it('serializes output mappings in the reordered modal order', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'mapping_pipeline',
        name: 'Mapping Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'mapper',
            name: 'Mapper',
            component_ref: 'json_mapper',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
            output_actions: [
              {
                action_type: 'zenodo_metadata_field',
                source_output: 'metadata_json',
                selector: '$.title',
                target_field: 'title',
                overwrite_policy: 'overwrite',
              },
              {
                action_type: 'zenodo_metadata_field',
                source_output: 'audit_json',
                selector: '$.message',
                target_field: 'description',
                overwrite_policy: 'append',
              },
            ],
          },
        ],
      },
    })

    await wrapper.get('[data-testid="output-mapping-manage-mapper"]').trigger('click')
    await nextTick()
    await wrapper.get('[data-testid="output-mapping-down-0"]').trigger('click')
    await nextTick()

    const payload = await validateAndGetPayload(wrapper)
    expect(payload.steps[0].output_actions.map((action) => action.target_field)).toEqual(['description', 'title'])
  })

  it('serializes output mappings after drag-and-drop reordering', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'mapping_drag_pipeline',
        name: 'Mapping Drag Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'mapper',
            name: 'Mapper',
            component_ref: 'json_mapper',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
            output_actions: [
              {
                action_type: 'zenodo_metadata_field',
                source_output: 'metadata_json',
                selector: '$.title',
                target_field: 'title',
                overwrite_policy: 'overwrite',
              },
              {
                action_type: 'zenodo_metadata_field',
                source_output: 'audit_json',
                selector: '$.message',
                target_field: 'description',
                overwrite_policy: 'append',
              },
            ],
          },
        ],
      },
    })

    await wrapper.get('[data-testid="output-mapping-manage-mapper"]').trigger('click')
    await nextTick()
    await dragAndDrop(wrapper, '[data-testid="output-mapping-drag-handle-1"]', '[data-testid="output-mapping-row-0"]')

    const payload = await validateAndGetPayload(wrapper)
    expect(payload.steps[0].output_actions.map((action) => action.target_field)).toEqual(['description', 'title'])
  })

  it('serializes EDM metadata mappings with the EDM action type', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'edm_mapping_pipeline',
        name: 'EDM Mapping Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'mapper',
            name: 'Mapper',
            component_ref: 'json_mapper',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
            output_actions: [],
          },
        ],
      },
    })

    await wrapper.get('[data-testid="output-mapping-manage-mapper"]').trigger('click')
    await nextTick()
    await wrapper.get('[data-testid="output-mapping-add"]').trigger('click')
    await nextTick()
    const mappingSelects = wrapper.find('[data-testid="output-mapping-row-0"]').findAll('select')
    await mappingSelects[2].setValue('point_count')

    const payload = await validateAndGetPayload(wrapper)
    expect(payload.steps[0].output_actions[0].target_field).toBe('point_count')
    expect(payload.steps[0].output_actions[0].action_type).toBe('edm_metadata_field')
  })

  it('preserves advanced JSON-only entries after structured edits and validation', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'advanced_pipeline',
        name: 'Advanced Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'render',
            name: 'Render',
            component_ref: 'render_component',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
            input_bindings: [
              { target: 'legacy_input', type: 'literal', value: 'keep-me' },
            ],
            output_actions: [
              {
                action_type: 'zenodo_metadata_field',
                source_output: 'metadata_json',
                selector: '$.title',
                target_field: 'title',
                overwrite_policy: 'overwrite',
              },
              {
                action_type: 'record_warning',
                source_output: 'audit_json',
                transform: 'trim',
              },
            ],
            resources: {
              cache: true,
            },
            triggers: {
              default_behavior: 'run',
              rules: [
                {
                  id: 'mesh_rule',
                  label: 'Mesh',
                  action: 'run',
                  conditions: [
                    { source_type: 'file_fact', field: 'extension', operator: 'eq', value: '.glb' },
                  ],
                },
                {
                  id: 'cloud_rule',
                  label: 'Cloud',
                  action: 'skip',
                  conditions: [
                    { source_type: 'file_fact', field: 'extension', operator: 'eq', value: '.ply' },
                  ],
                },
              ],
              match_mode: 'first_match',
              legacy_window: { max_files: 10 },
            },
          },
        ],
      },
      components: [
        {
          ...componentsFixture.render_component,
          constructor_schema: {
            ...componentsFixture.render_component.constructor_schema,
            outputs: [
              { name: 'metadata_json', label: 'Metadata JSON', type: 'json', selector_examples: ['$.title'] },
              { name: 'audit_json', label: 'Audit JSON', type: 'json', selector_examples: ['$.message'] },
            ],
          },
          playground_schema: {
            ...componentsFixture.render_component.playground_schema,
            outputs: [
              { name: 'metadata_json', label: 'Metadata JSON', type: 'json' },
              { name: 'audit_json', label: 'Audit JSON', type: 'json' },
            ],
          },
        },
      ],
    })

    await wrapper.get('[data-testid="trigger-rule-down-render-0"]').trigger('click')
    await nextTick()

    const payload = await validateAndGetPayload(wrapper)
    const step = payload.steps[0]

    expect(step.input_bindings).toContainEqual({ target: 'legacy_input', type: 'literal', value: 'keep-me' })
    expect(step.output_actions).toContainEqual({
      action_type: 'record_warning',
      source_output: 'audit_json',
      transform: 'trim',
    })
    expect(step.resources).toEqual({ cache: true })
    expect(step.triggers.match_mode).toBe('first_match')
    expect(step.triggers.legacy_window).toEqual({ max_files: 10 })
  })

  it('renders batch directory warnings returned by constructor preflight', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'preflight_warning_pipeline',
        name: 'Preflight Warning Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'consume',
            name: 'Consume',
            component_ref: 'consumer',
            execution_profile_ref: 'builtin_default',
            scope: 'batch',
          },
        ],
      },
    })

    mocked.pipelineService.preflightPipelineConstructor.mockResolvedValue({
      data: {
        valid: true,
        validation: {
          valid: true,
          errors: [],
          warnings: [],
        },
        steps: [
          {
            step_id: 'consume',
            scope: 'batch',
            records: [
              {
                record_path: '/tmp/session/uploads/a/model.glb',
                action: 'run',
                matched_rule_id: null,
                resolved_inputs: {
                  input_files: ['/tmp/session/outputs/converted/model.usdz'],
                },
              },
            ],
            buckets: [
              {
                bucket_key: 'bucket-1',
                record_paths: ['/tmp/session/uploads/a/model.glb'],
                parameters: {},
                inputs: {},
                warnings: [
                  "Step 'consume' could not resolve directory input 'input_dir' to a single directory for this batch bucket. Candidate directories: /tmp/session/outputs/converted, /tmp/session/outputs/alt"
                ],
              },
            ],
          },
        ],
      },
    })

    await wrapper.get('[data-testid="preflight-session-id"]').setValue('42')
    await wrapper.get('[data-testid="preflight-local-file-paths"]').setValue('/tmp/session/uploads/a/model.glb')

    const payload = await runPreflightAndGetPayload(wrapper)
    expect(payload.session_id).toBe(42)
    expect(payload.local_file_paths).toEqual(['/tmp/session/uploads/a/model.glb'])

    const warningCard = wrapper.get('[data-testid="preflight-warning-consume-0-0"]')
    expect(warningCard.text()).toContain("could not resolve directory input 'input_dir'")
    expect(warningCard.text()).toContain('/tmp/session/outputs/converted')
    expect(warningCard.text()).toContain('Records: /tmp/session/uploads/a/model.glb')
  })

  it('uses the session file browser to build preflight local file paths', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'preflight_session_browser_pipeline',
        name: 'Preflight Session Browser Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'consume',
            name: 'Consume',
            component_ref: 'consumer',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
          },
        ],
      },
    })

    mocked.fileService.getNodes.mockResolvedValue({
      data: {
        nodes: [
          {
            absolute_path: '/tmp/session/uploads',
            relative_path: 'uploads',
            children: [
              {
                absolute_path: '/tmp/session/uploads/model_a.glb',
                relative_path: 'uploads/model_a.glb',
                children: [],
              },
              {
                absolute_path: '/tmp/session/uploads/model_b.ply',
                relative_path: 'uploads/model_b.ply',
                children: [],
              },
            ],
          },
        ],
      },
    })
    mocked.pipelineService.preflightPipelineConstructor.mockResolvedValue({
      data: {
        valid: true,
        validation: {
          valid: true,
          errors: [],
          warnings: [],
        },
        steps: [],
      },
    })

    await wrapper.get('[data-testid="preflight-session-id"]').setValue('42')
    await flushPromises()

    await wrapper.get('[data-testid="preflight-session-files-search"]').setValue('model_a')
    await wrapper.get('[data-testid="preflight-session-files-item-0"]').trigger('click')

    const localPaths = wrapper.get('[data-testid="preflight-local-file-paths"]')
    expect(localPaths.element.value).toBe('/tmp/session/uploads/model_a.glb')

    const payload = await runPreflightAndGetPayload(wrapper)
    expect(payload.session_id).toBe(42)
    expect(payload.local_file_paths).toEqual(['/tmp/session/uploads/model_a.glb'])
  })

  it('runs the selected pipeline from constructor preflight paths and renders persisted report artifacts', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'three_d_analysis_pipeline',
        name: '3D Analysis Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'profile_model',
            name: 'Profile Model',
            component_ref: 'convert_model',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
          },
        ],
      },
    })

    await wrapper.get('[data-testid="preflight-session-id"]').setValue('42')
    await wrapper.get('[data-testid="preflight-local-file-paths"]').setValue('/tmp/model.glb')
    mocked.pipelineService.preflightPipelineConstructor.mockResolvedValue({ data: { valid: true, validation: { valid: true }, steps: [] } })
    await wrapper.get('[data-testid="run-preflight"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="run-pipeline-execution"]').trigger('click')
    await flushPromises()

    expect(mocked.pipelineService.executePipelineOnFiles).toHaveBeenCalledWith(
      42,
      ['/tmp/model.glb'],
      true,
      'three_d_analysis_pipeline',
      expect.objectContaining({ abortOnCriticalError: true, asyncExecution: true, requestId: expect.any(String), expectedVersion: '1.0.0' }),
    )
    expect(mocked.pipelineService.getPipelineRun).toHaveBeenCalledWith('run-3d')
    expect(wrapper.text()).toContain('profile_model')
    expect(wrapper.text()).toContain('sample_model_profiler_report.json')
    expect(wrapper.text()).toContain('/tmp/report.json')
  })

  it('hides admin intake for non-admin pipeline authors on the tools route', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'author_pipeline',
        name: 'Author Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [],
      },
      user: {
        id: 2,
        role: 'user',
        capabilities_json: ['native_pipeline_author'],
      },
      routePath: '/tools/pipeline-constructor',
    })

    expect(wrapper.text()).toContain('Pipeline Constructor')
    expect(wrapper.text()).not.toContain('Admin Intake')
  })

  it('supports bulk replacement from the preflight session file browser', async () => {
    const wrapper = await mountConstructorView({
      pipelineConfig: {
        identifier: 'preflight_bulk_pipeline',
        name: 'Preflight Bulk Pipeline',
        version: '1.0.0',
        status: 'active',
        modality: '3D Model',
        processingMode: 'root',
        steps: [
          {
            id: 'consume',
            name: 'Consume',
            component_ref: 'consumer',
            execution_profile_ref: 'builtin_default',
            scope: 'record',
          },
        ],
      },
    })

    mocked.fileService.getNodes.mockResolvedValue({
      data: {
        nodes: [
          {
            absolute_path: '/tmp/session/uploads',
            relative_path: 'uploads',
            children: [
              {
                absolute_path: '/tmp/session/uploads/model_a.glb',
                relative_path: 'uploads/model_a.glb',
                children: [],
              },
              {
                absolute_path: '/tmp/session/uploads/model_b.glb',
                relative_path: 'uploads/model_b.glb',
                children: [],
              },
              {
                absolute_path: '/tmp/session/uploads/model_c.ply',
                relative_path: 'uploads/model_c.ply',
                children: [],
              },
            ],
          },
        ],
      },
    })
    mocked.pipelineService.preflightPipelineConstructor.mockResolvedValue({
      data: {
        valid: true,
        validation: {
          valid: true,
          errors: [],
          warnings: [],
        },
        steps: [],
      },
    })

    await wrapper.get('[data-testid="preflight-session-id"]').setValue('42')
    await flushPromises()

    await wrapper.get('[data-testid="preflight-session-files-search"]').setValue('model_b')
    await wrapper.get('[data-testid="preflight-session-files-bulk-replace_all_matching"]').trigger('click')

    const localPaths = wrapper.get('[data-testid="preflight-local-file-paths"]')
    expect(localPaths.element.value).toBe('/tmp/session/uploads/model_b.glb')

    const payload = await runPreflightAndGetPayload(wrapper)
    expect(payload.local_file_paths).toEqual(['/tmp/session/uploads/model_b.glb'])
  })
  const reliabilityConfig = {
    identifier: 'reliable', name: 'Reliable pipeline', version: '1.0.0', steps: [
      { id: 'consume', name: 'Consume', component_ref: 'consumer', execution_profile_ref: 'builtin_default', scope: 'record' },
    ],
  }

  it('invalidates validation on edits and ignores late validation responses', async () => {
    const wrapper = await mountConstructorView({ pipelineConfig: reliabilityConfig })
    let resolve
    mocked.pipelineService.validatePipelineConfig.mockImplementation(() => new Promise(done => { resolve = done }))
    await wrapper.get('[data-testid="validate-pipeline"]').trigger('click')
    await wrapper.get('input[aria-label="Name"]').setValue('Changed during validation')
    resolve({ data: { valid: true, errors: [], warnings: [] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Not checked for current edits')
    expect(wrapper.text()).toContain('Unpublished changes')
    expect(wrapper.get('[data-testid="run-pipeline-execution"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('requires fresh preflight after file changes and publication after definition changes', async () => {
    const wrapper = await mountConstructorView({ pipelineConfig: reliabilityConfig })
    await wrapper.get('[data-testid="preflight-session-id"]').setValue('42')
    await wrapper.get('[data-testid="preflight-local-file-paths"]').setValue('/tmp/model.glb')
    mocked.pipelineService.preflightPipelineConstructor.mockResolvedValue({ data: { valid: true, validation: { valid: true }, steps: [] } })
    await wrapper.get('[data-testid="run-preflight"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="run-pipeline-execution"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="preflight-local-file-paths"]').setValue('/tmp/other.glb')
    expect(wrapper.get('[data-testid="run-pipeline-execution"]').attributes('disabled')).toBeDefined()
    await wrapper.get('input[aria-label="Name"]').setValue('Unpublished revision')
    expect(wrapper.text()).toContain('Publish these changes before running')
    expect(mocked.pipelineService.executePipelineOnFiles).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('revokes the previous preflight when a repeated check fails to complete', async () => {
    const wrapper = await mountConstructorView({ pipelineConfig: reliabilityConfig })
    await wrapper.get('[data-testid="preflight-session-id"]').setValue('42')
    await wrapper.get('[data-testid="preflight-local-file-paths"]').setValue('/tmp/model.glb')
    mocked.pipelineService.preflightPipelineConstructor.mockResolvedValueOnce({ data: { valid: true, validation: { valid: true }, steps: [] } })
    await wrapper.get('[data-testid="run-preflight"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="run-pipeline-execution"]').attributes('disabled')).toBeUndefined()
    mocked.pipelineService.preflightPipelineConstructor.mockRejectedValueOnce(new Error('Connection interrupted'))
    await wrapper.get('[data-testid="run-preflight"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="run-pipeline-execution"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Connection interrupted')
    wrapper.unmount()
  })

  it('does not publish a definition that server validation rejected', async () => {
    const wrapper = await mountConstructorView({ pipelineConfig: reliabilityConfig })
    mocked.pipelineService.validatePipelineConfig.mockResolvedValue({ data: { valid: false, errors: ['Missing input source'] } })
    await wrapper.findAll('button').find(button => button.text() === 'Publish Version').trigger('click')
    await flushPromises()
    expect(mocked.pipelineService.createPipelineVersion).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Missing input source')
    wrapper.unmount()
  })

  it('keeps the editor when discarding changes is cancelled', async () => {
    const wrapper = await mountConstructorView({ pipelineConfig: reliabilityConfig })
    await wrapper.get('input[aria-label="Name"]').setValue('Keep this work')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await wrapper.findAll('button').find(button => button.text() === 'New Pipeline').trigger('click')
    expect(wrapper.get('input[aria-label="Name"]').element.value).toBe('Keep this work')
    expect(confirm).toHaveBeenCalledOnce()
    confirm.mockRestore()
    wrapper.unmount()
  })

  it('preserves unpublished edits when importing a component', async () => {
    const wrapper = await mountConstructorView({ pipelineConfig: reliabilityConfig })
    await wrapper.get('input[aria-label="Name"]').setValue('Keep after import')
    const path = wrapper.findAll('input').find(input => input.attributes('placeholder')?.includes('component'))
    await path.setValue('/srv/components/example/component.yaml')
    mocked.pipelineService.importComponent.mockResolvedValue({ data: {} })
    const importButton = wrapper.findAll('button').find(button => button.text() === 'Import')
    await importButton.trigger('click')
    await flushPromises()
    expect(wrapper.get('input[aria-label="Name"]').element.value).toBe('Keep after import')
    expect(mocked.pipelineService.getPipeline).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('warns about dependent steps and restores removed connections with Undo', async () => {
    const wrapper = await mountConstructorView({ pipelineConfig: { ...reliabilityConfig, steps: [
      { id: 'produce', name: 'Produce', component_ref: 'consumer' },
      { id: 'consume', name: 'Consume', component_ref: 'consumer', input_bindings: [{ kind: 'input', target: 'input_file', type: 'artifact_file', source_step: 'produce', source_output: 'output_file' }] },
    ] } })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    await wrapper.get('[data-testid="step-card-produce"]').findAll('button').find(button => button.text() === 'Remove').trigger('click')
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Consume'))
    expect(wrapper.text()).toContain('source “produce” is missing')
    await wrapper.findAll('button').find(button => button.text().startsWith('Undo last step')).trigger('click')
    expect(wrapper.find('[data-testid="step-card-produce"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('source “produce” is missing')
    confirm.mockRestore()
    wrapper.unmount()
  })

  it('keeps the editor usable while advanced JSON has invalid binding shapes', async () => {
    const wrapper = await mountConstructorView({ pipelineConfig: reliabilityConfig })
    const card = wrapper.find('[data-testid^="step-card-"]')
    await card.get('[data-tab="advanced"]').trigger('click')
    for (const value of ['null', '{"input_bindings": {}}', '{"parameter_bindings": [null]}', '{']) {
      await card.get('textarea[data-testid^="advanced-json-"]').setValue(value)
      expect(wrapper.text()).toContain('Pipeline Constructor')
    }
    wrapper.unmount()
  })

  it('flags a moved source immediately and provides keyboard-accessible settings tabs', async () => {
    const wrapper = await mountConstructorView({ pipelineConfig: { ...reliabilityConfig, steps: [
      { id: 'produce', name: 'Produce', component_ref: 'consumer' },
      { id: 'consume', name: 'Consume', component_ref: 'consumer', input_bindings: [{ kind: 'input', target: 'input_file', type: 'artifact_file', source_step: 'produce', source_output: 'output_file' }] },
    ] } })
    const card = wrapper.get('[data-testid="step-card-produce"]')
    await card.findAll('button').find(button => button.text() === 'Down').trigger('click')
    expect(wrapper.text()).toContain('source “produce” must appear earlier')
    await card.get('[role="tablist"]').trigger('keydown', { key: 'ArrowRight' })
    expect(card.get('[data-tab="parameters"]').attributes('aria-selected')).toBe('true')
    wrapper.unmount()
  })

})
