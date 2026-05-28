function normalizeExtension(path) {
  const value = String(path || '').trim().toLowerCase()
  const lastDot = value.lastIndexOf('.')
  return lastDot >= 0 ? value.slice(lastDot) : ''
}

export function isImageExtension(path) {
  return ['.png', '.jpg', '.jpeg', '.webp', '.gif'].includes(normalizeExtension(path))
}

export function isModelExtension(path) {
  return ['.glb', '.gltf', '.usdz', '.obj', '.fbx', '.ply', '.stl', '.usd', '.usda', '.usdc', '.dae', '.abc'].includes(normalizeExtension(path))
}

export function canInlinePreviewModel(path) {
  return ['.glb', '.gltf'].includes(normalizeExtension(path))
}

function matchArtifactView(artifact, artifactViews) {
  const artifactPath = String(artifact?.path || '').trim()
  const extension = normalizeExtension(artifactPath)
  const views = Array.isArray(artifactViews) ? artifactViews : []
  const matchedView = views.find((view) => {
    const extensions = Array.isArray(view?.extensions) ? view.extensions.map((item) => String(item).toLowerCase()) : []
    return extensions.length > 0 && extensions.includes(extension)
  })
  if (matchedView) {
    return matchedView
  }
  return {
    id: 'other-files',
    label: 'Other Files',
    widget: 'file_download',
    extensions: []
  }
}

export function buildPlaygroundArtifactGroups(result, schema) {
  const artifacts = Array.isArray(result?.artifacts) ? result.artifacts : []
  const artifactViews = schema?.result?.artifact_views || []
  const groups = new Map()

  artifacts.forEach((artifact, index) => {
    const view = matchArtifactView(artifact, artifactViews)
    const existingGroup = groups.get(view.id)
    const currentItems = existingGroup ? [...existingGroup.items] : []
    currentItems.push({
      ...artifact,
      index,
      extension: normalizeExtension(artifact?.path),
      widget: view.widget,
      canInlinePreview: view.widget === 'image_gallery' || (view.widget === 'model_viewer' && canInlinePreviewModel(artifact?.path)),
      isImage: isImageExtension(artifact?.path),
      isModel: isModelExtension(artifact?.path)
    })
    groups.set(view.id, {
      id: view.id,
      label: view.label,
      widget: view.widget,
      items: currentItems
    })
  })

  return Array.from(groups.values())
}

export function buildPlaygroundOutputSummary(result, schema) {
  const outputs = result?.outputs && typeof result.outputs === 'object' ? result.outputs : {}
  const outputDefinitions = Array.isArray(schema?.outputs) ? schema.outputs : []
  return outputDefinitions
    .map((definition) => ({
      name: definition.name,
      label: definition.label || definition.name,
      description: definition.description || '',
      value: outputs[definition.name]
    }))
    .filter((entry) => entry.value !== undefined && entry.value !== null && entry.value !== '')
}
