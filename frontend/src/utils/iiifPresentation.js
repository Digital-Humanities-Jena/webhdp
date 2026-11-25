export const IIIF_PRESENTATION_LABEL = 'IIIF Presentation 4.0 RC'
export const IIIF_VIEWER_MATRIX_URL = 'https://iiif.io/api/cookbook/recipe/matrix-v4/'
export const IIIF_ADMIN_SAMPLE_ID = 'https://example.invalid/webhdp/iiif-preview.glb'

const presentationContext = /^https?:\/\/iiif\.io\/api\/presentation\/([34])\/context\.json$/
const gltfMediaTypes = new Set(['model/gltf-binary', 'model/gltf+json'])
const gltfPath = /\.(?:glb|gltf)(?:\/content)?$/i
const zenodoOrigins = new Set(['https://zenodo.org', 'https://sandbox.zenodo.org'])
const zenodoContentPath = /^\/api\/records\/[1-9][0-9]*\/files\/[^/]+\/content$/
const credentialParameter = /token|secret|password|passphrase|signature|credential|api[-_]?key|^sig$/i
const transformLabels = {
  TranslateTransform: 'Translate',
  RotateTransform: 'Rotate',
  ScaleTransform: 'Scale'
}

function asArray(value) {
  return Array.isArray(value) ? value : value == null ? [] : [value]
}

function firstLabel(label) {
  return label && typeof label === 'object'
    ? Object.values(label).flat().find(value => typeof value === 'string' && value.trim())
    : undefined
}

function xyz(resource) {
  const values = [resource?.x, resource?.y, resource?.z]
  return values.every(Number.isFinite) ? values : null
}

function modelAsset(body, annotation, label) {
  const model = body?.type === 'SpecificResource' ? body.source : body
  if (model?.type !== 'Model' || typeof model.id !== 'string') return null
  let url
  try { url = new URL(model.id) } catch { return null }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null
  if ([...url.searchParams.keys()].some(key => credentialParameter.test(key))) return null

  const format = typeof model.format === 'string' ? model.format.toLowerCase() : ''
  const previewable = gltfMediaTypes.has(format) ||
    ((!format || format === 'application/octet-stream') && gltfPath.test(url.pathname))
  const transforms = asArray(body?.transform)
    .filter(transform => Object.hasOwn(transformLabels, transform?.type) && xyz(transform))
    .map(transform => ({ name: transformLabels[transform.type], values: xyz(transform) }))
  const point = asArray(annotation.target)
    .filter(target => target?.type === 'SpecificResource')
    .flatMap(target => asArray(target.selector))
    .find(selector => selector?.type === 'PointSelector' && xyz(selector))
  return { url: url.href, format, label: firstLabel(model.label) || label, previewable, transforms, point: xyz(point) }
}

export function iiifInlineModelUrl(model, appOrigin, adminSampleUrl) {
  if (!model?.previewable) return ''
  if (model.url === IIIF_ADMIN_SAMPLE_ID && adminSampleUrl) return adminSampleUrl
  const url = new URL(model.url)
  if (url.origin === appOrigin && gltfPath.test(url.pathname)) return url.href
  if (zenodoOrigins.has(url.origin) && zenodoContentPath.test(url.pathname)) return url.href
  return ''
}

export function inspectIiifManifest(content) {
  let manifest = content
  if (typeof content === 'string') {
    try { manifest = JSON.parse(content) } catch { return null }
  }
  if (manifest?.type !== 'Manifest') return null
  const versions = asArray(manifest['@context']).map(context => (
    typeof context === 'string' ? context.match(presentationContext)?.[1] : null
  ))
  const version = versions.at(-1)
  if (version === '3') return { versionLabel: 'IIIF Presentation 3.0', scenes: [] }
  if (version !== '4' || versions.slice(0, -1).includes('4')) return null

  const scenes = asArray(manifest.items).filter(item => item?.type === 'Scene').map(scene => {
    const label = firstLabel(scene.label) || firstLabel(manifest.label) || 'Scene'
    const painting = asArray(scene.items).flatMap(page => asArray(page?.items))
      .filter(annotation => asArray(annotation?.motivation).includes('painting'))
    const models = painting.flatMap(annotation => (
      asArray(annotation.body).map(body => modelAsset(body, annotation, label)).filter(Boolean)
    ))
    return { label, models }
  })
  return { versionLabel: IIIF_PRESENTATION_LABEL, scenes }
}
