import { expect, test } from 'vitest'

import {
  buildPlaygroundFieldIndex,
  buildPlaygroundFormState,
  deriveDirectories,
  filterSessionPathsForField,
  flattenSessionFilePaths,
  getPlaygroundSchema,
  isPlaygroundFieldVisible,
  serializePlaygroundFieldValue
} from '../src/utils/playgroundManifest.js'

const component = {
  key: 'demo_component',
  playground_schema: {
    version: 1,
    title: 'Demo Component',
    description: 'Schema-backed component',
    metadata: {
      name: 'demo_component',
      label: 'Demo Component',
      version: '1.0.0',
      tags: ['demo'],
      category: 'Testing'
    },
    inputs: [
      {
        name: 'image_path',
        label: 'Image Path',
        kind: 'input',
        type: 'file_path',
        widget: 'image_input',
        required: true,
        default: '',
        accept_extensions: ['.png', '.jpg'],
        constraints: { mutex_with: [], visible_if: null }
      }
    ],
    outputs: [],
    parameter_groups: [
      {
        title: 'General',
        description: '',
        fields: [
          {
            name: 'tags',
            label: 'Tags',
            kind: 'parameter',
            type: 'array[string]',
            item_type: 'string',
            widget: 'array_editor',
            required: false,
            default: ['preview', 'demo'],
            constraints: { mutex_with: [], visible_if: null }
          },
          {
            name: 'metadata',
            label: 'Metadata',
            kind: 'parameter',
            type: 'json',
            widget: 'json_editor',
            required: false,
            default: { quality: 'high' },
            constraints: { mutex_with: [], visible_if: null }
          },
          {
            name: 'advanced',
            label: 'Advanced',
            kind: 'parameter',
            type: 'boolean',
            widget: 'checkbox',
            required: false,
            default: false,
            constraints: { mutex_with: ['count'], visible_if: null }
          },
          {
            name: 'count',
            label: 'Count',
            kind: 'parameter',
            type: 'integer',
            widget: 'number_input',
            required: false,
            default: '',
            constraints: {
              mutex_with: ['advanced'],
              visible_if: { field: 'image_path', truthy: true }
            }
          }
        ]
      }
    ],
    result: {
      artifact_views: [],
      show_result_json: true,
      show_logs: true
    }
  }
}

test('getPlaygroundSchema prefers backend-produced schema', () => {
  const schema = getPlaygroundSchema(component)
  expect(schema.title).toBe('Demo Component')
  expect(schema.inputs[0].widget).toBe('image_input')
})

test('buildPlaygroundFormState preserves schema defaults for array and json fields', () => {
  const formState = buildPlaygroundFormState(component.playground_schema)
  expect(formState.inputs.image_path).toBe('')
  expect(formState.parameters.tags).toBe('preview\ndemo')
  expect(formState.parameters.metadata).toBe('{\n  "quality": "high"\n}')
  expect(formState.parameters.advanced).toBe(false)
})

test('serializePlaygroundFieldValue supports arrays, json, and integers', () => {
  const index = buildPlaygroundFieldIndex(component.playground_schema)
  expect(serializePlaygroundFieldValue(index.tags, 'foo\nbar')).toEqual(['foo', 'bar'])
  expect(serializePlaygroundFieldValue(index.metadata, '{"quality":"draft"}')).toEqual({ quality: 'draft' })
  expect(serializePlaygroundFieldValue(index.count, '7')).toBe(7)
})

test('isPlaygroundFieldVisible evaluates visible_if truthy rules', () => {
  const index = buildPlaygroundFieldIndex(component.playground_schema)
  expect(isPlaygroundFieldVisible(index.count, { image_path: '' })).toBe(false)
  expect(isPlaygroundFieldVisible(index.count, { image_path: '/tmp/input.png' })).toBe(true)
})

test('filterSessionPathsForField narrows file suggestions to accepted extensions', () => {
  const imageField = component.playground_schema.inputs[0]
  const filtered = filterSessionPathsForField(imageField, [
    '/tmp/a.png',
    '/tmp/b.jpg',
    '/tmp/c.glb'
  ])
  expect(filtered).toEqual(['/tmp/a.png', '/tmp/b.jpg'])
})

test('flattenSessionFilePaths and deriveDirectories prepare constructor session suggestions', () => {
  const files = flattenSessionFilePaths([
    {
      absolute_path: '/tmp/session/uploads',
      relative_path: 'uploads',
      children: [
        {
          absolute_path: '/tmp/session/uploads/set_a',
          relative_path: 'uploads/set_a',
          children: [
            {
              absolute_path: '/tmp/session/uploads/set_a/model_a.glb',
              relative_path: 'uploads/set_a/model_a.glb',
              children: []
            }
          ]
        },
        {
          absolute_path: '/tmp/session/uploads/set_b/model_b.glb',
          relative_path: 'uploads/set_b/model_b.glb',
          children: []
        },
        {
          absolute_path: '/tmp/session/uploads/__MACOSX/ignored.glb',
          relative_path: 'uploads/__MACOSX/ignored.glb',
          children: []
        }
      ]
    }
  ])

  expect([...files].sort()).toEqual([
    '/tmp/session/uploads/set_a/model_a.glb',
    '/tmp/session/uploads/set_b/model_b.glb'
  ])
  expect([...deriveDirectories(files)].sort()).toEqual([
    '/tmp/session/uploads/set_a',
    '/tmp/session/uploads/set_b'
  ])
})

test('restores saved arrays and JSON into editable widget values', () => {
  const schema = getPlaygroundSchema(component)
  const values = buildPlaygroundFormState(schema, { inputs: { image_path: '/session/image.png' }, parameters: { tags: ['first', 'second'], metadata: { quality: 'low' }, advanced: true } })
  expect(values.inputs.image_path).toBe('/session/image.png')
  expect(values.parameters.tags).toBe('first\nsecond')
  expect(JSON.parse(values.parameters.metadata)).toEqual({ quality: 'low' })
  expect(values.parameters.advanced).toBe(true)
})
