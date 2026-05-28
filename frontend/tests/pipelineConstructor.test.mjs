import { expect, test } from 'vitest'

import {
  buildAdvancedJsonPayload,
  buildDefaultBindingForField,
  buildOutputActionSourceKey,
  getCompatibleSourceOutputOptions,
  normalizeTriggerRule,
  serializeTriggerCondition,
  serializeTriggerRule,
} from '../src/utils/pipelineConstructor.js'

let localCounter = 0

function nextLocalKey(prefix) {
  localCounter += 1
  return `${prefix}-${localCounter}`
}

test('buildAdvancedJsonPayload preserves non-structured trigger metadata', () => {
  const structuredAction = {
    action_type: 'zenodo_metadata_field',
    source_output: 'metadata_json',
    selector: '$.title',
    target_field: 'title',
    transform: 'trim',
    overwrite_policy: 'overwrite',
  }
  const rawStep = {
    input_bindings: [
      { target: 'input_file', type: 'pipeline_source_file' },
      { target: 'legacy_binding', type: 'literal', value: 'keep-me' },
    ],
    output_actions: [
      structuredAction,
      { action_type: 'record_warning', source_output: 'warning_text', transform: 'trim' },
    ],
    resources: { cache: true },
    triggers: {
      default_behavior: 'run',
      rules: [{ id: 'mesh_rule', action: 'run' }],
      match_mode: 'first_match',
      legacy_window: { max_files: 10 },
    },
  }

  const advanced = JSON.parse(
    buildAdvancedJsonPayload(rawStep, ['input_file'], [{ __sourceKey: buildOutputActionSourceKey(structuredAction) }])
  )

  expect(advanced.input_bindings).toEqual([{ target: 'legacy_binding', type: 'literal', value: 'keep-me' }])
  expect(advanced.output_actions).toEqual([{ action_type: 'record_warning', source_output: 'warning_text', transform: 'trim' }])
  expect(advanced.resources).toEqual({ cache: true })
  expect(advanced.triggers).toEqual({
    match_mode: 'first_match',
    legacy_window: { max_files: 10 },
  })
})

test('trigger rule normalization and serialization preserve advanced rule and condition fields', () => {
  localCounter = 0
  const normalized = normalizeTriggerRule(
    {
      id: 'point_cloud_rule',
      label: 'Point cloud',
      action: 'run',
      priority: 5,
      conditions: [
        {
          source_type: 'classifier_output',
          source_step: 'classify',
          source_output: 'classification_json',
          field: '$.asset.model_kind',
          operator: 'eq',
          value: 'point_cloud',
          comparator_hint: 'case_sensitive',
        },
      ],
      parameter_overrides: { resolution: 2048 },
      execution_hint: 'gpu-heavy',
    },
    nextLocalKey
  )

  const serialized = serializeTriggerRule(
    normalized,
    normalized.conditions.map((condition) =>
      serializeTriggerCondition(condition, {
        source_type: condition.source_type,
        source_step: condition.source_step,
        source_output: condition.source_output,
        field: condition.field,
        operator: condition.operator,
        value: 'point_cloud',
      })
    ),
    { resolution: 4096 }
  )

  expect(serialized.execution_hint).toBe('gpu-heavy')
  expect(serialized.conditions[0].comparator_hint).toBe('case_sensitive')
  expect(serialized.parameter_overrides.resolution).toBe(4096)
  expect(serialized.conditions[0].field).toBe('$.asset.model_kind')
})

test('buildDefaultBindingForField prefers a unique compatible prior output', () => {
  const binding = buildDefaultBindingForField(
    { name: 'input_file', type: 'file_path' },
    [
      {
        id: 'convert',
        outputs: [{ name: 'output_path', type: 'file_path' }],
      },
    ]
  )

  expect(binding).toEqual({
    enabled: true,
    target: 'input_file',
    type: 'artifact_file',
    source_step: 'convert',
    source_output: 'output_path',
    selector: '',
  })
})

test('getCompatibleSourceOutputOptions filters outputs by input compatibility', () => {
  const outputs = [
    { name: 'rendered_model', type: 'file_path', label: 'Rendered Model' },
    { name: 'render_dir', type: 'dir_path', label: 'Render Directory' },
    { name: 'metadata_json', type: 'json', label: 'Metadata' },
  ]

  expect(
    getCompatibleSourceOutputOptions({ type: 'file_list' }, outputs),
  ).toEqual([
      { value: 'rendered_model', label: 'Rendered Model' },
      { value: 'render_dir', label: 'Render Directory' },
    ])
  expect(
    getCompatibleSourceOutputOptions({ type: 'json' }, outputs),
  ).toEqual([
      { value: 'rendered_model', label: 'Rendered Model' },
      { value: 'metadata_json', label: 'Metadata' },
    ])
})
