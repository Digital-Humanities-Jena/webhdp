import { expect, test } from 'vitest'

import {
  buildPlaygroundArtifactGroups,
  buildPlaygroundOutputSummary,
  canInlinePreviewModel,
  isImageExtension,
  isModelExtension
} from '../src/utils/playgroundResults.js'

const schema = {
  outputs: [
    { name: 'output_path', label: 'Output Path', description: 'Primary output' },
    { name: 'thumbnail_files', label: 'Thumbnails', description: '' }
  ],
  result: {
    artifact_views: [
      { id: 'images', label: 'Rendered Images', widget: 'image_gallery', extensions: ['.png', '.jpg'] },
      { id: 'models', label: 'Models', widget: 'model_viewer', extensions: ['.glb', '.gltf', '.usdz'] }
    ]
  }
}

const result = {
  outputs: {
    output_path: '/tmp/output/model.usdz',
    thumbnail_files: ['/tmp/output/model.png']
  },
  artifacts: [
    { name: 'model.png', path: '/tmp/output/model.png' },
    { name: 'scene.glb', path: '/tmp/output/scene.glb' },
    { name: 'model.usdz', path: '/tmp/output/model.usdz' }
  ]
}

test('artifact helpers classify supported preview types', () => {
  expect(isImageExtension('/tmp/output/model.png')).toBe(true)
  expect(isModelExtension('/tmp/output/scene.glb')).toBe(true)
  expect(canInlinePreviewModel('/tmp/output/scene.glb')).toBe(true)
  expect(canInlinePreviewModel('/tmp/output/model.usdz')).toBe(false)
})

test('buildPlaygroundArtifactGroups groups artifacts by configured views', () => {
  const groups = buildPlaygroundArtifactGroups(result, schema)
  expect(groups).toHaveLength(2)
  expect(groups[0].label).toBe('Rendered Images')
  expect(groups[0].items[0].isImage).toBe(true)
  expect(groups[1].label).toBe('Models')
  expect(groups[1].items[0].canInlinePreview).toBe(true)
  expect(groups[1].items[1].canInlinePreview).toBe(false)
})

test('buildPlaygroundOutputSummary matches schema outputs to result outputs', () => {
  const summary = buildPlaygroundOutputSummary(result, schema)
  expect(summary).toHaveLength(2)
  expect(summary[0].label).toBe('Output Path')
  expect(summary[1].value).toEqual(['/tmp/output/model.png'])
})
