function deepClone(value) {
  if (value === undefined) {
    return undefined
  }
  return JSON.parse(JSON.stringify(value))
}

function normalizeLegacyField(rawField, kind, groupTitle = '', groupDescription = '') {
  const field = rawField && typeof rawField === 'object' ? rawField : {}
  const type = String(field.type || 'string').trim().toLowerCase()
  let widget = 'text_input'
  if (type === 'boolean') widget = 'checkbox'
  else if (type === 'string_dropdown') widget = 'select'
  else if (type === 'integer' || type === 'number') widget = 'number_input'
  else if (type === 'text') widget = 'textarea'
  else if (type === 'json') widget = 'json_editor'
  else if (type === 'file_path') widget = 'file_picker'
  else if (type === 'dir_path') widget = 'directory_picker'
  else if (type === 'file_list') widget = 'file_list_picker'

  return {
    name: String(field.name || '').trim(),
    label: String(field.label || field.name || '').trim(),
    description: String(field.description || '').trim(),
    kind,
    type,
    widget,
    required: field.required === true,
    default: deepClone(field.default),
    options: Array.isArray(field.options) ? field.options.map((option) => String(option)) : [],
    placeholder: null,
    help_text: null,
    rows: widget === 'textarea' || widget === 'json_editor' ? 6 : null,
    path_source: type === 'dir_path' ? 'directories' : (type === 'file_path' || type === 'file_list' ? 'files' : null),
    accept_extensions: [],
    accept_mime_types: [],
    preview_kind: null,
    item_type: null,
    group_title: groupTitle || null,
    group_description: groupDescription || null,
    constraints: {
      mutex_with: Array.isArray(field.mutex_with) ? field.mutex_with.map((item) => String(item)) : [],
      visible_if: null
    }
  }
}

function buildLegacySchema(component) {
  const manifest = component?.manifest || {}
  const inputs = Array.isArray(manifest?.inputs)
    ? manifest.inputs.map((field) => normalizeLegacyField(field, 'input')).filter((field) => field.name)
    : []
  const parameterGroups = Array.isArray(manifest?.parameter_groups)
    ? manifest.parameter_groups
      .map((group) => {
        const title = String(group?.title || 'Parameters').trim()
        const description = String(group?.description || '').trim()
        const fields = Array.isArray(group?.parameters)
          ? group.parameters
            .map((field) => normalizeLegacyField(field, 'parameter', title, description))
            .filter((field) => field.name)
          : []
        return {
          title,
          description,
          fields
        }
      })
      .filter((group) => group.fields.length > 0)
    : []

  return {
    version: 0,
    component_key: component?.key || manifest?.metadata?.name || '',
    title: manifest?.metadata?.label || component?.name || component?.key || '',
    description: manifest?.metadata?.description || component?.description || '',
    metadata: {
      name: manifest?.metadata?.name || component?.key || '',
      label: manifest?.metadata?.label || component?.name || component?.key || '',
      version: manifest?.metadata?.version || component?.version || '',
      tags: Array.isArray(manifest?.metadata?.tags) ? manifest.metadata.tags.map((tag) => String(tag)) : [],
      keywords: Array.isArray(manifest?.metadata?.keywords) ? manifest.metadata.keywords.map((tag) => String(tag)) : [],
      category: manifest?.metadata?.category || null
    },
    inputs,
    outputs: Array.isArray(manifest?.outputs) ? manifest.outputs.map((output) => ({
      name: String(output?.name || '').trim(),
      label: String(output?.label || output?.name || '').trim(),
      description: String(output?.description || '').trim(),
      type: String(output?.type || '').trim().toLowerCase(),
      default: deepClone(output?.default)
    })) : [],
    parameter_groups: parameterGroups,
    result: {
      artifact_views: [
        { id: 'images', label: 'Image Outputs', widget: 'image_gallery', extensions: ['.png', '.jpg', '.jpeg', '.webp', '.gif'] },
        { id: 'models', label: '3D Outputs', widget: 'model_viewer', extensions: ['.glb', '.gltf', '.usdz', '.obj', '.fbx', '.ply', '.stl', '.usd', '.usda', '.usdc', '.dae', '.abc'] },
        { id: 'files', label: 'Files', widget: 'file_download', extensions: [] }
      ],
      show_result_json: true,
      show_logs: true
    }
  }
}

export function getComponentManifest(component) {
  return component?.manifest || {}
}

export function getPlaygroundSchema(component) {
  const schema = component?.playground_schema
  if (schema && typeof schema === 'object') {
    return deepClone(schema)
  }
  return buildLegacySchema(component)
}

export function getPlaygroundInputFields(schema) {
  return Array.isArray(schema?.inputs) ? schema.inputs : []
}

export function getPlaygroundParameterGroups(schema) {
  return Array.isArray(schema?.parameter_groups) ? schema.parameter_groups : []
}

export function getPlaygroundOutputDefinitions(schema) {
  return Array.isArray(schema?.outputs) ? schema.outputs : []
}

export function getPlaygroundResultSchema(schema) {
  return schema?.result && typeof schema.result === 'object'
    ? schema.result
    : { artifact_views: [], show_result_json: true, show_logs: true }
}

export function getAllPlaygroundFields(schema) {
  const fields = [...getPlaygroundInputFields(schema)]
  getPlaygroundParameterGroups(schema).forEach((group) => {
    group.fields.forEach((field) => fields.push(field))
  })
  return fields
}

function defaultFieldValue(field) {
  const fieldType = String(field?.type || '').trim().toLowerCase()
  const widget = String(field?.widget || '').trim()
  const defaultValue = deepClone(field?.default)

  if (fieldType === 'json' || widget === 'json_editor') {
    if (defaultValue === undefined || defaultValue === null || defaultValue === '') {
      return ''
    }
    return JSON.stringify(defaultValue, null, 2)
  }

  if (fieldType === 'file_list' || widget === 'file_list_picker') {
    if (Array.isArray(defaultValue)) {
      return defaultValue.join('\n')
    }
    if (typeof defaultValue === 'string') {
      return defaultValue
    }
    return ''
  }

  if (fieldType.startsWith('array[') || widget === 'array_editor') {
    if (Array.isArray(defaultValue)) {
      return defaultValue.join('\n')
    }
    return ''
  }

  if (widget === 'checkbox' || fieldType === 'boolean') {
    return typeof defaultValue === 'boolean' ? defaultValue : false
  }

  if (defaultValue === undefined || defaultValue === null) {
    return ''
  }
  return defaultValue
}

export function buildPlaygroundFormState(schema, request = {}) {
  const inputs = {}
  const parameters = {}

  getPlaygroundInputFields(schema).forEach((field) => {
    inputs[field.name] = defaultFieldValue({ ...field, default: request.inputs?.[field.name] ?? field.default })
  })
  getPlaygroundParameterGroups(schema).forEach((group) => {
    group.fields.forEach((field) => {
      parameters[field.name] = defaultFieldValue({ ...field, default: request.parameters?.[field.name] ?? field.default })
    })
  })
  return { inputs, parameters }
}

export function serializePlaygroundFieldValue(field, rawValue) {
  const fieldType = String(field?.type || '').trim().toLowerCase()
  const widget = String(field?.widget || '').trim()

  if (fieldType === 'json' || widget === 'json_editor') {
    const text = String(rawValue ?? '').trim()
    if (!text) {
      return undefined
    }
    try {
      return JSON.parse(text)
    } catch {
      throw new Error(`${field.label || field.name} must contain valid JSON.`)
    }
  }

  if (fieldType === 'file_list' || widget === 'file_list_picker') {
    return String(rawValue ?? '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
  }

  if (fieldType.startsWith('array[') || widget === 'array_editor') {
    const itemType = String(field?.item_type || fieldType.slice(6, -1) || 'string').trim().toLowerCase()
    return String(rawValue ?? '')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((item) => {
        if (itemType === 'integer') {
          const parsed = Number.parseInt(item, 10)
          if (!Number.isInteger(parsed)) {
            throw new Error(`${field.label || field.name} must contain integers only.`)
          }
          return parsed
        }
        if (itemType === 'number') {
          const parsed = Number(item)
          if (!Number.isFinite(parsed)) {
            throw new Error(`${field.label || field.name} must contain numbers only.`)
          }
          return parsed
        }
        return item
      })
  }

  if (widget === 'checkbox' || fieldType === 'boolean') {
    return rawValue === true
  }

  if (fieldType === 'integer') {
    const text = String(rawValue ?? '').trim()
    if (!text) {
      return undefined
    }
    const parsed = Number.parseInt(text, 10)
    if (!Number.isInteger(parsed)) {
      throw new Error(`${field.label || field.name} must be an integer.`)
    }
    return parsed
  }

  if (fieldType === 'number') {
    const text = String(rawValue ?? '').trim()
    if (!text) {
      return undefined
    }
    const parsed = Number(text)
    if (!Number.isFinite(parsed)) {
      throw new Error(`${field.label || field.name} must be a number.`)
    }
    return parsed
  }

  return String(rawValue ?? '').trim()
}

export function isPlaygroundValueMissing(value) {
  if (value === undefined || value === null) {
    return true
  }
  if (typeof value === 'string') {
    return value.trim() === ''
  }
  if (Array.isArray(value)) {
    return value.length === 0
  }
  return false
}

export function buildPlaygroundFieldIndex(schema) {
  return getAllPlaygroundFields(schema).reduce((index, field) => {
    index[field.name] = field
    return index
  }, {})
}

export function flattenFormValues(formState) {
  return {
    ...(formState?.inputs || {}),
    ...(formState?.parameters || {})
  }
}

export function isPlaygroundFieldVisible(field, combinedValues) {
  const visibleIf = field?.constraints?.visible_if
  if (!visibleIf || typeof visibleIf !== 'object') {
    return true
  }
  const currentValue = combinedValues?.[visibleIf.field]
  if (Object.prototype.hasOwnProperty.call(visibleIf, 'truthy')) {
    return visibleIf.truthy ? !isPlaygroundValueMissing(currentValue) && currentValue !== false : isPlaygroundValueMissing(currentValue) || currentValue === false
  }
  if (Object.prototype.hasOwnProperty.call(visibleIf, 'equals')) {
    return currentValue === visibleIf.equals
  }
  if (Object.prototype.hasOwnProperty.call(visibleIf, 'not_equals')) {
    return currentValue !== visibleIf.not_equals
  }
  if (Array.isArray(visibleIf.in)) {
    return visibleIf.in.includes(currentValue)
  }
  return true
}

export function formatPlaygroundLogs(run) {
  const logs = run?.logs || run?.result?.logs || {}
  return {
    stdout: String(logs.stdout || '').trim(),
    stderr: String(logs.stderr || '').trim()
  }
}

export function flattenSessionFilePaths(nodes) {
  const output = []
  const queue = Array.isArray(nodes) ? [...nodes] : []

  while (queue.length > 0) {
    const node = queue.shift()
    if (!node || typeof node !== 'object') {
      continue
    }

    const absolutePath = String(node.absolute_path || '').trim()
    const relativePath = String(node.relative_path || '').trim().toLowerCase()
    const children = Array.isArray(node.children) ? node.children : []
    const hasChildren = children.length > 0
    const excluded = relativePath.includes('__macosx') || relativePath.includes('__pycache__')

    if (absolutePath && !hasChildren && !excluded) {
      output.push(absolutePath)
    }

    queue.push(...children)
  }

  return Array.from(new Set(output))
}

export function deriveDirectories(filePaths) {
  return Array.from(new Set(
    (Array.isArray(filePaths) ? filePaths : [])
      .map((path) => {
        const value = String(path || '').trim()
        const lastSlash = value.lastIndexOf('/')
        return lastSlash > 0 ? value.slice(0, lastSlash) : ''
      })
      .filter(Boolean)
  ))
}

export function filterSessionPathsForField(field, filePaths) {
  const acceptExtensions = Array.isArray(field?.accept_extensions)
    ? field.accept_extensions.map((extension) => String(extension).toLowerCase())
    : []
  if (acceptExtensions.length === 0) {
    return Array.isArray(filePaths) ? filePaths : []
  }
  return (Array.isArray(filePaths) ? filePaths : []).filter((path) => {
    const normalizedPath = String(path || '').trim().toLowerCase()
    return acceptExtensions.some((extension) => normalizedPath.endsWith(extension))
  })
}
